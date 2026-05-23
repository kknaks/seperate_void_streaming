"""demo_v03.py — Phase 3 demo (PLAN-V03-T-001 skeleton + T-002 mapping).

v0.2 ablation 최적: pyannote/embedding × w=2.0 × s=0.5 × baseline
legacy v0.1 자산: ElevenLabs STT, PcmRingBuffer, web/index.html 4-panel

시간 overlap mapping: phrase 시간창 × segment_log → dominant speaker label (PLAN-V03-T-002).

실행:
    set -a && source .env && set +a
    uvicorn examples.demo_v03:app --host 0.0.0.0 --port 8000 --reload

WebSocket:
    ws://localhost:8000/audio/{visit_id}
    바이너리로 PCM 16kHz mono 16-bit bytes 전송
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
    from starlette.websockets import WebSocketState
except ImportError as e:
    raise ImportError("fastapi 설치 필요: pip install fastapi uvicorn") from e

# legacy v0.1 자산 (보존)
from server.audio.ringbuffer import PcmRingBuffer
from server.stt import ElevenLabsSTT, Transcript

# diart lazy import guard
try:
    import torch
    from diart.blocks import (
        OverlapAwareSpeakerEmbedding,
        OnlineSpeakerClustering,
        SpeakerSegmentation,
    )
    from diart.models import EmbeddingModel as _DiartEmbeddingModel, SegmentationModel
    from pyannote.core import SlidingWindow as _SlidingWindow, SlidingWindowFeature as _SlidingWindowFeature

    _DIART_AVAILABLE = True
except ImportError:
    _DIART_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Config — v0.2 ablation 최적 고정
# ─────────────────────────────────────────────────────────────────────────────
_SR = 16_000
_WINDOW_S = 2.0
_STEP_S = 0.5
_WINDOW_SAMPLES = int(_WINDOW_S * _SR)  # 32000
_STEP_SAMPLES = int(_STEP_S * _SR)      # 8000
_TAU_ACTIVE = 0.6   # baseline (spec-04 §4.3)
_RHO_UPDATE = 0.3
_DELTA_NEW = 1.0
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _resolve_label_from_segments(
    phrase_start: float,
    phrase_end: float,
    segments: list[SegmentResult],
) -> str | None:
    """Return dominant speaker label by time overlap. None if no overlap."""
    overlaps: dict[str, float] = {}
    for seg in segments:
        ov = max(0.0, min(phrase_end, seg.t_end) - max(phrase_start, seg.t_start))
        if ov > 0:
            overlaps[seg.speaker] = overlaps.get(seg.speaker, 0.0) + ov
    if not overlaps:
        return None
    return max(overlaps.items(), key=lambda x: x[1])[0]

# ─────────────────────────────────────────────────────────────────────────────
# powerset → multilabel (inlined from speaker_engine/diart_adapter.py)
# ─────────────────────────────────────────────────────────────────────────────
_POWERSET_MAPPING = np.array(
    [
        [0, 0, 0],  # 0: silence
        [1, 0, 0],  # 1: spk0
        [0, 1, 0],  # 2: spk1
        [0, 0, 1],  # 3: spk2
        [1, 1, 0],  # 4: spk0+spk1
        [1, 0, 1],  # 5: spk0+spk2
        [0, 1, 1],  # 6: spk1+spk2
    ],
    dtype=np.float32,
)


def _powerset_to_multilabel(scores: np.ndarray) -> np.ndarray:
    """powerset scores (T, 7) → multilabel (T, 3)."""
    hard = np.eye(7, dtype=np.float32)[np.argmax(scores, axis=-1)]
    return hard @ _POWERSET_MAPPING


# ─────────────────────────────────────────────────────────────────────────────
# DiartModels — model weights loaded once (shared across sessions)
# ─────────────────────────────────────────────────────────────────────────────
class DiartModels:
    """Shared diart model weights. Call load() once at startup."""

    def __init__(self) -> None:
        self._seg: SpeakerSegmentation | None = None
        self._emb: OverlapAwareSpeakerEmbedding | None = None
        self.loaded = False

    def load(self, hf_token: str | None = None, device: str = "cpu") -> None:
        """Sync — run via asyncio.to_thread."""
        if self.loaded:
            return
        if not _DIART_AVAILABLE:
            raise RuntimeError("diart/pyannote.audio 가 설치되지 않았습니다.")
        hf_token = hf_token or os.environ.get("HF_TOKEN")
        _device = torch.device(device)
        logger.info("DiartModels: loading models (device=%s, w=%.1f, s=%.1f, baseline)", device, _WINDOW_S, _STEP_S)
        seg_model = SegmentationModel.from_pyannote(
            "pyannote/segmentation-3.0",
            use_hf_token=hf_token or True,
        )
        emb_model = _DiartEmbeddingModel.from_pyannote(
            "pyannote/embedding",
            use_hf_token=hf_token or True,
        )
        self._seg = SpeakerSegmentation(seg_model, device=_device)
        self._emb = OverlapAwareSpeakerEmbedding(model=emb_model, device=_device)
        self.loaded = True
        logger.info("DiartModels: loaded OK")

    def new_session(self) -> DiartSession:
        if not self.loaded:
            raise RuntimeError("DiartModels.load() 를 먼저 호출하세요.")
        return DiartSession(self._seg, self._emb)  # type: ignore[arg-type]


_diart_models = DiartModels()
_diart_load_lock = asyncio.Lock()


async def _get_diart_session() -> DiartSession | None:
    """Lazy-load models on first call. Returns None if unavailable."""
    if not _DIART_AVAILABLE or not os.environ.get("HF_TOKEN"):
        return None
    async with _diart_load_lock:
        if not _diart_models.loaded:
            try:
                await asyncio.to_thread(_diart_models.load)
            except Exception:
                logger.exception("DiartModels load failed — diart disabled")
                return None
    return _diart_models.new_session()


# ─────────────────────────────────────────────────────────────────────────────
# DiartSession — per-WS-connection state (fresh OnlineSpeakerClustering)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SegmentResult:
    speaker: str
    t_start: float
    t_end: float


class DiartSession:
    """Per-session diart state. Sync process_window → call via asyncio.to_thread."""

    def __init__(self, seg: SpeakerSegmentation, emb: OverlapAwareSpeakerEmbedding) -> None:
        self._seg = seg
        self._emb = emb
        self._clusterer = OnlineSpeakerClustering(
            tau_active=_TAU_ACTIVE,
            rho_update=_RHO_UPDATE,
            delta_new=_DELTA_NEW,
            max_speakers=20,
        )

    def process_window(self, waveform: np.ndarray, session_t_start: float) -> list[SegmentResult]:
        """Process one _WINDOW_S window → list[SegmentResult]. Sync."""
        if len(waveform) < _WINDOW_SAMPLES:
            waveform = np.pad(waveform, (0, _WINDOW_SAMPLES - len(waveform)))
        else:
            waveform = waveform[:_WINDOW_SAMPLES]

        wav_t = torch.from_numpy(waveform.astype(np.float32)).unsqueeze(0).unsqueeze(-1)  # (1, T, 1)

        # 1. Segmentation
        seg_out = self._seg(wav_t)

        # 2. Extract numpy data
        if hasattr(seg_out, "data") and isinstance(seg_out.data, np.ndarray):
            seg_data = seg_out.data
        elif isinstance(seg_out, np.ndarray):
            seg_data = seg_out
        else:
            seg_data = np.array(seg_out)
        if seg_data.ndim == 3:
            seg_data = seg_data[0]

        n_frames, n_classes = seg_data.shape
        seg_ml = (
            _powerset_to_multilabel(seg_data.astype(np.float32))
            if n_classes == 7
            else seg_data.astype(np.float32)
        )

        # 3. Speaker embedding
        emb_out = self._emb(wav_t, seg_out)
        if hasattr(emb_out, "detach"):
            emb_arr = emb_out.detach().cpu().numpy()
        elif isinstance(emb_out, np.ndarray):
            emb_arr = emb_out
        else:
            emb_arr = np.array(emb_out)
        if emb_arr.ndim == 3:
            emb_arr = emb_arr[0]
        emb_arr = emb_arr.astype(np.float32)

        # 4. Online clustering
        frame_dur = _WINDOW_S / max(n_frames, 1)
        sw = _SlidingWindow(duration=frame_dur, step=frame_dur, start=0.0)
        seg_swf = _SlidingWindowFeature(seg_ml, sw)
        speaker_map = self._clusterer.identify(seg_swf, torch.from_numpy(emb_arr))
        local_spks, global_spks = speaker_map.valid_assignments()

        # 5. Build results
        results: list[SegmentResult] = []
        n_local = seg_ml.shape[1]
        for l_spk, g_spk in zip(local_spks, global_spks):
            if l_spk >= n_local:
                continue
            active = np.where(seg_ml[:, l_spk] > 0.5)[0]
            if len(active) == 0:
                continue
            t_s = session_t_start + float(active[0]) / n_frames * _WINDOW_S
            t_e = session_t_start + float(active[-1] + 1) / n_frames * _WINDOW_S
            label = f"auto:{chr(ord('A') + int(g_spk) % 26)}"
            results.append(SegmentResult(speaker=label, t_start=t_s, t_end=t_e))
            logger.info("segment(speaker=%s, t_start=%.2f, t_end=%.2f)", label, t_s, t_e)

        return results


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="void_streaming Phase 3 demo")


# ─────────────────────────────────────────────────────────────────────────────
# PCM stream helper (from fastapi_ws_demo.py pattern)
# ─────────────────────────────────────────────────────────────────────────────
async def _pcm_stream(ws: WebSocket):
    """Yield binary PCM chunks until WS disconnect or EOF text frame."""
    while True:
        try:
            msg = await ws.receive()
        except WebSocketDisconnect:
            break
        if msg["type"] == "websocket.disconnect":
            break
        chunk = msg.get("bytes")
        if chunk:
            yield chunk
            continue
        text = msg.get("text")
        if text:
            try:
                if json.loads(text).get("type") == "eof":
                    break
            except (json.JSONDecodeError, AttributeError):
                pass


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket endpoint
# ─────────────────────────────────────────────────────────────────────────────
@app.websocket("/audio/{visit_id}")
async def audio_ws(ws: WebSocket, visit_id: str) -> None:
    await ws.accept()
    logger.info("WS connected: visit_id=%s", visit_id)

    stt = ElevenLabsSTT(language="ko")
    buf = PcmRingBuffer()
    phrase_log: list[dict] = []
    segment_log: list[SegmentResult] = []

    diart_session = await _get_diart_session()
    if diart_session is None:
        logger.warning("visit_id=%s: diart unavailable — placeholder labels only", visit_id)

    pcm_for_diart: asyncio.Queue[bytes | None] = asyncio.Queue()

    # Live latency hook (PLAN-V04-T-001):
    #   각 phrase 의 audio 끝나는 시점 (t_end) 의 PCM 청크가 server 도착한 wall-clock vs
    #   labeled_phrase emit wall-clock 차이 = 진짜 라이브 라벨링 latency.
    session_start_wallclock = time.perf_counter()
    audio_recv_log: list[tuple[float, float]] = []  # (audio_t_offset_s, recv_wallclock_offset_s)
    latency_log: list[dict] = []

    async def pcm_loop() -> None:
        async for chunk in _pcm_stream(ws):
            recv_wc = time.perf_counter() - session_start_wallclock
            buf.append(chunk)
            # PCM 청크 끝 시점의 audio_t 추정 = current ringbuffer duration
            audio_t = buf.duration_s()
            audio_recv_log.append((audio_t, recv_wc))
            await stt.feed(chunk)
            await pcm_for_diart.put(chunk)
        await stt.close()
        await pcm_for_diart.put(None)  # sentinel

    async def diart_loop() -> None:
        pcm_buf = bytearray()
        session_t = 0.0
        while True:
            chunk = await pcm_for_diart.get()
            if chunk is None:
                break
            if diart_session is None:
                continue
            pcm_buf.extend(chunk)
            while len(pcm_buf) >= _WINDOW_SAMPLES * 2:  # int16 = 2 B/sample
                window = np.frombuffer(bytes(pcm_buf[: _WINDOW_SAMPLES * 2]), dtype=np.int16).astype(np.float32) / 32768.0
                try:
                    segs = await asyncio.to_thread(diart_session.process_window, window, session_t)
                    segment_log.extend(segs)
                except Exception:
                    logger.exception("diart window error (t=%.2fs)", session_t)
                del pcm_buf[: _STEP_SAMPLES * 2]
                session_t += _STEP_S

    async def stt_loop() -> None:
        phrase_words: list[Transcript] = []

        async def _flush() -> None:
            if not phrase_words:
                return
            t_start = phrase_words[0].t_start
            t_end = phrase_words[-1].t_end
            text = " ".join(w.text for w in phrase_words)
            label = _resolve_label_from_segments(t_start, t_end, segment_log)
            if label is None:
                label = segment_log[-1].speaker if segment_log else "unknown"
            entry: dict = {
                "label": label,
                "t_start": t_start,
                "t_end": t_end,
                "text": text,
            }
            phrase_log.append(entry)
            # Live latency 측정 — phrase t_end 의 PCM 청크 도착 wallclock vs 현재 emit wallclock
            emit_wc = time.perf_counter() - session_start_wallclock
            audio_recv_wc = None
            for audio_t, recv_wc in audio_recv_log:
                if audio_t >= t_end:
                    audio_recv_wc = recv_wc
                    break
            latency_s = (emit_wc - audio_recv_wc) if audio_recv_wc is not None else None
            latency_log.append({
                "phrase_t_start": t_start,
                "phrase_t_end": t_end,
                "audio_recv_wallclock": audio_recv_wc,
                "emit_wallclock": emit_wc,
                "latency_s": latency_s,
                "label": label,
            })
            logger.info(
                "[PHRASE] t=%.2f~%.2f label=%s latency=%s text=%r",
                t_start, t_end, label,
                f"{latency_s:.3f}s" if latency_s is not None else "N/A",
                text[:60],
            )
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json({"type": "labeled_phrase", **entry})
            phrase_words.clear()

        async for t in stt.stream():
            await ws.send_json({
                "type": "stt",
                "t_start": t.t_start,
                "t_end": t.t_end,
                "text": t.text,
                "is_final": t.is_final,
            })
            if not t.is_final:
                await _flush()
                continue
            if t.t_start == 0.0 and t.t_end == 0.0:
                continue
            phrase_words.append(t)

        await _flush()

    try:
        await asyncio.gather(pcm_loop(), diart_loop(), stt_loop())

        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json({"type": "final_grouped", "utterances": phrase_log})
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
        # Live latency JSON 저장 (DEMO_V03_LATENCY_LOG=1 env var 시)
        if os.environ.get("DEMO_V03_LATENCY_LOG") == "1" and latency_log:
            out_dir = Path("eval/ablation/results/v04")
            out_dir.mkdir(parents=True, exist_ok=True)
            valid = [r for r in latency_log if r.get("latency_s") is not None]
            ls = [r["latency_s"] for r in valid]
            ls_sorted = sorted(ls)
            def _pct(p):
                if not ls_sorted:
                    return None
                idx = max(0, min(len(ls_sorted) - 1, int(round((p / 100.0) * (len(ls_sorted) - 1)))))
                return ls_sorted[idx]
            payload = {
                "visit_id": visit_id,
                "embedding": os.environ.get("DEMO_V03_EMBEDDING", "pyannote/embedding"),
                "sample": os.environ.get("DEMO_V03_SAMPLE", "unknown"),
                "duration_s": buf.duration_s(),
                "phrase_count": len(phrase_log),
                "metrics": {
                    "live_emit_latency_p50_s": _pct(50),
                    "live_emit_latency_p95_s": _pct(95),
                    "live_emit_latency_max_s": max(ls) if ls else None,
                    "phrases_measured": len(valid),
                },
                "latency_per_phrase": latency_log,
            }
            out_path = out_dir / f"live-{visit_id}.json"
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Latency JSON saved: %s (p50=%s p95=%s)", out_path,
                        f"{_pct(50):.3f}s" if _pct(50) else "N/A",
                        f"{_pct(95):.3f}s" if _pct(95) else "N/A")


# StaticFiles: /audio/{visit_id} WS 라우트 이후 등록 (FastAPI 라우트 우선순위)
app.mount("/", StaticFiles(directory="web", html=True), name="web")
