"""unit tests — speaker_engine.sources.multichannel (H-04, spec-05 §2-2 unit 카테고리).

pyroomacoustics 는 sys.modules mock 으로 완전 격리 — 실 라이브러리 접근 0.
"""

from __future__ import annotations

import sys
import types
from typing import AsyncIterator
from unittest.mock import patch

import numpy as np
import pytest

from speaker_engine.sources.multichannel import (
    _ds_weights,
    _mvdr_weights,
    from_beamforming,
    from_multichannel_mixdown,
)
from speaker_engine.types import BeamformingConfig, MicrophoneGeometry


# ── helpers ───────────────────────────────────────────────────────────────────


async def _stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def _collect(gen: AsyncIterator[bytes]) -> list[bytes]:
    result = []
    async for chunk in gen:
        result.append(chunk)
    return result


def _multichannel_bytes(frames: np.ndarray) -> bytes:
    """(n_samples, channels) int16 ndarray → interleaved bytes."""
    assert frames.dtype == np.int16
    return frames.tobytes()


def _fake_pra() -> types.ModuleType:
    """pyroomacoustics 모듈 대역 (import 성공, 실 API 없음)."""
    mod = types.ModuleType("pyroomacoustics")
    return mod


def _geometry(channels: int = 2, spacing: float = 0.05) -> MicrophoneGeometry:
    """x 축으로 spacing 간격의 직선 어레이 (test fixture)."""
    positions = np.zeros((channels, 3))
    positions[:, 0] = np.arange(channels) * spacing
    return MicrophoneGeometry(positions=positions)


# ── from_multichannel_mixdown — mean ─────────────────────────────────────────


class TestMixdownMean:
    async def test_2ch_identical_signal_mean(self):
        """2 채널 동일 신호 → mean = 동일 신호."""
        data = np.array([[100, 100], [200, 200], [-300, -300]], dtype=np.int16)
        chunks = [_multichannel_bytes(data)]
        result = b"".join(await _collect(from_multichannel_mixdown(_stream(chunks), 2)))
        output = np.frombuffer(result, dtype=np.int16)
        np.testing.assert_array_equal(output, np.array([100, 200, -300], dtype=np.int16))

    async def test_2ch_opposite_phase_mean_is_zero(self):
        """2 채널 반대 위상 → mean = 0."""
        vals = [500, -1000, 32767]
        data = np.array([[v, -v] for v in vals], dtype=np.int16)
        chunks = [_multichannel_bytes(data)]
        result = b"".join(await _collect(from_multichannel_mixdown(_stream(chunks), 2)))
        output = np.frombuffer(result, dtype=np.int16)
        np.testing.assert_array_equal(output, np.zeros(len(vals), dtype=np.int16))

    async def test_4ch_mean(self):
        """4 채널 mean = 채널 평균."""
        # 4 채널: [100, 200, 300, 400] → mean = 250
        data = np.array([[100, 200, 300, 400]], dtype=np.int16)
        chunks = [_multichannel_bytes(data)]
        result = b"".join(await _collect(from_multichannel_mixdown(_stream(chunks), 4)))
        output = np.frombuffer(result, dtype=np.int16)
        assert output[0] == 250

    async def test_mean_is_default_method(self):
        """method 생략 시 mean."""
        data = np.array([[100, 200]], dtype=np.int16)
        chunks = [_multichannel_bytes(data)]
        result_default = b"".join(
            await _collect(from_multichannel_mixdown(_stream(chunks), 2))
        )
        chunks2 = [_multichannel_bytes(data)]
        result_explicit = b"".join(
            await _collect(from_multichannel_mixdown(_stream(chunks2), 2, method="mean"))
        )
        assert result_default == result_explicit


# ── from_multichannel_mixdown — sum / clipping ───────────────────────────────


