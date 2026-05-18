"""unit tests — speaker_engine.audio.format (F-03)."""

import struct

import numpy as np
import pytest

from speaker_engine.audio.format import (
    SAMPLE_RATE,
    bytes_to_float32,
    validate_pcm,
)

_RNG = np.random.default_rng(42)


def _pcm_bytes(n_samples: int = 1600) -> bytes:
    """n_samples 개의 16-bit PCM bytes (seeded sin wave)."""
    t = np.linspace(0, n_samples / SAMPLE_RATE, n_samples, endpoint=False)
    wave = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    return wave.tobytes()


# ── validate_pcm ─────────────────────────────────────────────────────────────


class TestValidatePcm:
    def test_valid_pcm_passes(self):
        validate_pcm(_pcm_bytes())

    def test_wrong_sample_rate_raises(self):
        with pytest.raises(ValueError, match="sample_rate"):
            validate_pcm(_pcm_bytes(), sample_rate=8000)

    def test_44100_sample_rate_raises(self):
        with pytest.raises(ValueError, match="sample_rate"):
            validate_pcm(_pcm_bytes(), sample_rate=44100)

    def test_stereo_raises(self):
        with pytest.raises(ValueError, match="channels"):
            validate_pcm(_pcm_bytes(), channels=2)

    def test_odd_bytes_length_raises(self):
        odd_bytes = b"\x00" * 3
        with pytest.raises(ValueError, match="even"):
            validate_pcm(odd_bytes)

    def test_empty_bytes_valid(self):
        validate_pcm(b"")

    def test_single_sample_valid(self):
        validate_pcm(struct.pack("<h", 1000))


# ── bytes_to_float32 ──────────────────────────────────────────────────────────


class TestBytesToFloat32:
    def test_returns_float32_ndarray(self):
        arr = bytes_to_float32(_pcm_bytes())
        assert arr.dtype == np.float32
        assert arr.ndim == 1

    def test_shape_matches_sample_count(self):
        arr = bytes_to_float32(_pcm_bytes(3200))
        assert arr.shape == (3200,)

    def test_int16_max_normalizes_to_approx_one(self):
        max_sample = struct.pack("<h", 32767)
        arr = bytes_to_float32(max_sample)
        assert arr[0] == pytest.approx(32767 / 32768.0, abs=1e-6)

    def test_int16_min_normalizes_negative(self):
        min_sample = struct.pack("<h", -32768)
        arr = bytes_to_float32(min_sample)
        assert arr[0] == pytest.approx(-1.0, abs=1e-6)

    def test_zero_sample_is_zero(self):
        zero_sample = struct.pack("<h", 0)
        arr = bytes_to_float32(zero_sample)
        assert arr[0] == pytest.approx(0.0)

    def test_empty_bytes_returns_empty_array(self):
        arr = bytes_to_float32(b"")
        assert arr.shape == (0,)

    def test_odd_bytes_raises(self):
        with pytest.raises(ValueError, match="even"):
            bytes_to_float32(b"\x00\x01\x02")

    def test_values_in_range(self):
        arr = bytes_to_float32(_pcm_bytes(16000))
        assert arr.min() >= -1.0
        assert arr.max() <= 1.0
