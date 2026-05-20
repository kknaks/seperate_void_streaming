"""WhisperSTT — faster-whisper 기반 STT 어댑터 (spec-06 §1-§4).

인터페이스:
    async def feed(self, chunk: bytes) -> None
    async def flush_window(self, t_start: float, t_end: float) -> str
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_BYTES_PER_SAMPLE = 2  # 16-bit signed PCM
_MIN_DURATION_S = 0.2
_ASR_TIMEOUT_S = 5.0


def _detect_device_and_compute() -> tuple[str, str]:
    """사용 가능한 하드웨어 기준으로 (device, compute_type) 반환."""
    try:
        import torch  # noqa: PLC0415

        if torch.cuda.is_available():
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


class WhisperSTT:
    """faster-whisper 래퍼 — spec-06 §1 인터페이스 구현.

    Pattern B 팬아웃(adr-02): feed() 는 비동기 create_task 로 호출되고,
    flush_window() 는 SpeakerSegment emit 직후 await 된다.
    """

    def __init__(
        self,
        model_size: str = "medium",
        language: str = "ko",
        beam_size: int = 5,
        compute_type: Optional[str] = None,
        device: Optional[str] = None,
    ) -> None:
        if device is None or compute_type is None:
            _device, _compute_type = _detect_device_and_compute()
            device = device or _device
            compute_type = compute_type or _compute_type

        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415

            self._model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
        except ValueError as exc:
            logger.warning("WhisperSTT: %s — fallback to cpu/int8", exc)
            from faster_whisper import WhisperModel  # noqa: PLC0415

            self._model = WhisperModel(model_size, device="cpu", compute_type="int8")

        self._language = language
        self._beam_size = beam_size
        self._buffer = bytearray()
        self._lock = asyncio.Lock()

    async def warmup(self) -> None:
        """더미 1s zero waveform 으로 모델 워밍업 — 서버 기동 시 1회 호출."""
        dummy = np.zeros(_SAMPLE_RATE, dtype=np.float32)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._transcribe_sync, dummy)
        logger.info("WhisperSTT: warmup complete")

    async def feed(self, chunk: bytes) -> None:
        """PCM16 bytes 누적. 반환값 없음 (spec-06 §1)."""
        async with self._lock:
            self._buffer.extend(chunk)

    async def flush_window(self, t_start: float, t_end: float) -> str:
        """누적 PCM 에서 [t_start, t_end] 구간 슬라이스 → ASR → 텍스트 반환.

        - t_end - t_start < 0.2s → "" 즉시 반환 (spec-06 §3)
        - t_end 가 누적 PCM 초과 → 가용분까지만 (spec-06 §OQ-06-1 A안)
        - ASR 5s 초과 → "" + WARNING (spec-06 §4)
        """
        if t_end - t_start < _MIN_DURATION_S:
            return ""

        byte_start = int(t_start * _SAMPLE_RATE) * _BYTES_PER_SAMPLE
        byte_end = int(t_end * _SAMPLE_RATE) * _BYTES_PER_SAMPLE

        async with self._lock:
            pcm_slice = bytes(self._buffer[byte_start:byte_end])

        if not pcm_slice:
            return ""

        pcm_np = np.frombuffer(pcm_slice, dtype=np.int16).astype(np.float32) / 32768.0

        loop = asyncio.get_running_loop()
        try:
            text = await asyncio.wait_for(
                loop.run_in_executor(None, self._transcribe_sync, pcm_np),
                timeout=_ASR_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "WhisperSTT.flush_window: ASR timeout (>%.1fs) t=[%.2f, %.2f]",
                _ASR_TIMEOUT_S,
                t_start,
                t_end,
            )
            return ""

        return text

    def _transcribe_sync(self, pcm: np.ndarray) -> str:
        segments, _ = self._model.transcribe(
            pcm,
            language=self._language,
            beam_size=self._beam_size,
        )
        return "".join(s.text for s in segments).strip()