class TestMixdownSum:
    async def test_sum_simple(self):
        """method="sum" — 합산 결과 검증."""
        data = np.array([[100, 200]], dtype=np.int16)
        chunks = [_multichannel_bytes(data)]
        result = b"".join(
            await _collect(from_multichannel_mixdown(_stream(chunks), 2, method="sum"))
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert output[0] == 300

    async def test_sum_clipping_at_int16_max(self):
        """sum 이 int16 max 초과 시 32767 saturation."""
        data = np.array([[32767, 1]], dtype=np.int16)
        chunks = [_multichannel_bytes(data)]
        result = b"".join(
            await _collect(from_multichannel_mixdown(_stream(chunks), 2, method="sum"))
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert output[0] == np.iinfo(np.int16).max

    async def test_sum_clipping_at_int16_min(self):
        """sum 이 int16 min 미만 시 -32768 saturation."""
        data = np.array([[-32768, -1]], dtype=np.int16)
        chunks = [_multichannel_bytes(data)]
        result = b"".join(
            await _collect(from_multichannel_mixdown(_stream(chunks), 2, method="sum"))
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert output[0] == np.iinfo(np.int16).min


# ── from_multichannel_mixdown — ValueError ───────────────────────────────────


class TestMixdownValueError:
    async def test_channels_1_raises(self):
        """channels=1 → ValueError (최소 2 채널)."""
        with pytest.raises(ValueError, match="채널"):
            async for _ in from_multichannel_mixdown(_stream([b"\x00\x00"]), 1):
                pass

    async def test_channels_0_raises(self):
        """channels=0 → ValueError."""
        with pytest.raises(ValueError):
            async for _ in from_multichannel_mixdown(_stream([b""]), 0):
                pass

    async def test_invalid_method_raises(self):
        """method='invalid' → ValueError."""
        with pytest.raises(ValueError, match="method"):
            async for _ in from_multichannel_mixdown(_stream([b""]), 2, method="invalid"):
                pass

    async def test_invalid_method_rms(self):
        """method='rms' → ValueError."""
        with pytest.raises(ValueError):
            async for _ in from_multichannel_mixdown(_stream([b""]), 2, method="rms"):
                pass


# ── from_multichannel_mixdown — rolling buffer ───────────────────────────────


class TestMixdownRollingBuffer:
    async def test_unaligned_chunk_rolling_buffer(self):
        """chunk boundary 가 frame_bytes 배수 아님 → rolling buffer 동작."""
        channels = 2
        # 2 프레임: [[100, 200], [300, 400]] → 8 bytes
        data = np.array([[100, 200], [300, 400]], dtype=np.int16)
        full_bytes = _multichannel_bytes(data)
        assert len(full_bytes) == 8

        # 3 + 5 로 분할 → 첫 chunk 는 frame_bytes=4 미만 (aligned=0)
        chunk1 = full_bytes[:3]
        chunk2 = full_bytes[3:]

        result = b"".join(
            await _collect(from_multichannel_mixdown(_stream([chunk1, chunk2]), channels))
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert output[0] == 150   # mean(100, 200)
        assert output[1] == 350   # mean(300, 400)

    async def test_single_byte_chunks(self):
        """1바이트씩 입력 → 4바이트 모일 때 yield."""
        channels = 2
        data = np.array([[1000, 2000]], dtype=np.int16)  # 4 bytes
        full_bytes = _multichannel_bytes(data)
        chunks = [bytes([b]) for b in full_bytes]  # 1 byte each

        result = b"".join(
            await _collect(from_multichannel_mixdown(_stream(chunks), channels))
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert output[0] == 1500  # mean(1000, 2000)

    async def test_aligned_chunk_normal_yield(self):
        """channels*2 의 정확한 배수 → 정상 yield (buf 잔여 없음)."""
        channels = 2
        data = np.array([[100, 200], [300, 400], [500, 600]], dtype=np.int16)  # 3 frames, 12 bytes
        chunks = [_multichannel_bytes(data)]

        result = b"".join(
            await _collect(from_multichannel_mixdown(_stream(chunks), channels))
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert len(output) == 3
        assert output[0] == 150
        assert output[1] == 350
        assert output[2] == 550

    async def test_empty_input_empty_generator(self):
        """빈 input → 빈 generator."""
        result = await _collect(from_multichannel_mixdown(_stream([]), 2))
        assert result == []

    async def test_empty_bytes_chunk_skipped(self):
        """b'' chunk → skip."""
        channels = 2
        data = np.array([[100, 200]], dtype=np.int16)
        chunks = [b"", _multichannel_bytes(data), b""]

        result = b"".join(
            await _collect(from_multichannel_mixdown(_stream(chunks), channels))
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert len(output) == 1
        assert output[0] == 150


# ── from_beamforming — ImportError ───────────────────────────────────────────


class TestBeamformingImportError:
    async def test_missing_pra_raises_import_error(self):
        """pyroomacoustics 미설치 → ImportError (extras 안내 메시지)."""
        geometry = _geometry()
        with patch.dict(sys.modules, {"pyroomacoustics": None}):
            with pytest.raises(ImportError, match="speaker_engine\\[beamforming\\]"):
                async for _ in from_beamforming(_stream([b""]), 2, geometry):
                    pass

    async def test_import_error_message_has_pip_install(self):
        """ImportError 메시지에 'pip install' 포함."""
        geometry = _geometry()
        with patch.dict(sys.modules, {"pyroomacoustics": None}):
            with pytest.raises(ImportError) as exc_info:
                async for _ in from_beamforming(_stream([b""]), 2, geometry):
                    pass
        assert "pip install" in str(exc_info.value)

    def test_module_importable_without_pra(self):
        """pyroomacoustics 없이도 multichannel 모듈 import 가능 (lazy import)."""
        import speaker_engine.sources.multichannel as mc

        assert hasattr(mc, "from_beamforming")
        assert callable(mc.from_beamforming)


# ── from_beamforming — ValueError ────────────────────────────────────────────


class TestBeamformingValueError:
    async def test_channels_1_raises(self):
        """channels=1 → ValueError."""
        geometry = _geometry(1)
        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            with pytest.raises(ValueError, match="채널"):
                async for _ in from_beamforming(_stream([b""]), 1, geometry):
                    pass

    async def test_geometry_mismatch_raises(self):
        """channels=3 but geometry.positions.shape[0]=2 → ValueError."""
        geometry = _geometry(2)
        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            with pytest.raises(ValueError, match="불일치"):
                async for _ in from_beamforming(_stream([b""]), 3, geometry):
                    pass

    async def test_invalid_method_raises(self):
        """method='rms' → ValueError."""
        geometry = _geometry()
        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            with pytest.raises(ValueError, match="method"):
                async for _ in from_beamforming(_stream([b""]), 2, geometry, method="rms"):
                    pass

    async def test_method_empty_string_raises(self):
        """method='' → ValueError."""
        geometry = _geometry()
        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            with pytest.raises(ValueError):
                async for _ in from_beamforming(_stream([b""]), 2, geometry, method=""):
                    pass


# ── from_beamforming — output ────────────────────────────────────────────────


class TestBeamformingOutput:
    def _make_block(self, n_fft: int = 512, channels: int = 2) -> bytes:
        """n_fft 프레임짜리 multichannel int16 합성 bytes."""
        rng = np.random.default_rng(42)
        data = rng.integers(-1000, 1000, (n_fft, channels), dtype=np.int16)
        return data.tobytes()

    async def test_yields_mono_bytes_with_mock_pra(self):
        """mock pyroomacoustics → multichannel input → mono bytes yield."""
        channels = 2
        n_fft = 512
        geometry = _geometry(channels)
        block = self._make_block(n_fft, channels)

        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            results = await _collect(
                from_beamforming(_stream([block]), channels, geometry, method="ds")
            )

        assert len(results) == 1
        assert isinstance(results[0], bytes)
        assert len(results[0]) == n_fft * 2  # n_fft int16 samples

    async def test_output_is_mono_int16_per_block(self):
        """출력 bytes 는 n_fft × 2 bytes (int16 mono 1 block)."""
        channels = 2
        n_fft = 512
        geometry = _geometry(channels)
        # 2 blocks worth of data
        block = self._make_block(n_fft, channels) * 2

        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            results = await _collect(
                from_beamforming(_stream([block]), channels, geometry)
            )

        assert len(results) == 2
        for r in results:
            assert len(r) == n_fft * 2

    async def test_empty_input_yields_nothing(self):
        """빈 input → 빈 generator."""
        geometry = _geometry()
        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            results = await _collect(
                from_beamforming(_stream([]), 2, geometry)
            )
        assert results == []

    async def test_short_input_less_than_block_yields_nothing(self):
        """block_bytes 미만 입력 → yield 없음."""
        channels = 2
        n_fft = 512
        geometry = _geometry(channels)
        short = b"\x00" * (n_fft * channels * 2 - 4)  # one int16 short

        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            results = await _collect(
                from_beamforming(_stream([short]), channels, geometry)
            )
        assert results == []


# ── from_beamforming — config / method priority ───────────────────────────────


class TestBeamformingConfig:
    async def test_config_none_uses_default(self):
        """config=None → BeamformingConfig() default (n_fft=512, sample_rate=16000) 사용."""
        channels = 2
        n_fft = 512  # BeamformingConfig default
        geometry = _geometry(channels)
        block = np.zeros((n_fft, channels), dtype=np.int16).tobytes()

        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            results = await _collect(
                from_beamforming(_stream([block]), channels, geometry, config=None)
            )

        assert len(results) == 1
        assert len(results[0]) == n_fft * 2

    async def test_explicit_config_n_fft_respected(self):
        """config.n_fft=256 → 출력 블록 = 256 × 2 bytes."""
        channels = 2
        n_fft = 256
        cfg = BeamformingConfig(n_fft=n_fft)
        geometry = _geometry(channels)
        block = np.zeros((n_fft, channels), dtype=np.int16).tobytes()

        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            results = await _collect(
                from_beamforming(_stream([block]), channels, geometry, config=cfg)
            )

        assert len(results) == 1
        assert len(results[0]) == n_fft * 2

    async def test_method_arg_overrides_config_method(self):
        """method='ds' + config.method='mvdr' → _ds_weights 호출 (method 인자 우선)."""
        channels = 2
        n_fft = 512
        geometry = _geometry(channels)
        block = np.zeros((n_fft, channels), dtype=np.int16).tobytes()
        cfg = BeamformingConfig(method="mvdr")

        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            with patch(
                "speaker_engine.sources.multichannel._ds_weights", wraps=_ds_weights
            ) as mock_ds, patch(
                "speaker_engine.sources.multichannel._mvdr_weights", wraps=_mvdr_weights
            ) as mock_mvdr:
                await _collect(
                    from_beamforming(
                        _stream([block]), channels, geometry, method="ds", config=cfg
                    )
                )

        mock_ds.assert_called_once()
        mock_mvdr.assert_not_called()

    async def test_method_mvdr_uses_mvdr_weights(self):
        """method='mvdr' → _mvdr_weights 호출."""
        channels = 2
        n_fft = 512
        geometry = _geometry(channels)
        block = np.zeros((n_fft, channels), dtype=np.int16).tobytes()

        with patch.dict(sys.modules, {"pyroomacoustics": _fake_pra()}):
            with patch(
                "speaker_engine.sources.multichannel._mvdr_weights", wraps=_mvdr_weights
            ) as mock_mvdr:
                await _collect(
                    from_beamforming(_stream([block]), channels, geometry, method="mvdr")
                )

        mock_mvdr.assert_called_once()


# ── re-export 검증 ────────────────────────────────────────────────────────────


class TestReexport:
    def test_sources_package_exports_from_multichannel_mixdown(self):
        """sources 패키지에서 from_multichannel_mixdown re-export."""
        from speaker_engine.sources import from_multichannel_mixdown as f

        assert callable(f)

    def test_sources_package_exports_from_beamforming(self):
        """sources 패키지에서 from_beamforming re-export."""
        from speaker_engine.sources import from_beamforming as f

        assert callable(f)

    def test_top_level_exports_from_multichannel_mixdown(self):
        """speaker_engine 최상위에서 from_multichannel_mixdown re-export."""
        from speaker_engine import from_multichannel_mixdown as f

        assert callable(f)

    def test_top_level_exports_from_beamforming(self):
        """speaker_engine 최상위에서 from_beamforming re-export."""
        from speaker_engine import from_beamforming as f

        assert callable(f)

    def test_sources_all_includes_both(self):
        """sources.__all__ 에 두 함수 포함."""
        import speaker_engine.sources as src

        assert "from_multichannel_mixdown" in src.__all__
        assert "from_beamforming" in src.__all__

    def test_multichannel_module_all(self):
        """multichannel 모듈 __all__ 에 두 함수 포함."""
        import speaker_engine.sources.multichannel as mc

        assert "from_multichannel_mixdown" in mc.__all__
        assert "from_beamforming" in mc.__all__
