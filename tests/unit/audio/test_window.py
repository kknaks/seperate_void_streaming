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
        ev = _FakeEvent(t_start=0.0, t_end=1.0)
        adapter = _make_adapter(return_value=[ev])
        buf = WaveformBuffer(adapter)
        await buf.feed(_pcm_bytes(WINDOW_SIZE // 2))
        result = await buf.flush()
        adapter.process_window.assert_called_once()
        called_wave = adapter.process_window.call_args[0][0]
        assert called_wave.shape == (WINDOW_SIZE,)
        # 패딩된 부분은 0
        assert called_wave[WINDOW_SIZE // 2 :].sum() == pytest.approx(0.0)
        assert len(result) == 1

    async def test_flush_returns_queued_plus_remainder(self):
        ev1 = _FakeEvent(t_start=0.0, t_end=1.0)
        ev2 = _FakeEvent(t_start=0.0, t_end=1.0)
        adapter = AsyncMock()
        adapter.process_window = AsyncMock(side_effect=[[ev1], [ev2]])
        buf = WaveformBuffer(adapter)
        # window 1개 + 잔량 (큐 이벤트 + flush 이벤트)
        await buf.feed(_pcm_bytes(WINDOW_SIZE + HOP_SIZE // 2))
        result = await buf.flush()
        # process_window: 1 (feed) + 1 (flush) = 2
        assert adapter.process_window.call_count == 2
        assert len(result) == 2

    async def test_flush_clears_buffer(self):
        adapter = _make_adapter()
        buf = WaveformBuffer(adapter)
        await buf.feed(_pcm_bytes(HOP_SIZE))
        await buf.flush()
        # 두 번 flush 해도 process_window 추가 호출 없음
        await buf.flush()
        assert adapter.process_window.call_count == 1


# ── Bug B: session-relative t_start (Bug B fix) ──────────────────────────────


class _FakeEvent:
    """t_start / t_end 만 있는 최소 이벤트 객체 (RawSpeakerEvent 대리)."""

    def __init__(self, t_start: float, t_end: float) -> None:
        self.t_start = t_start
        self.t_end = t_end


class TestSessionRelativeTimes:
    async def test_first_window_offset_zero(self):
        """첫 window (offset=0) — 이벤트 t_start/t_end 변화 없음."""
        ev = _FakeEvent(t_start=2.5, t_end=5.0)
        adapter = AsyncMock()
        adapter.process_window = AsyncMock(return_value=[ev])

        buf = WaveformBuffer(adapter)
        await buf.feed(_pcm_bytes(WINDOW_SIZE))
        results = buf.drain_queue()

        assert len(results) == 1
        assert results[0].t_start == pytest.approx(2.5)
        assert results[0].t_end == pytest.approx(5.0)

    async def test_second_window_offset_one_second(self):
        """두 번째 window (HOP=1s) — t_start 에 1초 추가."""
        ev1 = _FakeEvent(t_start=2.5, t_end=5.0)
        ev2 = _FakeEvent(t_start=2.5, t_end=5.0)
        adapter = AsyncMock()
        adapter.process_window = AsyncMock(side_effect=[[ev1], [ev2]])

        buf = WaveformBuffer(adapter)
        await buf.feed(_pcm_bytes(WINDOW_SIZE))   # window 1
        await buf.feed(_pcm_bytes(HOP_SIZE))       # window 2
        results = buf.drain_queue()

        assert len(results) == 2
        assert results[0].t_start == pytest.approx(2.5)    # offset 0
        assert results[1].t_start == pytest.approx(2.5 + HOP_SIZE / 16_000)  # offset 1s

    async def test_third_window_offset_two_seconds(self):
        """세 번째 window — t_start 에 2초 추가 (누적 검증)."""
        events = [_FakeEvent(t_start=1.0, t_end=2.0) for _ in range(3)]
        adapter = AsyncMock()
        adapter.process_window = AsyncMock(side_effect=[[events[0]], [events[1]], [events[2]]])

        buf = WaveformBuffer(adapter)
        await buf.feed(_pcm_bytes(WINDOW_SIZE + 2 * HOP_SIZE))
        results = buf.drain_queue()

        hop_s = HOP_SIZE / 16_000  # 1.0s
        assert results[0].t_start == pytest.approx(1.0 + 0 * hop_s)
        assert results[1].t_start == pytest.approx(1.0 + 1 * hop_s)
        assert results[2].t_start == pytest.approx(1.0 + 2 * hop_s)

    async def test_flush_window_offset_correct(self):
        """flush() 이벤트도 session-relative 오프셋 적용."""
        # 첫 window 처리 후 잔량 flush → flush window offset = 1s
        ev_feed = _FakeEvent(t_start=0.0, t_end=1.0)
        ev_flush = _FakeEvent(t_start=0.5, t_end=2.0)
        adapter = AsyncMock()
        adapter.process_window = AsyncMock(side_effect=[[ev_feed], [ev_flush]])

        buf = WaveformBuffer(adapter)
        await buf.feed(_pcm_bytes(WINDOW_SIZE + HOP_SIZE // 2))  # window 1 + 잔량
        result = await buf.flush()

        hop_s = HOP_SIZE / 16_000
        assert ev_flush.t_start == pytest.approx(0.5 + hop_s)  # flush offset = 1s


# ── backpressure (R1) ─────────────────────────────────────────────────────────


class TestBackpressure:
    async def test_queue_full_backpressure(self):
        """queue_maxsize=1 로 설정 후 2개 window feed 시 backpressure 검증."""

        async def slow_process(wave: np.ndarray) -> list[Any]:
            return [_FakeEvent(t_start=0.0, t_end=1.0)]

        adapter = AsyncMock()
        adapter.process_window = AsyncMock(side_effect=slow_process)

        buf = WaveformBuffer(adapter, queue_maxsize=1)

        # 첫 window → 큐에 들어감 (maxsize=1, 아직 공간 있음)
        await buf.feed(_pcm_bytes(WINDOW_SIZE))
        # 두 번째 window → 큐 full, 하지만 await 으로 처리됨 (소비 없이 대기)
        # asyncio.wait_for 로 타임아웃 걸어 deadlock 방지
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(buf.feed(_pcm_bytes(HOP_SIZE)), timeout=0.05)
