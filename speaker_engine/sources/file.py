"""from_file — 파일 오디오 소스 헬퍼 (H-02, spec-01 §2-2)."""

from __future__ import annotations

import asyncio
import logging
import wave
from pathlib import Path
from typing import AsyncIterator

from speaker_engine.audio.format import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

_log = logging.getLogger(__name__)

_CHUNK_SIZE_DEFAULT: int = 3200  # ~100ms @ 16kHz mono 16-bit (1600 samples × 2 bytes)


def _validate_wav(wf: wave.Wave_read, path: Path) -> None:
    sr = wf.getframerate()
    ch = wf.getnchannels()
    sw = wf.getsampwidth()
    if sr != SAMPLE_RATE:
        raise ValueError(
            f"WAV '{path}' sample rate {sr} Hz (expected {SAMPLE_RATE} Hz)"
        )
    if ch != CHANNELS:
        raise ValueError(
            f"WAV '{path}' has {ch} channels (expected {CHANNELS} mono)"
        )
    if sw != SAMPLE_WIDTH:
        raise ValueError(
            f"WAV '{path}' sample width {sw * 8}-bit (expected {SAMPLE_WIDTH * 8}-bit)"
        )


async def from_file(
    path: str | Path,
    chunk_size: int = _CHUNK_SIZE_DEFAULT,
) -> AsyncIterator[bytes]:
    """로컬 파일 (PCM raw 또는 WAV) → bytes 스트림. 테스트/배치 용."""
    path = Path(path)

    # FileNotFoundError propagates naturally from stat()
    if path.stat().st_size == 0:
        return

    use_wav = path.suffix.lower() == ".wav"

    if not use_wav:
        # Header fallback: peek first 4 bytes for RIFF signature
        with open(path, "rb") as f:
            peek = f.read(4)
        use_wav = len(peek) >= 4 and peek[:4] == b"RIFF"

    if use_wav:
        try:
            with wave.open(str(path), "rb") as wf:
                _validate_wav(wf, path)
                frames_per_chunk = max(1, chunk_size // SAMPLE_WIDTH)
                while True:
                    frames = wf.readframes(frames_per_chunk)
                    if not frames:
                        break
                    yield frames
                    await asyncio.sleep(0)
        except wave.Error as exc:
            raise ValueError(f"WAV '{path}' header corrupted: {exc}") from exc
    else:
        with open(path, "rb") as f:
            data = f.read()

        if len(data) % SAMPLE_WIDTH != 0:
            _log.warning(
                "from_file: PCM file '%s' has odd byte count (%d), dropping last byte",
                path,
                len(data),
            )
            data = data[:-1]

        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]
            await asyncio.sleep(0)


__all__ = ["from_file"]
