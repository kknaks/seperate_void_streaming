"""PCM 포맷 검증 + bytes → float32 변환 유틸 (spec-01 §5, adr-06)."""

from __future__ import annotations

import numpy as np

SAMPLE_RATE: int = 16000
CHANNELS: int = 1
SAMPLE_WIDTH: int = 2  # 16-bit = 2 bytes
INT16_MAX: float = 32768.0


def validate_pcm(
    chunk: bytes,
    *,
    sample_rate: int = SAMPLE_RATE,
    channels: int = CHANNELS,
) -> None:
    """PCM 포맷 검증. 위반 시 ValueError.

    Parameters
    ----------
    chunk:
        raw PCM bytes.
    sample_rate:
        기대 sample rate. 16000 외 다른 값을 넘기면 항상 ValueError.
    channels:
        기대 채널 수. 1 외 다른 값을 넘기면 항상 ValueError.
    """
    if sample_rate != SAMPLE_RATE:
        raise ValueError(
            f"sample_rate must be {SAMPLE_RATE} Hz, got {sample_rate}"
        )
    if channels != CHANNELS:
        raise ValueError(
            f"channels must be {CHANNELS} (mono), got {channels}"
        )
    if len(chunk) % SAMPLE_WIDTH != 0:
        raise ValueError(
            f"PCM bytes length must be even (16-bit), got {len(chunk)}"
        )


def bytes_to_float32(chunk: bytes) -> np.ndarray:
    """16-bit signed PCM bytes → float32 ndarray, shape=(n_samples,).

    int16 / 32768.0 정규화 → [-1.0, 1.0] 범위.
    빈 bytes 는 shape=(0,) 배열 반환.
    """
    if len(chunk) % SAMPLE_WIDTH != 0:
        raise ValueError(
            f"PCM bytes length must be even (16-bit), got {len(chunk)}"
        )
    samples = np.frombuffer(chunk, dtype=np.int16)
    return (samples.astype(np.float32)) / INT16_MAX


__all__ = [
    "SAMPLE_RATE",
    "CHANNELS",
    "SAMPLE_WIDTH",
    "validate_pcm",
    "bytes_to_float32",
]
