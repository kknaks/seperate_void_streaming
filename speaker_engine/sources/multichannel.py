"""multichannel — mixdown + beamforming 헬퍼 (H-04, spec-01 §2-3, adr-07)."""

from __future__ import annotations

import logging
from typing import AsyncIterator

import numpy as np

from speaker_engine.types import BeamformingConfig, MicrophoneGeometry

_log = logging.getLogger(__name__)

_SPEED_OF_SOUND: float = 343.0  # m/s


# ── from_multichannel_mixdown ─────────────────────────────────────────────────


async def from_multichannel_mixdown(
    stream: AsyncIterator[bytes],
    channels: int,
    method: str = "mean",
) -> AsyncIterator[bytes]:
    """멀티채널 인터리브드 PCM raw 스트림을 mono 16kHz PCM 으로 변환.

    Parameters
    ----------
    stream   : multi-channel raw PCM bytes (channels 채널 인터리브드, 16kHz, 16-bit signed)
    channels : 입력 채널 수 (≥ 2)
    method   : "mean" (채널 평균, default) | "sum" (채널 합산, clipping)

    Yields
    ------
    bytes — mono 16kHz 16-bit signed PCM

    Notes
    -----
    chunk boundary 가 channels * 2 배수가 아니면 rolling buffer 로 흡수.
    """
    if channels < 2:
        raise ValueError(f"최소 2 채널 필요, got channels={channels}")
    if method not in ("mean", "sum"):
        raise ValueError(f"method must be 'mean' or 'sum', got {method!r}")

    frame_bytes = channels * 2  # bytes per interleaved sample
    buf = bytearray()

    async for chunk in stream:
        if not chunk:
            continue
        buf.extend(chunk)

        aligned = (len(buf) // frame_bytes) * frame_bytes
        if aligned == 0:
            continue

        data = bytes(buf[:aligned])
        buf = buf[aligned:]

        arr = np.frombuffer(data, dtype=np.int16).reshape(-1, channels)

        if method == "mean":
            mono = np.mean(arr, axis=1).astype(np.int16)
        else:  # sum
            summed = np.sum(arr.astype(np.int32), axis=1)
            mono = np.clip(
                summed, np.iinfo(np.int16).min, np.iinfo(np.int16).max
            ).astype(np.int16)

        yield mono.tobytes()


# ── beamforming weight helpers ────────────────────────────────────────────────


def _steering_vector(
    positions: np.ndarray,
    reference_channel: int,
    n_fft: int,
    sample_rate: int,
) -> np.ndarray:
    """Far-field steering vector relative to reference_channel.

    Returns (n_freq, channels) complex128.
    """
    ref_pos = positions[reference_channel]
    delays = np.linalg.norm(positions - ref_pos, axis=1) / _SPEED_OF_SOUND  # (ch,) sec
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)  # (n_freq,)
    # Phase compensation: e^(-j * 2π * f * τ)
    return np.exp(
        -1j * 2.0 * np.pi * freqs[:, np.newaxis] * delays[np.newaxis, :]
    )  # (n_freq, channels)


def _ds_weights(
    positions: np.ndarray,
    reference_channel: int,
    n_fft: int,
    sample_rate: int,
) -> np.ndarray:
    """Delay-and-Sum weights (normalized by channel count).

    Returns (n_freq, channels) complex128.
    """
    d = _steering_vector(positions, reference_channel, n_fft, sample_rate)
    return d / positions.shape[0]


def _mvdr_weights(
    positions: np.ndarray,
    reference_channel: int,
    n_fft: int,
    sample_rate: int,
) -> np.ndarray:
    """MVDR weights under white-noise (diagonal covariance) assumption.

    With unit-magnitude steering vectors, this reduces to DS with steering
    normalization: w = d / (d^H d). Under white-noise assumption and unit-
    magnitude steering, d^H d = M (channel count), giving the same result as
    DS numerically. Both paths are kept for explicit intent and future extension
    to data-dependent covariance estimation.

    Returns (n_freq, channels) complex128.
    """
    d = _steering_vector(positions, reference_channel, n_fft, sample_rate)
    dHd = np.sum(np.abs(d) ** 2, axis=1, keepdims=True)  # (n_freq, 1)
    return d / np.maximum(dHd, 1e-10)


# ── from_beamforming ──────────────────────────────────────────────────────────


async def from_beamforming(
    stream: AsyncIterator[bytes],
    channels: int,
    geometry: MicrophoneGeometry,
    method: str = "mvdr",
    config: BeamformingConfig | None = None,
) -> AsyncIterator[bytes]:
    """멀티채널 인터리브드 PCM raw 스트림에 beamforming 적용 후 mono 출력.

    Parameters
    ----------
    stream   : multi-channel raw PCM bytes (channels 채널 인터리브드, 16kHz, 16-bit signed)
    channels : 입력 채널 수 (≥ 2)
    geometry : 마이크 물리 배치 (MicrophoneGeometry)
    method   : "mvdr" (default) | "ds" — config.method 보다 우선
    config   : BeamformingConfig (None → default 사용)

    Yields
    ------
    bytes — mono 16kHz 16-bit signed PCM

    Raises
    ------
    ImportError  : extras [beamforming] (pyroomacoustics) 미설치 시
    ValueError   : channels < 2, method 불허, channels != geometry shape 불일치 시
    """
    try:
        import pyroomacoustics  # noqa: F401 — gating extras availability
    except ImportError as exc:
        raise ImportError(
            "from_beamforming() 사용에 pyroomacoustics 가 필요합니다. "
            "설치: pip install 'speaker_engine[beamforming]'"
        ) from exc

    if channels < 2:
        raise ValueError(f"최소 2 채널 필요, got channels={channels}")
    if method not in ("mvdr", "ds"):
        raise ValueError(f"method must be 'mvdr' or 'ds', got {method!r}")
    if channels != geometry.positions.shape[0]:
        raise ValueError(
            f"channels={channels} 과 "
            f"geometry.positions.shape[0]={geometry.positions.shape[0]} 불일치"
        )

    cfg = config or BeamformingConfig()
    effective_method = method  # method arg takes precedence over config.method
    n_fft = cfg.n_fft
    sample_rate = cfg.sample_rate

    positions = geometry.positions  # (channels, 3)

    if effective_method == "ds":
        weights = _ds_weights(positions, geometry.reference_channel, n_fft, sample_rate)
    else:  # mvdr
        weights = _mvdr_weights(positions, geometry.reference_channel, n_fft, sample_rate)

    # Frequency-domain beamforming (rectangular window — no amplitude gaps at block boundaries)
    frame_bytes = channels * 2
    block_bytes = n_fft * frame_bytes
    buf = bytearray()

    async for chunk in stream:
        if not chunk:
            continue
        buf.extend(chunk)

        while len(buf) >= block_bytes:
            block = bytes(buf[:block_bytes])
            buf = buf[block_bytes:]

            arr = (
                np.frombuffer(block, dtype=np.int16)
                .reshape(n_fft, channels)
                .astype(np.float64)
                / 32768.0
            )

            X = np.fft.rfft(arr, axis=0)        # (n_freq, channels)
            Y = np.sum(X * weights, axis=1)      # (n_freq,)
            y = np.fft.irfft(Y, n=n_fft)         # (n_fft,)

            out = np.clip(y * 32768, -32768, 32767).astype(np.int16)
            yield out.tobytes()


__all__ = ["from_multichannel_mixdown", "from_beamforming"]
