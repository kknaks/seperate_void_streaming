"""auto_play_audio.py — sample WAV → WS demo_v03 자동 송신 (라이브 latency 측정용).

사용:
    DEMO_V03_LATENCY_LOG=1 \
    DEMO_V03_EMBEDDING=pyannote/embedding \
    DEMO_V03_SAMPLE=record_1.wav \
    python scripts/auto_play_audio.py --audio eval/data/korean/record_1.wav --ws ws://localhost:8000/audio/auto-{ts}

server (demo_v03) 가 환경 변수로 embedding/sample 식별 후 JSON 저장.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf
import websockets


CHUNK_MS = 100  # 100 ms 단위 송신 (AudioWorklet 와 유사)
SR = 16000


async def stream_wav(audio_path: Path, ws_url: str) -> None:
    """16kHz mono wav → 100ms PCM int16 청크 → WS 송신 (실시간 속도)."""
    data, sr = sf.read(str(audio_path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != SR:
        raise ValueError(f"sample rate {sr} != {SR} (resample 필요)")
    # float32 [-1, 1] → int16 little-endian
    pcm_i16 = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)
    chunk_samples = SR * CHUNK_MS // 1000
    total_chunks = (len(pcm_i16) + chunk_samples - 1) // chunk_samples
    print(f"[auto_play] audio: {audio_path.name}, duration={len(pcm_i16)/SR:.1f}s, chunks={total_chunks}, chunk={CHUNK_MS}ms")

    async with websockets.connect(ws_url, ping_interval=None, max_size=None) as ws:
        print(f"[auto_play] WS connected: {ws_url}")
        start = time.perf_counter()
        for i in range(total_chunks):
            seg = pcm_i16[i * chunk_samples : (i + 1) * chunk_samples]
            await ws.send(seg.tobytes())
            # 실시간 속도 유지
            target = (i + 1) * (CHUNK_MS / 1000.0)
            now = time.perf_counter() - start
            if now < target:
                await asyncio.sleep(target - now)
        # EOF 신호 (text frame)
        await ws.send(json.dumps({"type": "eof"}))
        print(f"[auto_play] EOF sent. Total wall-clock: {time.perf_counter() - start:.1f}s")
        # 서버 final emit + JSON 저장 대기
        try:
            async for msg in ws:
                if isinstance(msg, str):
                    obj = json.loads(msg)
                    mtype = obj.get("type")
                    if mtype == "done":
                        print("[auto_play] done received")
                        break
        except websockets.ConnectionClosed:
            pass
    print("[auto_play] WS closed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--ws", default=None,
                        help="WS URL (default: ws://localhost:8000/audio/auto-{visit_id})")
    args = parser.parse_args()
    if args.ws is None:
        visit_id = f"auto-{uuid.uuid4().hex[:12]}"
        ws_url = f"ws://localhost:8000/audio/{visit_id}"
    else:
        ws_url = args.ws
    asyncio.run(stream_wav(args.audio, ws_url))


if __name__ == "__main__":
    main()
