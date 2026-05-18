"""persist_workflow.py — 첫 세션(auto 분리) → persist → 둘째 세션(stored 재인식).

이 예제는 SQLite 백엔드를 사용한다.
프로세스를 재시작해도 화자 정보가 유지되어 두 번째 세션에서 자동 인식된다.

실행:
    export HF_TOKEN=hf_xxxxx
    python examples/persist_workflow.py samples/first.wav samples/second.wav
"""

import asyncio
import os
import sys

from speaker_engine import (
    LabelChange,
    PersistMapping,
    SpeakerCandidate,
    SpeakerEngine,
    SpeakerSegment,
    from_file,
)

_STORAGE_URL = os.environ.get(
    "SPEAKER_ENGINE_STORAGE_URL",
    "sqlite:///speaker_data.db",
)


async def first_session(audio_path: str) -> list[SpeakerCandidate]:
    """auto:* 분리 → finalize → persist."""
    print(f"\n=== 1차 세션: {audio_path} ===\n")

    engine = SpeakerEngine(storage_url=_STORAGE_URL)

    async with engine:
        async for event in engine.stream(from_file(audio_path)):
            if isinstance(event, SpeakerSegment):
                print(f"  [{event.label}] {event.t_start:.2f}s–{event.t_end:.2f}s")
            elif isinstance(event, LabelChange):
                print(f"  >> {event.old_label} → {event.new_label} [{event.reason}]")

        candidates = await engine.finalize()

    print(f"\n후보 화자:")
    for c in candidates:
        print(f"  {c.auto_id}: {c.utterance_count}발화 / {c.total_duration:.1f}s")

    # 매핑 정의 (실제 환경에서는 사용자 입력 또는 UI 연동)
    mappings: list[PersistMapping] = []
    label_map = {"auto:A": "이지영", "auto:B": "김환자"}
    for c in candidates:
        name = label_map.get(c.auto_id)  # 매핑 없으면 anon_NNN 자동 부여
        mappings.append(PersistMapping(auto_id=c.auto_id, name=name))

    speakers = await engine.persist(mappings)

    print(f"\n영속화 완료:")
    for s in speakers:
        print(f"  {s.name} ({s.origin})  id={s.id}")

    return candidates


async def second_session(audio_path: str) -> None:
    """동일 storage → stored:이름 으로 자동 인식."""
    print(f"\n=== 2차 세션: {audio_path} ===\n")

    engine = SpeakerEngine(storage_url=_STORAGE_URL)

    async with engine:
        async for event in engine.stream(from_file(audio_path)):
            if isinstance(event, SpeakerSegment):
                print(f"  [{event.label}] {event.t_start:.2f}s–{event.t_end:.2f}s")
            elif isinstance(event, LabelChange):
                print(f"  >> {event.old_label} → {event.new_label} [{event.reason}]")

        await engine.finalize()

    print("\n2차 세션 완료.")


if __name__ == "__main__":
    first_path = sys.argv[1] if len(sys.argv) > 1 else "samples/first.wav"
    second_path = sys.argv[2] if len(sys.argv) > 2 else "samples/second.wav"

    asyncio.run(first_session(first_path))
    asyncio.run(second_session(second_path))
