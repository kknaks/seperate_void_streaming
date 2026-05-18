"""unit tests — speaker_engine.audio.window (F-03, spec-03 §2-2)."""

import asyncio
import struct
from typing import Any
from unittest.mock import AsyncMock

import numpy as np
import pytest

from speaker_engine.audio.window import HOP_SIZE, WINDOW_SIZE, WaveformBuffer

_RNG = np.random.default_rng(0)


def _pcm_bytes(n_samples: int) -> bytes:
    """n_samples 개 16-bit PCM bytes (zeros — 검증 무관)."""
    return (np.zeros(n_samples, dtype=np.int16)).tobytes()


def _make_adapter(return_value: list[Any] | None = None) -> AsyncMock:
    """process_window 를 mock 하는 DiartAdapter stub."""
    adapter = AsyncMock()
    adapter.process_window = AsyncMock(return_value=return_value or [])
    return adapter


# ── feed ─────────────────────────────────────────────────────────────────────


class TestWaveformBufferFeed:
    async def test_under_window_size_no_process_call(self):
        adapter = _make_adapter()
        buf = WaveformBuffer(adapter)
        await buf.feed(_pcm_bytes(WINDOW_SIZE // 2))
        adapter.process_window.assert_not_called()

    async def test_exact_window_triggers_one_call(self):
        adapter = _make_adapter()
        buf = WaveformBuffer(adapter)
        await buf.feed(_pcm_bytes(WINDOW_SIZE))
        adapter.process_window.assert_called_once()
        called_wave = adapter.process_window.call_args[0][0]
        assert called_wave.shape == (WINDOW_SIZE,)
        assert called_wave.dtype == np.float32

    async def test_sliding_hop_triggers_second_call(self):
        adapter = _make_adapter()
        buf = WaveformBuffer(adapter)
        # 10s window 채우고
        await buf.feed(_pcm_bytes(WINDOW_SIZE))
        # 1s hop 추가 → 두 번째 window
        await buf.feed(_pcm_bytes(HOP_SIZE))
        assert adapter.process_window.call_count == 2

    async def test_multiple_windows_in_single_feed(self):
        adapter = _make_adapter()
        buf = WaveformBuffer(adapter)
        # WINDOW_SIZE + 2 × HOP_SIZE → 3개 window 기대
        total = WINDOW_SIZE + 2 * HOP_SIZE
        await buf.feed(_pcm_bytes(total))
        assert adapter.process_window.call_count == 3

    async def test_waveform_values_correct(self):
        """bytes_to_float32 변환 후 window 에 올바른 값이 들어가는지."""
        adapter = _make_adapter()
        buf = WaveformBuffer(adapter)
        samples = (np.ones(WINDOW_SIZE, dtype=np.int16) * 16384).tobytes()
        await buf.feed(samples)
        called_wave = adapter.process_window.call_args[0][0]
        expected = 16384 / 32768.0
        assert called_wave[0] == pytest.approx(expected, abs=1e-5)


# ── flush ─────────────────────────────────────────────────────────────────────


class TestWaveformBufferFlush:
    async def test_flush_empty_buffer_returns_empty(self):
        adapter = _make_adapter()
        buf = WaveformBuffer(adapter)
        result = await buf.flush()
        assert result == []
        adapter.process_window.assert_not_called()

    async def test_flush_partial_buffer_zero_pads(self):
        adapter = _make_adapter(return_value=["event"])
        buf = WaveformBuffer(adapter)
        await buf.feed(_pcm_bytes(WINDOW_SIZE // 2))
        result = await buf.flush()
        adapter.process_window.assert_called_once()
        called_wave = adapter.process_window.call_args[0][0]
        assert called_wave.shape == (WINDOW_SIZE,)
        # 패딩된 부분은 0
        assert called_wave[WINDOW_SIZE // 2 :].sum() == pytest.approx(0.0)
        assert result == ["event"]

    async def test_flush_returns_queued_plus_remainder(self):
        adapter = _make_adapter(return_value=["evt"])
        buf = WaveformBuffer(adapter)
        # window 1개 + 잔량 (큐 이벤트 + flush 이벤트)
        await buf.feed(_pcm_bytes(WINDOW_SIZE + HOP_SIZE // 2))
        result = await buf.flush()
        # process_window: 1 (feed) + 1 (flush) = 2
        assert adapter.process_window.call_count == 2
        assert result == ["evt", "evt"]

    async def test_flush_clears_buffer(self):
        adapter = _make_adapter()
        buf = WaveformBuffer(adapter)
        await buf.feed(_pcm_bytes(HOP_SIZE))
        await buf.flush()
        # 두 번 flush 해도 process_window 추가 호출 없음
        await buf.flush()
        assert adapter.process_window.call_count == 1


# ── backpressure (R1) ─────────────────────────────────────────────────────────


class TestBackpressure:
    async def test_queue_full_backpressure(self):
        """queue_maxsize=1 로 설정 후 2개 window feed 시 backpressure 검증."""
        slow_results: list[Any] = []

        async def slow_process(wave: np.ndarray) -> list[Any]:
            return ["event"]

        adapter = AsyncMock()
        adapter.process_window = AsyncMock(side_effect=slow_process)

        buf = WaveformBuffer(adapter, queue_maxsize=1)

        # 첫 window → 큐에 들어감 (maxsize=1, 아직 공간 있음)
        await buf.feed(_pcm_bytes(WINDOW_SIZE))
        # 두 번째 window → 큐 full, 하지만 await 으로 처리됨 (소비 없이 대기)
        # asyncio.wait_for 로 타임아웃 걸어 deadlock 방지
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(buf.feed(_pcm_bytes(HOP_SIZE)), timeout=0.05)
