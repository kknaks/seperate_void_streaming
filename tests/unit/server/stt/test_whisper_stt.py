"""Unit tests for WhisperSTT (spec-06 §6 unit 카테고리)."""

from __future__ import annotations

import asyncio
import struct
from unittest.mock import MagicMock, patch

import pytest

# WhisperSTT 는 faster_whisper 설치 없이도 단위 테스트 가능 — model 을 mock
_SAMPLE_RATE = 16000
_BYTES_PER_SAMPLE = 2


def _make_pcm(duration_s: float, amplitude: int = 100) -> bytes:
    """16-bit mono PCM, duration_s 초 분량."""
    n = int(duration_s * _SAMPLE_RATE)
    return struct.pack(f"<{n}h", *([amplitude] * n))


def _make_stt(mock_model: MagicMock) -> "WhisperSTT":
    """faster_whisper.WhisperModel 을 mock 으로 교체한 WhisperSTT 반환."""
    from server.stt.adapter import WhisperSTT

    stt = object.__new__(WhisperSTT)
    stt._model = mock_model
    stt._language = "ko"
    stt._beam_size = 5
    stt._buffer = bytearray()
    stt._lock = asyncio.Lock()
    return stt


# ---------------------------------------------------------------------------
# PCM 누적
# ---------------------------------------------------------------------------


async def test_feed_accumulates_buffer():
    """feed() N회 호출 시 내부 버퍼 길이 = 합산 bytes."""
    mock_model = MagicMock()
    stt = _make_stt(mock_model)

    chunk = _make_pcm(0.5)  # 0.5s = 16000 samples = 32000 bytes
    await stt.feed(chunk)
    await stt.feed(chunk)

    assert len(stt._buffer) == len(chunk) * 2


# ---------------------------------------------------------------------------
# byte_offset 슬라이스 계산
# ---------------------------------------------------------------------------


async def test_flush_window_byte_offset_correct():
    """flush_window(1.0, 2.0) → 1-2s 구간 PCM 만 ASR 에 공급."""
    mock_model = MagicMock()
    # transcribe 가 (segments, info) 반환
    mock_model.transcribe.return_value = (iter([]), MagicMock())
    stt = _make_stt(mock_model)

    # 3초 PCM: 각 초를 구분할 수 있도록 앞 1s=0, 1-2s=100, 2-3s=200
    chunk_0 = _make_pcm(1.0, amplitude=0)
    chunk_1 = _make_pcm(1.0, amplitude=100)
    chunk_2 = _make_pcm(1.0, amplitude=200)
    await stt.feed(chunk_0)
    await stt.feed(chunk_1)
    await stt.feed(chunk_2)

    await stt.flush_window(1.0, 2.0)

    assert mock_model.transcribe.called
    pcm_arg = mock_model.transcribe.call_args[0][0]
    # 1-2s 구간 = 16000 samples
    assert len(pcm_arg) == _SAMPLE_RATE


async def test_flush_window_t_end_exceeds_buffer():
    """t_end 가 누적 PCM 초과 시 가용분까지만 — 예외 없이 ASR 수행."""
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([]), MagicMock())
    stt = _make_stt(mock_model)

    await stt.feed(_make_pcm(1.0))  # 1초만 있음

    # t_end=3.0 지만 1초만 있음
    result = await stt.flush_window(0.0, 3.0)
    assert isinstance(result, str)
    pcm_arg = mock_model.transcribe.call_args[0][0]
    assert len(pcm_arg) == _SAMPLE_RATE  # 1s 만큼만


# ---------------------------------------------------------------------------
# 짧은 구간 → "" 반환, 모델 호출 0회
# ---------------------------------------------------------------------------


async def test_flush_window_short_duration_returns_empty():
    """t_end - t_start < 0.2s → "" 반환, transcribe 미호출 (spec-06 §3)."""
    mock_model = MagicMock()
    stt = _make_stt(mock_model)

    await stt.feed(_make_pcm(1.0))

    result = await stt.flush_window(0.0, 0.1)  # 0.1s < 0.2s

    assert result == ""
    mock_model.transcribe.assert_not_called()


async def test_flush_window_exactly_min_duration_calls_model():
    """t_end - t_start == 0.2s → 모델 호출해야 함 (경계값)."""
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([]), MagicMock())
    stt = _make_stt(mock_model)

    await stt.feed(_make_pcm(1.0))

    await stt.flush_window(0.0, 0.2)  # 정확히 0.2s

    mock_model.transcribe.assert_called_once()


# ---------------------------------------------------------------------------
# strip() 적용 확인
# ---------------------------------------------------------------------------


async def test_flush_window_strips_whitespace():
    """모델 결과에 strip() 적용 (spec-06 §3)."""
    seg = MagicMock()
    seg.text = "  안녕하세요  "
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([seg]), MagicMock())
    stt = _make_stt(mock_model)

    await stt.feed(_make_pcm(2.0))

    result = await stt.flush_window(0.0, 1.0)
    assert result == "안녕하세요"


async def test_flush_window_multiple_segments_concatenated():
    """여러 segment 의 text 를 이어붙이고 strip."""
    seg_a = MagicMock()
    seg_a.text = " 안녕 "
    seg_b = MagicMock()
    seg_b.text = "하세요"
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([seg_a, seg_b]), MagicMock())
    stt = _make_stt(mock_model)

    await stt.feed(_make_pcm(2.0))

    result = await stt.flush_window(0.0, 1.0)
    assert result == "안녕 하세요"


# ---------------------------------------------------------------------------
# 빈 버퍼 케이스
# ---------------------------------------------------------------------------


async def test_flush_window_no_pcm_returns_empty():
    """feed 없이 flush_window 호출 → "" 반환, 모델 미호출."""
    mock_model = MagicMock()
    stt = _make_stt(mock_model)

    result = await stt.flush_window(0.0, 1.0)

    assert result == ""
    mock_model.transcribe.assert_not_called()
