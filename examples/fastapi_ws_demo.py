"""fastapi_ws_demo.py — FastAPI WebSocket + STT-driven Sequential Chain (adr-10, PLAN-006).

이전 Pattern B fanout (PLAN-005 / adr-02) 을 폐기하고
STT phrase boundary SSOT 기반 Sequential Chain 으로 재작성.

흐름:
  PCM → buf.append + stt.feed (동시)
    ↓
  stt.stream() partial  → ws stt 이벤트
  stt.stream() final    → phrase 단어 누적 → partial 도착 또는 스트림 종료 시 flush
    → buf.slice(t_start, t_end) → engine.identify_phrase → labeled_phrase 이벤트
  세션 종료: final_grouped + done

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
    from starlette.websockets import WebSocketState
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "fastapi 가 설치되지 않았습니다. 'pip install fastapi uvicorn' 을 실행하세요."
    ) from e

from server.audio.ringbuffer import PcmRingBuffer
from server.stt import ElevenLabsSTT, Transcript
from speaker_engine import SpeakerEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
# T-006 admin smoke 진단용 — STT raw 흐름 확인. 정식 코드 아님.
_stt_logger = logging.getLogger("server.stt")
_stt_logger.setLevel(logging.DEBUG)

_WORD_GAP_SPLIT_S = 0.4  # word gap threshold for phrase sub-split (PLAN-006-T-011)

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


def _merge_consecutive_phrases(phrases: list[dict]) -> list[dict]:
    """동일 label 연속 phrase 를 하나로 병합 (final_grouped 재구성).

    t_start 오름차순 정렬 후 label 연속 병합.
    """
    if not phrases:
        return []
    sorted_phrases = sorted(phrases, key=lambda p: p["t_start"])
    result: list[dict] = []
    for p in sorted_phrases:
        if result and result[-1]["label"] == p["label"]:
            result[-1]["text"] += " " + p["text"]
            result[-1]["t_end"] = max(result[-1]["t_end"], p["t_end"])
        else:
            result.append(dict(p))
    return result


@app.websocket("/audio/{visit_id}")
async def audio_ws(ws: WebSocket, visit_id: str) -> None:
    await ws.accept()
    logger.info("WS connected: visit_id=%s", visit_id)

    engine = SpeakerEngine()
    stt = ElevenLabsSTT(language="ko")
    buf = PcmRingBuffer()
    phrase_log: list[dict] = []  # labeled_phrase 누적 → final_grouped

    pcm_for_engine: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def pcm_loop() -> None:
        """PCM 수신 → ringbuffer 누적 + STT feed + engine 학습 채널 fan-out."""
        async for pcm in _pcm_stream(ws):
            buf.append(pcm)
            await stt.feed(pcm)
            await pcm_for_engine.put(pcm)
        await stt.close()
        await pcm_for_engine.put(None)  # sentinel → engine_iter 종료

    async def engine_iter():
        """engine.stream 용 PCM async iterator — 학습 채널."""
        while True:
            chunk = await pcm_for_engine.get()
            if chunk is None:
                break
            yield chunk

    async def engine_learn_loop() -> None:
        """engine.stream PCM 흘려서 OnlineSpeakerClusterer 학습 누적. segment yield 소비만, UI emit X."""
        logger.debug("engine.stream learning channel started: visit_id=%s", visit_id)
        async for _segment in engine.stream(engine_iter()):
            pass
        logger.debug("engine.stream learning channel finished: visit_id=%s", visit_id)

    async def stt_loop() -> None:
        """STT 스트림 처리 — phrase 단위 identify_phrase → labeled_phrase.

        phrase 경계 감지 정책:
          - is_final=True Transcript 를 phrase_words 에 누적
          - is_final=False (partial) 도착 시 직전 phrase_words flush
          - 스트림 종료 시 잔여 phrase_words flush
        ElevenLabs VAD 에서 한 committed_transcript_with_timestamps 의 모든
        단어는 next partial 이전에 도착하므로 이 정책이 phrase 경계를 정확히 포착.
        """
        phrase_words: list[Transcript] = []

        async def _flush_phrase() -> None:
            if not phrase_words:
                return
            # word gap > threshold 인 곳에서 sub-group 분할
            sub_groups: list[list[Transcript]] = []
            current: list[Transcript] = [phrase_words[0]]
            for prev, curr in zip(phrase_words, phrase_words[1:]):
                gap = curr.t_start - prev.t_end
                if gap > _WORD_GAP_SPLIT_S:
                    sub_groups.append(current)
                    current = [curr]
                else:
                    current.append(curr)
            sub_groups.append(current)

            gap_split = len(sub_groups) > 1
            for group in sub_groups:
                t_start = group[0].t_start
                t_end = group[-1].t_end
                text = " ".join(w.text for w in group)
                pcm_slice = buf.slice(t_start, t_end)
                label = await engine.identify_phrase(pcm_slice)
                entry: dict = {
                    "label": label,
                    "t_start": t_start,
                    "t_end": t_end,
                    "text": text,
                }
                phrase_log.append(entry)
                logger.info(
                    "[PHRASE] t=%.2f~%.2f dur=%.2fs label=%s words=%d slice=%dB gap_split=%s text=%r",
                    t_start, t_end, t_end - t_start, label, len(group),
                    len(pcm_slice), gap_split, text[:60],
                )
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json({"type": "labeled_phrase", **entry})
                else:
                    logger.info("WS already disconnected before labeled_phrase: visit_id=%s", visit_id)

            phrase_words.clear()

        async for transcript in stt.stream():
            await ws.send_json(
                {
                    "type": "stt",
                    "t_start": transcript.t_start,
                    "t_end": transcript.t_end,
                    "text": transcript.text,
                    "is_final": transcript.is_final,
                }
            )

            if not transcript.is_final:
                # partial 도착 = 직전 phrase 경계 → flush
                await _flush_phrase()
                continue

            # committed_transcript (타임스탬프 없음) 은 slice 불가 → skip
            if transcript.t_start == 0.0 and transcript.t_end == 0.0:
                continue

            phrase_words.append(transcript)

        # 스트림 종료 → 잔여 flush
        await _flush_phrase()

    try:
        async with engine:
            await asyncio.gather(pcm_loop(), engine_learn_loop(), stt_loop())

            if ws.client_state == WebSocketState.CONNECTED:
                final_utterances = _merge_consecutive_phrases(phrase_log)
                await ws.send_json({"type": "final_grouped", "utterances": final_utterances})
                await ws.send_json({"type": "done", "visit_id": visit_id})
            else:
                logger.info("WS already disconnected before final_grouped: visit_id=%s", visit_id)

    except WebSocketDisconnect:
        logger.info("WS disconnected: visit_id=%s", visit_id)
    except Exception:
        logger.exception("WS error: visit_id=%s", visit_id)
        try:
            await ws.send_json({"type": "error", "message": "Internal server error"})
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
