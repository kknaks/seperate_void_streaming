"""WhisperSTT 통합 테스트 — 실 faster-whisper medium + 한국어 sample (spec-06 §6).

실행 조건:
    pip install faster-whisper
    pytest tests/integration/test_stt_korean.py -m integration -v

faster-whisper 미설치 또는 모델 다운로드 실패 시 자동 skip.
"""

from __future__ import annotations

import math
import struct

import numpy as np
import pytest

_SAMPLE_RATE = 16000


def _sin_pcm(duration_s: float = 2.0, freq: float = 440.0) -> bytes:
    """합성 sine wave PCM (16-bit mono) — 한국어 ASR 초기값 측정용 fallback."""
    n = int(duration_s * _SAMPLE_RATE)
    samples = [int(32767 * math.sin(2 * math.pi * freq * i / _SAMPLE_RATE)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


def _zeros_pcm(duration_s: float = 2.0) -> bytes:
    n = int(duration_s * _SAMPLE_RATE)
    return struct.pack(f"<{n}h", *([0] * n))


@pytest.mark.integration
class TestWhisperSTTIntegration:
    """실 faster-whisper medium 모델 로드 + flush_window 동작 확인."""

    @pytest.fixture(scope="class")
    def stt(self):
        try:
            from server.stt import WhisperSTT
        except ImportError as exc:
            pytest.skip(f"server.stt import 실패: {exc}")

        try:
            instance = WhisperSTT(model_size="medium", language="ko")
        except Exception as exc:
            pytest.skip(f"WhisperSTT 초기화 실패 (모델 없음?): {exc}")

        return instance

    async def test_warmup_completes(self, stt):
        """warmup() 이 예외 없이 완료되어야 함."""
        await stt.warmup()

    async def test_feed_and_flush_returns_string(self, stt):
        """PCM feed 후 flush_window → str 반환 (비어있어도 OK)."""
        pcm = _zeros_pcm(2.0)
        await stt.feed(pcm)
        result = await stt.flush_window(0.0, 2.0)
        assert isinstance(result, str)

    async def test_flush_short_duration_empty(self, stt):
        """0.1s 구간 → "" 반환 (spec-06 §3 최소 구간)."""
        result = await stt.flush_window(0.0, 0.1)
        assert result == ""

    async def test_flush_no_feed_empty(self, stt):
        """feed 없이 flush_window(5.0, 7.0) → "" (버퍼 부족)."""
        from server.stt.adapter import WhisperSTT as _W
        fresh = _W.__new__(_W)
        import asyncio
        fresh._model = stt._model
        fresh._language = "ko"
        fresh._beam_size = 5
        fresh._buffer = bytearray()
        fresh._lock = asyncio.Lock()

        result = await fresh.flush_window(5.0, 7.0)
        assert result == ""

    async def test_korean_sample_nonempty_if_wav_available(self, stt, tmp_path):
        """tests/data 에 ko_sample.wav 가 있으면 비어있지 않은 텍스트 반환 기대."""
        import os

        wav_path = "tests/data/ko_sample.wav"
        if not os.path.exists(wav_path):
            pytest.skip("ko_sample.wav 없음 — 합성 audio 로 빈 결과 허용")

        import wave

        with wave.open(wav_path, "rb") as wf:
            assert wf.getnchannels() == 1, "mono WAV 필요"
            assert wf.getframerate() == _SAMPLE_RATE, "16kHz WAV 필요"
            pcm = wf.readframes(wf.getnframes())

        duration = len(pcm) / (_SAMPLE_RATE * 2)

        fresh_stt = type(stt)(model_size="medium", language="ko")
        await fresh_stt.feed(pcm)
        result = await fresh_stt.flush_window(0.0, duration)

        assert isinstance(result, str)
        assert len(result) > 0, f"한국어 sample → 빈 문자열 반환 (WER 측정 불가): {wav_path}"
