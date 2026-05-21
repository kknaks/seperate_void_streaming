"""PcmRingBuffer — 16kHz mono PCM 시간축 누적 버퍼 (PLAN-006-T-004).

STT-driven Sequential Chain (adr-10) 에서 STT final phrase 의
t_start/t_end 로 PCM slice 를 추출하여 engine.identify_phrase 에 전달.

asyncio 단일 이벤트 루프 가정: append/slice 는 non-await sync 메서드이므로
이벤트 루프 내에서 원자적으로 실행됨 — 별도 Lock 불필요.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SAMPLE_RATE: int = 16_000
_BYTES_PER_SAMPLE: int = 2  # 16-bit mono
_BYTES_PER_SECOND: int = _SAMPLE_RATE * _BYTES_PER_SAMPLE  # 32_000


class PcmRingBuffer:
    """16kHz mono PCM 16-bit bytes 시간축 누적 버퍼.

    append() 로 PCM 을 누적하고 slice(t_start, t_end) 로 절대 시간(초)
    기준 PCM 을 추출한다. max_duration_s 초과 시 oldest bytes 를 폐기.
    """

    def __init__(self, max_duration_s: float = 3600.0) -> None:
        self._max_bytes: int = int(max_duration_s * _BYTES_PER_SECOND)
        self._data: bytearray = bytearray()
        # 현재 _data[0] 이 대응하는 절대 시간(초)
        self._t_offset: float = 0.0

    def append(self, pcm_bytes: bytes) -> None:
        """PCM bytes 를 시간축 추적하며 추가. 한도 초과 시 oldest 폐기."""
        self._data.extend(pcm_bytes)
        overflow = len(self._data) - self._max_bytes
        if overflow > 0:
            # sample boundary 정렬 (2 bytes per sample)
            drop = overflow + (overflow % _BYTES_PER_SAMPLE)
            del self._data[:drop]
            self._t_offset += drop / _BYTES_PER_SECOND
            logger.warning(
                "PcmRingBuffer: 세션 길이 한도 초과 — %.3fs 폐기",
                drop / _BYTES_PER_SECOND,
            )

    def slice(self, t_start: float, t_end: float) -> bytes:
        """절대 시간(초) 기준 PCM bytes 반환.

        t_start < _t_offset 인 경우 가용 범위만 반환.
        t_start >= t_end 또는 범위 밖이면 b"" 반환.
        """
        start_byte = int((t_start - self._t_offset) * _BYTES_PER_SECOND)
        end_byte = int((t_end - self._t_offset) * _BYTES_PER_SECOND)
        # sample boundary 정렬
        start_byte = start_byte - (start_byte % _BYTES_PER_SAMPLE)
        end_byte = end_byte - (end_byte % _BYTES_PER_SAMPLE)
        # 범위 클램핑
        start_byte = max(0, start_byte)
        end_byte = max(0, min(len(self._data), end_byte))
        if start_byte >= end_byte:
            return b""
        return bytes(self._data[start_byte:end_byte])

    def duration_s(self) -> float:
        """현재 누적된 PCM 길이 (초)."""
        return len(self._data) / _BYTES_PER_SECOND
