"""basic_chunk_stream.py — 파일 → SpeakerEngine → 콘솔 출력 + finalize.

실행:
    export HF_TOKEN=hf_xxxxx
    export SPEAKER_ENGINE_STORAGE_URL=memory://
    python examples/basic_chunk_stream.py samples/meeting.wav
"""

import asyncio
import sys

from speaker_engine import (
    LabelChange,
    SpeakerEngine,
    SpeakerSegment,
    from_file,
)


async def main(audio_path: str) -> None:
    engine = SpeakerEngine()  # env: HF_TOKEN + SPEAKER_ENGINE_STORAGE_URL

    print(f"처리 중: {audio_path}\n")

    async with engine:
        async for event in engine.stream(from_file(audio_path)):
            if isinstance(event, SpeakerSegment):
                dur = event.t_end - event.t_start
                print(
                    f"[{event.label:<20}] "
                    f"{event.t_start:7.2f}s–{event.t_end:7.2f}s "
                    f"({dur:.2f}s)  conf={event.confidence:.2f}  id={event.utterance_id}"
                )
            elif isinstance(event, LabelChange):
                print(
                    f"  >> LabelChange: {event.old_label} → {event.new_label} "
                    f"[{event.reason}]  affected={len(event.affected_utterance_ids)}개"
                )

        candidates = await engine.finalize()

    print(f"\n{'─'*60}")
    print(f"세션 화자 수: {len(candidates)}")
    for c in candidates:
        print(
            f"  {c.auto_id:<10} "
            f"{c.utterance_count}발화  "
            f"{c.total_duration:.1f}s"
        )


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "samples/meeting.wav"
    asyncio.run(main(path))
