"""fastapi_ws_demo.py — FastAPI WebSocket + Pattern B fanout + ElevenLabsSTT (spec-07 §3).

설치 (examples 전용 — 코어 의존성 아님):
    pip install fastapi uvicorn websockets

실행:
    export HF_TOKEN=hf_xxxxx
    export ELEVENLABS_API_KEY=sk_xxxxx
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

from server.stt import ElevenLabsSTT, Transcript
from speaker_engine import (
    LabelChange,
    SpeakerEngine,
    SpeakerSegment,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="speaker_engine WS demo")


def _build_final_utterances(
    word_log: list[dict], label_changes: list[LabelChange]
) -> list[dict]:
    """finalize 후 canonical 라벨 기준 utterance 단위 재구성 (adr-09, spec-07 §3).

    정책:
    - LabelChange.affected_utterance_ids 를 segment_id → new_label 매핑으로 적용.
    - 미매핑 단어(segment_id 없거나 label 없음)는 final_grouped 에서 제외.
    - 시간순 정렬 후 같은 label 연속이면 한 utterance 로 병합.
    """
    id_to_label: dict[str, str] = {}
    for ch in label_changes:
        for uid in ch.affected_utterance_ids:
            id_to_label[uid] = ch.new_label

    words: list[dict] = []
    for w in word_log:
        label = id_to_label.get(w.get("segment_id", ""), w.get("label"))
        if not label:
            continue
        words.append({**w, "label": label})

    words.sort(key=lambda w: w["t_start"])
    utterances: list[dict] = []
    for w in words:
        if utterances and utterances[-1]["label"] == w["label"]:
            utterances[-1]["text"] += " " + w["text"]
            utterances[-1]["t_end"] = max(utterances[-1]["t_end"], w["t_end"])
        else:
            utterances.append(
                {
                    "label": w["label"],
                    "t_start": w["t_start"],
                    "t_end": w["t_end"],
                    "text": w["text"],
                }
            )
    return utterances


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


@app.websocket("/audio/{visit_id}")
async def audio_ws(ws: WebSocket, visit_id: str) -> None:
    await ws.accept()
    logger.info("WS connected: visit_id=%s", visit_id)

    engine = SpeakerEngine()
    stt = ElevenLabsSTT(language="ko")

    # ── live grouping state (adr-09, Pattern B 유지) ──
    pending_words: list[dict] = []       # segment 미도착 단어 버퍼
    segments_emitted: list[dict] = []    # 시간 매칭용 segment 히스토리
    word_log: list[dict] = []            # final_grouped 재구성용 단어 누적
    label_changes_applied: list[LabelChange] = []  # finalize 후 라벨 보정용

    def _find_covering_segment(word: dict) -> dict | None:
        """word.t_start 를 커버하는 가장 최근 segment 반환.

        매칭 정책: contain — seg.t_start ≤ word.t_start ≤ seg.t_end.
        다중 매칭 시 가장 최근 segment 우선 (engine sliding window 특성상 최신이 더 정확).
        """
        t = word["t_start"]
        for seg in reversed(segments_emitted):
            if seg["t_start"] <= t <= seg["t_end"]:
                return seg
        return None

    async def _emit_labeled_word(word: dict, seg: dict) -> None:
        entry = {
            "label": seg["label"],
            "t_start": word["t_start"],
            "t_end": word["t_end"],
            "text": word["text"],
            "segment_id": seg["segment_id"],
        }
        word_log.append(entry)
        await ws.send_json({"type": "labeled_word", **entry})

    async def attribute_word(word: dict) -> None:
        """final word 의 covering segment 를 찾아 labeled_word emit. 없으면 pending."""
        seg = _find_covering_segment(word)
        if seg is not None:
            await _emit_labeled_word(word, seg)
        else:
            pending_words.append(word)

    async def flush_pending_for(seg: dict) -> None:
        """새 segment 도착 후 pending_words 중 해당 segment 구간 단어 처리."""
        still_pending: list[dict] = []
        for word in pending_words:
            if seg["t_start"] <= word["t_start"] <= seg["t_end"]:
                await _emit_labeled_word(word, seg)
            else:
                still_pending.append(word)
        pending_words.clear()
        pending_words.extend(still_pending)

    async def tee() -> AsyncIterator[bytes]:
        """PCM 청크를 STT 와 엔진 양쪽에 fan-out (Pattern B, adr-02)."""
        async for chunk in _pcm_stream(ws):
            asyncio.create_task(stt.feed(chunk))
            yield chunk

    async def forward_stt_stream() -> None:
        """STT 채널 — Transcript 이벤트를 stt 타입 JSON 으로 push (spec-07 §3).

        is_final=True 단어만 live grouping 대상 (partial 은 timestamps 없음).
        """
        async for t in stt.stream():
            await ws.send_json(
                {
                    "type": "stt",
                    "t_start": t.t_start,
                    "t_end": t.t_end,
                    "text": t.text,
                    "is_final": t.is_final,
                }
            )
            if t.is_final:
                await attribute_word(
                    {"t_start": t.t_start, "t_end": t.t_end, "text": t.text}
                )

    async def engine_channel() -> list:
        """Engine 채널 — SpeakerSegment/LabelChange 처리 후 stt.close() + finalize."""
        async for event in engine.stream(tee()):
            if isinstance(event, SpeakerSegment):
                seg = {
                    "segment_id": event.utterance_id,
                    "label": event.label,
                    "t_start": event.t_start,
                    "t_end": event.t_end,
                }
                segments_emitted.append(seg)
                await ws.send_json(
                    {
                        "type": "segment",
                        "utterance_id": event.utterance_id,
                        "label": event.label,
                        "t_start": event.t_start,
                        "t_end": event.t_end,
                        "confidence": event.confidence,
                    }
                )
                await flush_pending_for(seg)
            elif isinstance(event, LabelChange):
                label_changes_applied.append(event)
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
        # PCM 소진 → STT commit 시그널 → forward_stt_stream 이 drain 후 종료
        await stt.close()
        return await engine.finalize()

    try:
        async with engine:
            candidates, _ = await asyncio.gather(
                engine_channel(),
                forward_stt_stream(),
            )

            # ── finalize 후 final_grouped 재구성 (done 직전, spec-07 §3) ──
            final_utterances = _build_final_utterances(word_log, label_changes_applied)
            await ws.send_json({"type": "final_grouped", "utterances": final_utterances})

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
            await stt.close()
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass


# StaticFiles mount: /audio/{visit_id} WS 라우트 이후에 등록 (FastAPI 라우트 우선순위)
app.mount("/", StaticFiles(directory="web", html=True), name="web")
