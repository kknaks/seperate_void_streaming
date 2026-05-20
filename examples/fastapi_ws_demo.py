"""fastapi_ws_demo.py — FastAPI WebSocket + Pattern B fanout + STT mock (planning-02 §150).

설치 (examples 전용 — 코어 의존성 아님):
    pip install fastapi uvicorn websockets

실행:
    export HF_TOKEN=hf_xxxxx
    export SPEAKER_ENGINE_STORAGE_URL=memory://
    uvicorn examples.fastapi_ws_demo:app --reload

WebSocket 연결:
    ws://localhost:8000/audio/{visit_id}
    바이너리 메시지로 PCM 16kHz mono 16-bit bytes 전송
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "fastapi 가 설치되지 않았습니다. 'pip install fastapi uvicorn' 을 실행하세요."
    ) from e

from speaker_engine import (
    LabelChange,
    SpeakerEngine,
    SpeakerSegment,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="speaker_engine WS demo")


async def _pcm_stream(ws: WebSocket) -> AsyncIterator[bytes]:
    """demo-local PCM 수신 루프 — eof 텍스트 프레임 처리 (spec-07 §7 graceful close).

    from_websocket 은 바이너리만 처리하므로 demo 전용으로 대체.
    - binary: PCM bytes yield
    - text {"type":"eof"}: generator 정상 종료 → done 전송 보장
    - websocket.disconnect: break
    """
    while True:
        try:
            message = await ws.receive()
        except WebSocketDisconnect:
            break
        if message["type"] == "websocket.disconnect":
            break
        chunk = message.get("bytes")
        if chunk:
            yield chunk
            continue
        text = message.get("text")
        if text:
            try:
                if json.loads(text).get("type") == "eof":
                    break
            except (json.JSONDecodeError, AttributeError):
                pass


class _MockSTT:
    """STT 구현체는 사용처 책임 (Pattern B fanout, adr-02). 여기선 stub."""

    async def feed(self, chunk: bytes) -> None:
        await asyncio.sleep(0)  # 실제 구현에서는 STT 백엔드로 전송

    async def flush_window(self, t_start: float, t_end: float) -> str:
        return f"[STT stub] {t_start:.2f}-{t_end:.2f}s"


@app.websocket("/audio/{visit_id}")
async def audio_ws(ws: WebSocket, visit_id: str) -> None:
    await ws.accept()
    logger.info("WS connected: visit_id=%s", visit_id)

    engine = SpeakerEngine()
    stt = _MockSTT()

    async def tee():
        """PCM 청크를 STT 와 엔진 양쪽에 fan-out (Pattern B, adr-02)."""
        async for chunk in _pcm_stream(ws):
            asyncio.create_task(stt.feed(chunk))
            yield chunk

    try:
        async with engine:
            async for event in engine.stream(tee()):
                if isinstance(event, SpeakerSegment):
                    text = await stt.flush_window(event.t_start, event.t_end)
                    await ws.send_json(
                        {
                            "type": "utterance",
                            "utterance_id": event.utterance_id,
                            "label": event.label,
                            "t_start": event.t_start,
                            "t_end": event.t_end,
                            "confidence": event.confidence,
                            "text": text,
                        }
                    )
                elif isinstance(event, LabelChange):
                    await ws.send_json(
                        {
                            "type": "relabel",
                            "old_label": event.old_label,
                            "new_label": event.new_label,
                            "reason": event.reason,
                            "affected_count": len(event.affected_utterance_ids),
                            "affected_utterance_ids": event.affected_utterance_ids,
                        }
                    )

            candidates = await engine.finalize()
            await ws.send_json(
                {
                    "type": "done",
                    "visit_id": visit_id,
                    "speaker_count": len(candidates),
                    "candidates": [
                        {
                            "auto_id": c.auto_id,
                            "utterance_count": c.utterance_count,
                            "total_duration": c.total_duration,
                        }
                        for c in candidates
                    ],
                }
            )

    except WebSocketDisconnect:
        logger.info("WS disconnected: visit_id=%s", visit_id)
    except Exception as exc:
        logger.exception("WS error: visit_id=%s", visit_id)
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# StaticFiles mount: /audio/{visit_id} WS 라우트 이후에 등록 (FastAPI 라우트 우선순위)
app.mount("/", StaticFiles(directory="web", html=True), name="web")
