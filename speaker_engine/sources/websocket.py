"""from_websocket — WebSocket 오디오 소스 헬퍼 (H-01, spec-01 §2-2)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

try:
    from starlette.websockets import WebSocketDisconnect as _WebSocketDisconnect
except ImportError:
    _WebSocketDisconnect = None  # type: ignore[assignment, misc]

_log = logging.getLogger(__name__)


async def from_websocket(ws: "WebSocket") -> AsyncIterator[bytes]:
    """FastAPI/Starlette WebSocket recv loop → PCM bytes 스트림."""
    while True:
        try:
            message = await ws.receive()
        except Exception as exc:
            if _WebSocketDisconnect is not None and isinstance(exc, _WebSocketDisconnect):
                break
            raise
        if message["type"] == "websocket.disconnect":
            break
        chunk = message.get("bytes")
        if chunk is not None:
            yield chunk
        else:
            _log.warning("from_websocket: non-bytes message received, skipping")
