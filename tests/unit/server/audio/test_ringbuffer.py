"""PcmRingBuffer 단위 테스트 (PLAN-006-T-004).

검증 대상:
  - append / slice 기본 동작
  - 시간축 연속성 (다중 append 후 slice 정합)
  - max_duration 초과 시 oldest 폐기 + t_offset 갱신
"""

from __future__ import annotations

import struct

import pytest

from server.audio.ringbuffer import PcmRingBuffer, _BYTES_PER_SECOND

_SR = 16_000
_BPS = 2  # bytes per sample


def _pcm(n_samples: int, value: int = 1000) -> bytes:
    """n_samples 개의 16-bit PCM 생성."""
    return struct.pack(f"<{n_samples}h", *([value] * n_samples))


def _secs(s: float) -> int:
    """초 → bytes 수."""
    return int(s * _BYTES_PER_SECOND)


class TestAppendSlice:
    def test_append_and_slice_full(self):
        """0.5초 append 후 0.0~0.5 slice 는 원본과 동일."""
        buf = PcmRingBuffer()
        pcm = _pcm(8_000, 100)  # 0.5초
        buf.append(pcm)
        assert buf.slice(0.0, 0.5) == pcm

    def test_slice_partial_range(self):
        """1초 × 2 append 후 두 번째 1초 구간 slice."""
        buf = PcmRingBuffer()
        s1 = _pcm(_SR, 111)  # 1초, value=111
        s2 = _pcm(_SR, 222)  # 1초, value=222
        buf.append(s1)
        buf.append(s2)
        sliced = buf.slice(1.0, 2.0)
        assert len(sliced) == _secs(1.0)
        assert sliced == s2

    def test_slice_out_of_range_returns_empty(self):
        """누적 범위 바깥 slice → b\"\"."""
        buf = PcmRingBuffer()
        buf.append(_pcm(_SR))  # 1초
        assert buf.slice(2.0, 3.0) == b""

    def test_slice_t_start_equals_t_end_returns_empty(self):
        """t_start == t_end → b\"\"."""
        buf = PcmRingBuffer()
        buf.append(_pcm(_SR))
        assert buf.slice(0.5, 0.5) == b""

    def test_empty_buffer_slice_returns_empty(self):
        """비어있는 버퍼 slice → b\"\"."""
        buf = PcmRingBuffer()
        assert buf.slice(0.0, 1.0) == b""

    def test_duration_tracking(self):
        """append 후 duration_s 정합 검증."""
        buf = PcmRingBuffer()
        buf.append(_pcm(_SR))  # 1초
        assert abs(buf.duration_s() - 1.0) < 1e-6


class TestTimeAxis:
    def test_consecutive_appends_time_axis(self):
        """0.5초 × 3 append → 각 구간 slice 정합."""
        buf = PcmRingBuffer()
        a = _pcm(8_000, 10)   # 0~0.5초
        b = _pcm(8_000, 20)   # 0.5~1.0초
        c = _pcm(8_000, 30)   # 1.0~1.5초
        buf.append(a)
        buf.append(b)
        buf.append(c)
        assert buf.slice(0.0, 0.5) == a
        assert buf.slice(0.5, 1.0) == b
        assert buf.slice(1.0, 1.5) == c

    def test_cross_boundary_slice(self):
        """두 append 경계를 넘는 slice 는 연결된 bytes 반환."""
        buf = PcmRingBuffer()
        a = _pcm(8_000, 10)  # 0~0.5초
        b = _pcm(8_000, 20)  # 0.5~1.0초
        buf.append(a)
        buf.append(b)
        sliced = buf.slice(0.0, 1.0)
        assert sliced == a + b


class TestMaxDuration:
    def test_overflow_drops_oldest(self):
        """max_duration 초과 시 oldest 폐기, 최근 데이터 유지."""
        buf = PcmRingBuffer(max_duration_s=0.5)
        pcm_old = _pcm(8_000, 100)  # 0.5초
        pcm_new = _pcm(8_000, 200)  # 0.5초 (합계 1.0초 → 한도 초과)
        buf.append(pcm_old)
        buf.append(pcm_new)
        assert abs(buf.duration_s() - 0.5) < 0.01
        # 남은 데이터는 pcm_new (t_offset=0.5 이후)
        sliced = buf.slice(buf._t_offset, buf._t_offset + 0.5)
        assert sliced == pcm_new

    def test_t_offset_updated_on_overflow(self):
        """overflow 발생 시 _t_offset 이 폐기된 시간만큼 증가."""
        buf = PcmRingBuffer(max_duration_s=0.5)
        buf.append(_pcm(8_000, 1))  # 0.5초 (한도 채움)
        buf.append(_pcm(8_000, 2))  # 0.5초 추가 → 0.5초 폐기
        assert abs(buf._t_offset - 0.5) < 1e-6

    def test_slice_after_overflow_uses_correct_offset(self):
        """overflow 후 slice 는 갱신된 t_offset 기준으로 동작."""
        buf = PcmRingBuffer(max_duration_s=1.0)
        buf.append(_pcm(_SR, 1))    # 0~1초 (1초)
        buf.append(_pcm(8_000, 2))  # 1~1.5초 (합계 1.5초 → 0.5초 폐기)
        # t_offset ≈ 0.5, 버퍼에는 0.5~1.5초 구간
        sliced = buf.slice(1.0, 1.5)
        assert len(sliced) == _secs(0.5)
