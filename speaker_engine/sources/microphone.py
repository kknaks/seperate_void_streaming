"""from_microphone — 마이크 오디오 소스 헬퍼 (H-03, extras [microphone], spec-01 §2-2)."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

_log = logging.getLogger(__name__)

_CHUNK_SIZE_DEFAULT: int = 3200  # ~100ms @ 16kHz mono 16-bit (1600 samples × 2 bytes)
_QUEUE_MAXSIZE: int = 100


async def from_microphone(
    device: int | str | None = None,
    chunk_size: int = _CHUNK_SIZE_DEFAULT,
) -> AsyncIterator[bytes]:
    """sounddevice 마이크 → bytes 스트림. 로컬 데모 용.

    16kHz / mono / 16-bit 강제. extras [microphone] (sounddevice) 필요.
    사용자 중단 (asyncio.CancelledError / aclose) 시 graceful 종료.
    """
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise ImportError(
            "from_microphone() 사용에 sounddevice 가 필요합니다. "
            "설치: pip install 'speaker_engine[microphone]'"
        ) from exc

    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    loop = asyncio.get_running_loop()

    def callback(indata, frames, time, status) -> None:  # type: ignore[misc]
        # sounddevice callback thread → event loop bridge
        chunk = indata.tobytes()

        def _try_put() -> None:
            try:
                queue.put_nowait(chunk)
            except asyncio.QueueFull:
                _log.warning("from_microphone: queue full, dropping audio chunk")

        loop.call_soon_threadsafe(_try_put)

    blocksize = max(1, chunk_size // 2)  # bytes → frames (int16 = 2 bytes/sample)

    with sd.InputStream(
        samplerate=16000,
        channels=1,
        dtype="int16",
        device=device,
        callback=callback,
        blocksize=blocksize,
    ):
        try:
            while True:
                chunk = await queue.get()
                yield chunk
        except asyncio.CancelledError:
            raise


__all__ = ["from_microphone"]
