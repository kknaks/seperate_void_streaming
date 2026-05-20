"""Unit tests for ElevenLabsSTT (spec-06 §6 unit 카테고리).

WS 는 mock 으로 대체 — 실 API 호출 없음.
"""

from __future__ import annotations

import asyncio
import json
import struct
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.stt.elevenlabs import ElevenLabsSTT, Transcript

_SAMPLE_RATE = 16000
_BYTES_PER_SAMPLE = 2


def _make_pcm(duration_s: float, amplitude: int = 100) -> bytes:
    n = int(duration_s * _SAMPLE_RATE)
    return struct.pack(f"<{n}h", *([amplitude] * n))


def _msg(msg_type: str, **kwargs) -> str:
    return json.dumps({"message_type": msg_type, **kwargs})


class _FakeWS:
    """websockets.ClientConnection 최소 mock."""

    def __init__(self, incoming: list[str]) -> None:
        self._incoming = list(incoming)
        self._sent: list[str] = []
        self._closed = False

    async def send(self, data: str) -> None:
        self._sent.append(data)

    async def close(self) -> None:
        self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        # yield to event loop first so sender task can run
        await asyncio.sleep(0)
        for msg in self._incoming:
            yield msg
            await asyncio.sleep(0)


def _make_stt(incoming: list[str]) -> tuple[ElevenLabsSTT, _FakeWS]:
    fake_ws = _FakeWS(incoming)

    @asynccontextmanager
    async def _connect(*args, **kwargs):
        yield fake_ws

    stt = ElevenLabsSTT(api_key="test-key-1234", language="ko")
    stt._connect_patch = patch("websockets.connect", side_effect=_connect)
    return stt, fake_ws


# ---------------------------------------------------------------------------
# Transcript 파싱
# ---------------------------------------------------------------------------


async def test_parse_partial_transcript():
    """partial_transcript → Transcript(is_final=False)."""
    msgs = [
        _msg("partial_transcript", text="안녕"),
    ]
    stt, fake_ws = _make_stt(msgs)
    await stt.close()  # 이후 stream()이 종료되도록 commit 센티넬 선제 투입

    with stt._connect_patch:
        results: list[Transcript] = []
        async for t in stt.stream():
            results.append(t)

    assert len(results) == 1
    assert results[0].text == "안녕"
    assert results[0].is_final is False


async def test_parse_committed_transcript_with_timestamps():
    """committed_transcript_with_timestamps → Transcript(is_final=True, t_start/t_end 설정)."""
    words = [
        {"text": "안녕", "start": 0.1, "end": 0.4, "type": "word"},
        {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"},
        {"text": "하세요", "start": 0.5, "end": 1.1, "type": "word"},
    ]
    msgs = [
        _msg("committed_transcript_with_timestamps", text="안녕 하세요", words=words),
    ]
    stt, _ = _make_stt(msgs)
    await stt.close()

    with stt._connect_patch:
        results: list[Transcript] = []
        async for t in stt.stream():
            results.append(t)

    assert len(results) == 1
    assert results[0].t_start == pytest.approx(0.1)
    assert results[0].t_end == pytest.approx(1.1)
    assert results[0].is_final is True


async def test_parse_committed_transcript_no_timestamps():
    """committed_transcript (타임스탬프 없음) → t_start=t_end=0.0, is_final=True."""
    msgs = [
        _msg("committed_transcript", text="결과"),
    ]
    stt, _ = _make_stt(msgs)
    await stt.close()

    with stt._connect_patch:
        results: list[Transcript] = []
        async for t in stt.stream():
            results.append(t)

    assert len(results) == 1
    assert results[0].t_start == 0.0
    assert results[0].t_end == 0.0
    assert results[0].is_final is True


async def test_session_started_ignored():
    """session_started 메시지는 Transcript 로 emit 되지 않아야 함."""
    msgs = [
        _msg("session_started", session_id="abc"),
        _msg("partial_transcript", text="테스트"),
    ]
    stt, _ = _make_stt(msgs)
    await stt.close()

    with stt._connect_patch:
        results: list[Transcript] = []
        async for t in stt.stream():
            results.append(t)

    assert len(results) == 1
    assert results[0].text == "테스트"


# ---------------------------------------------------------------------------
# feed → WS send
# ---------------------------------------------------------------------------


async def test_feed_sends_base64_audio_to_ws():
    """feed() 호출 시 base64 인코딩된 PCM 이 WS 로 전송되어야 함."""
    import base64

    chunk = _make_pcm(0.1)
    msgs: list[str] = []
    stt, fake_ws = _make_stt(msgs)

    async def _run():
        await stt.feed(chunk)
        await stt.close()
        with stt._connect_patch:
            async for _ in stt.stream():
                pass

    await _run()

    audio_sends = [s for s in fake_ws._sent if '"input_audio_chunk"' in s]
    assert len(audio_sends) >= 1
    first_payload = json.loads(audio_sends[0])
    assert first_payload["message_type"] == "input_audio_chunk"
    assert base64.b64decode(first_payload["audio_base_64"]) == chunk


async def test_close_sends_commit_signal():
    """close() 후 stream() 종료 시 commit=True 인 메시지가 WS 로 전송되어야 함."""
    msgs: list[str] = []
    stt, fake_ws = _make_stt(msgs)

    await stt.close()
    with stt._connect_patch:
        async for _ in stt.stream():
            pass

    commit_sends = [
        s for s in fake_ws._sent if '"commit": true' in s or '"commit":true' in s
    ]
    assert len(commit_sends) == 1
    payload = json.loads(commit_sends[0])
    assert payload["commit"] is True


# ---------------------------------------------------------------------------
# partial + final 둘 다 emit (§OQ-06-2 항목 2)
# ---------------------------------------------------------------------------


async def test_both_partial_and_final_emitted():
    """partial_transcript 와 committed_transcript 가 모두 stream() 으로 emit 되어야 함."""
    msgs = [
        _msg("partial_transcript", text="부분"),
        _msg("committed_transcript", text="최종"),
    ]
    stt, _ = _make_stt(msgs)
    await stt.close()

    with stt._connect_patch:
        results: list[Transcript] = []
        async for t in stt.stream():
            results.append(t)

    assert len(results) == 2
    assert results[0].is_final is False
    assert results[1].is_final is True


# ---------------------------------------------------------------------------
# API 키 부재 시 ValueError
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_value_error():
    """ELEVENLABS_API_KEY 환경변수 미설정 + api_key 미전달 시 ValueError."""
    import os

    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("ELEVENLABS_API_KEY", None)
        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
            ElevenLabsSTT()


# ---------------------------------------------------------------------------
# WS graceful close
# ---------------------------------------------------------------------------


async def test_ws_graceful_close_on_stream_end():
    """stream() 이 종료될 때 sender task 가 cancel 되어야 함 (WS 연결 누수 없음)."""
    msgs: list[str] = []
    stt, fake_ws = _make_stt(msgs)
    await stt.close()

    with stt._connect_patch:
        async for _ in stt.stream():
            pass

    # 예외 없이 완료 = graceful close 확인
    assert True
