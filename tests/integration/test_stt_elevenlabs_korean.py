"""ElevenLabsSTT 통합 테스트 — 실 ELEVENLABS_API_KEY + 한국어 sample (spec-06 §6).

실행 조건:
    ELEVENLABS_API_KEY 환경변수 설정
    pytest tests/integration/test_stt_elevenlabs_korean.py -m integration -v

ELEVENLABS_API_KEY 미설정 또는 ko_sample.wav 부재 시 자동 skip.
"""

from __future__ import annotations

import asyncio
import os
import struct

import pytest


def _zeros_pcm(duration_s: float = 2.0) -> bytes:
    n = int(duration_s * 16000)
    return struct.pack(f"<{n}h", *([0] * n))


@pytest.mark.integration
class TestElevenLabsSTTIntegration:
    """실 ELEVENLABS_API_KEY + stream() 동작 확인."""

    @pytest.fixture(autouse=True)
    def skip_if_no_key(self):
        if not os.environ.get("ELEVENLABS_API_KEY"):
            pytest.skip("ELEVENLABS_API_KEY 미설정")

    async def test_feed_and_stream_returns_transcript(self):
        """PCM feed 후 stream() → 최소 1개 Transcript 수신."""
        try:
            from server.stt.elevenlabs import ElevenLabsSTT, Transcript
        except ImportError as exc:
            pytest.skip(f"server.stt.elevenlabs import 실패: {exc}")

        stt = ElevenLabsSTT(language="ko")
        results: list[Transcript] = []

        async def _feed_and_close():
            for _ in range(4):  # 4 * 0.5s = 2s
                await stt.feed(_zeros_pcm(0.5))
                await asyncio.sleep(0.1)
            await stt.close()

        feed_task = asyncio.create_task(_feed_and_close())
        async for t in stt.stream():
            results.append(t)
        await feed_task

        assert len(results) >= 1
        for t in results:
            assert isinstance(t.text, str)
            assert isinstance(t.is_final, bool)

    async def test_korean_sample_nonempty_if_wav_available(self):
        """ko_sample.wav 가 있으면 비어있지 않은 텍스트 수신 기대."""
        import wave

        wav_path = "tests/data/ko_sample.wav"
        if not os.path.exists(wav_path):
            pytest.skip("ko_sample.wav 없음 — 실 오디오 테스트 skip")

        try:
            from server.stt.elevenlabs import ElevenLabsSTT, Transcript
        except ImportError as exc:
            pytest.skip(f"server.stt.elevenlabs import 실패: {exc}")

        with wave.open(wav_path, "rb") as wf:
            assert wf.getnchannels() == 1, "mono WAV 필요"
            assert wf.getframerate() == 16000, "16kHz WAV 필요"
            pcm = wf.readframes(wf.getnframes())

        stt = ElevenLabsSTT(language="ko")
        results: list[Transcript] = []

        chunk_size = 16000 * 2  # 1초 청크
        chunks = [pcm[i : i + chunk_size] for i in range(0, len(pcm), chunk_size)]

        async def _feed_and_close():
            for chunk in chunks:
                await stt.feed(chunk)
                await asyncio.sleep(0.05)
            await stt.close()

        feed_task = asyncio.create_task(_feed_and_close())
        async for t in stt.stream():
            results.append(t)
        await feed_task

        finals = [t for t in results if t.is_final]
        assert len(finals) >= 1
        combined_text = " ".join(t.text for t in finals)
        assert len(combined_text) > 0, f"한국어 sample → 빈 텍스트 반환: {wav_path}"
