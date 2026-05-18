"""unit tests — speaker_engine.sources.websocket (H-01, spec-05 §2-2 unit 카테고리).

외부 의존 0: starlette 없이 모듈 import 가능 검증 + AsyncMock 으로 WebSocket 격리.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from speaker_engine.sources.websocket import from_websocket


def _make_ws(*messages: dict) -> MagicMock:
    """AsyncMock receive() 가 순서대로 메시지를 반환하는 mock WebSocket."""
    ws = MagicMock()
    ws.receive = AsyncMock(side_effect=list(messages))
    return ws


def _bytes_msg(chunk: bytes) -> dict:
    return {"type": "websocket.receive", "bytes": chunk, "text": None}


def _text_msg(text: str) -> dict:
    return {"type": "websocket.receive", "bytes": None, "text": text}


def _disconnect_msg(code: int = 1000) -> dict:
    return {"type": "websocket.disconnect", "code": code}


# ── 정상 bytes 흐름 ───────────────────────────────────────────────────────────


class TestFromWebsocketBytesFlow:
    async def test_n_chunks_yield_n_bytes(self):
        ws = _make_ws(
            _bytes_msg(b"chunk1"),
            _bytes_msg(b"chunk2"),
            _bytes_msg(b"chunk3"),
            _disconnect_msg(),
        )
        result = []
        async for chunk in from_websocket(ws):
            result.append(chunk)
        assert result == [b"chunk1", b"chunk2", b"chunk3"]

    async def test_zero_chunks_yields_nothing(self):
        ws = _make_ws(_disconnect_msg())
        result = []
        async for chunk in from_websocket(ws):
            result.append(chunk)
        assert result == []

    async def test_single_chunk_yields_once(self):
        ws = _make_ws(_bytes_msg(b"\x00\xff"), _disconnect_msg())
        result = []
        async for chunk in from_websocket(ws):
            result.append(chunk)
        assert result == [b"\x00\xff"]

    async def test_empty_bytes_chunk_is_yielded(self):
        """b'' 빈 chunk 는 그대로 yield — PCM 검증은 SpeakerEngine 책임."""
        ws = _make_ws(_bytes_msg(b""), _disconnect_msg())
        result = []
        async for chunk in from_websocket(ws):
            result.append(chunk)
        assert result == [b""]


# ── disconnect 처리 ───────────────────────────────────────────────────────────


class TestFromWebsocketDisconnect:
    async def test_disconnect_message_terminates_generator(self):
        ws = _make_ws(_bytes_msg(b"a"), _disconnect_msg())
        result = []
        async for chunk in from_websocket(ws):
            result.append(chunk)
        assert result == [b"a"]

    async def test_websocket_disconnect_exception_terminates_gracefully(self):
        """WebSocketDisconnect 예외 → generator 자연 종료 (외부 전파 X)."""
        try:
            from starlette.websockets import WebSocketDisconnect
        except ImportError:
            pytest.skip("starlette not installed")

        ws = MagicMock()
        ws.receive = AsyncMock(side_effect=WebSocketDisconnect())
        result = []
        async for chunk in from_websocket(ws):
            result.append(chunk)
        assert result == []

    async def test_disconnect_after_several_chunks(self):
        chunks = [_bytes_msg(f"c{i}".encode()) for i in range(5)]
        ws = _make_ws(*chunks, _disconnect_msg())
        result = []
        async for chunk in from_websocket(ws):
            result.append(chunk)
        assert len(result) == 5


# ── 비-bytes 메시지 처리 (skip + WARN) ────────────────────────────────────────


class TestFromWebsocketNonBytesMessages:
    async def test_text_message_skipped(self):
        ws = _make_ws(
            _text_msg("hello"),
            _bytes_msg(b"audio"),
            _disconnect_msg(),
        )
        result = []
        async for chunk in from_websocket(ws):
            result.append(chunk)
        assert result == [b"audio"]

    async def test_text_message_emits_warning(self, caplog: pytest.LogCaptureFixture):
        ws = _make_ws(_text_msg("ignored"), _disconnect_msg())
        with caplog.at_level(logging.WARNING, logger="speaker_engine.sources.websocket"):
            async for _ in from_websocket(ws):
                pass
        assert any("non-bytes" in r.message for r in caplog.records)

    async def test_multiple_text_messages_all_skipped(self):
        ws = _make_ws(
            _text_msg("t1"),
            _bytes_msg(b"good"),
            _text_msg("t2"),
            _disconnect_msg(),
        )
        result = []
        async for chunk in from_websocket(ws):
            result.append(chunk)
        assert result == [b"good"]


# ── 비정상 예외 전파 ──────────────────────────────────────────────────────────


class TestFromWebsocketErrorPropagation:
    async def test_unexpected_exception_propagates(self):
        ws = MagicMock()
        ws.receive = AsyncMock(side_effect=ConnectionError("network failure"))
        with pytest.raises(ConnectionError):
            async for _ in from_websocket(ws):
                pass


# ── import 격리 검증 ──────────────────────────────────────────────────────────


class TestFromWebsocketImport:
    def test_module_importable(self):
        """speaker_engine.sources.websocket 는 starlette 미설치 환경에서도 import 가능."""
        import speaker_engine.sources.websocket as ws_mod

        assert hasattr(ws_mod, "from_websocket")
        assert callable(ws_mod.from_websocket)

    def test_top_level_import(self):
        """speaker_engine 최상위에서 from_websocket re-export 확인."""
        from speaker_engine import from_websocket as fw

        assert callable(fw)
