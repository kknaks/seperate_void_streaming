#!/usr/bin/env python3
"""Realtime ablation: live streaming DER + emit latency measurement.

PLAN-V03-T-002 — Phase 3 본격 측정 스크립트.

v0.2 (eval_ablation.py) 와 차이:
- offline StreamingInference X → 수동 슬라이딩 윈도우 루프 (demo_v03 diart_loop 동일)
- 라이브 emit latency 측정: wallclock_at_emit - audio_t_end_of_window
  양수 = real-time 뒤처짐, 음수 = real-time 앞섬
- online DER 스냅샷: 30s/60s/end 시점에서 segment_log → Annotation → DER
- 2 embedding (pyannote/embedding, ecapa-tdnn) × 2 sample 배치 실행 지원

Usage:
    python scripts/realtime_ablation.py \\
        --embedding pyannote/embedding \\
        --sample eval/data/korean/record_1.wav \\
        --gt-rttm eval/data/korean/record_1.rttm \\
        --output eval/ablation/results/v03/

    # batch 4 rows
    python scripts/realtime_ablation.py \\
        --embeddings pyannote/embedding ecapa-tdnn \\
        --samples eval/data/korean/record_1.wav eval/data/korean/record_3.wav \\
        --gt-rttm-dir eval/data/korean/ \\
        --output eval/ablation/results/v03/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import psutil
import soundfile as sf
import torch

# ── diart ─────────────────────────────────────────────────────────────────────
from diart.blocks import (
    OnlineSpeakerClustering,
    OverlapAwareSpeakerEmbedding,
    SpeakerSegmentation,
)
from diart.models import EmbeddingModel as DiartEmbeddingModel, SegmentationModel
from pyannote.core import Annotation, Segment, SlidingWindow, SlidingWindowFeature
from pyannote.metrics.diarization import DiarizationErrorRate

# ── embedding wrappers ─────────────────────────────────────────────────────────
from eval.embeddings.pyannote_emb import PyannoteEmbedding
from eval.embeddings.ecapa_tdnn import EcapaTdnnEmbedding

# ─────────────────────────────────────────────────────────────────────────────
# Config — v0.2 ablation 최적 고정 (spec-04 §4.3)
# ─────────────────────────────────────────────────────────────────────────────
_SR = 16_000
_WINDOW_S = 2.0
_STEP_S = 0.5
_WINDOW_SAMPLES = int(_WINDOW_S * _SR)   # 32000 samples
_STEP_SAMPLES = int(_STEP_S * _SR)       # 8000 samples
_TAU_ACTIVE = 0.6
_RHO_UPDATE = 0.3
_DELTA_NEW = 1.0

_POWERSET_MAPPING = np.array(
    [
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
        [1, 1, 0],
        [1, 0, 1],
        [0, 1, 1],
    ],
    dtype=np.float32,
)


def _powerset_to_multilabel(scores: np.ndarray) -> np.ndarray:
    hard = np.eye(7, dtype=np.float32)[np.argmax(scores, axis=-1)]
    return hard @ _POWERSET_MAPPING


# ─────────────────────────────────────────────────────────────────────────────
# ResourceMonitor (reused from eval_ablation.py pattern)
# ─────────────────────────────────────────────────────────────────────────────
class ResourceMonitor:
    def __init__(self, pid: int) -> None:
        self._pid = pid
        self._cpu: list[float] = []
        self._ram: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc = psutil.Process(pid)

    def start(self) -> None:
        self._stop.clear()
        self._cpu.clear()
        self._ram.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        self._proc.cpu_percent(interval=None)
        while not self._stop.is_set():
            try:
                self._cpu.append(self._proc.cpu_percent(interval=None))
                self._ram.append(self._proc.memory_info().rss / 1e6)
            except psutil.NoSuchProcess:
                break
            time.sleep(1.0)

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        cpu = self._cpu or [0.0]
        ram = self._ram or [0.0]
        return {
            "cpu_peak_pct": float(max(cpu)),
            "cpu_avg_pct": float(np.mean(cpu)),
            "ram_peak_mb": float(max(ram)),
            "ram_avg_mb": float(np.mean(ram)),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Embedding → diart wrapper (reused pattern from eval_ablation.py §370-377)
# ─────────────────────────────────────────────────────────────────────────────
class _DiartEmbeddingCallable:
    def __init__(self, our_model) -> None:
        self._model = our_model
        self._device = torch.device("cpu")

    def to(self, device):
        self._device = device if isinstance(device, torch.device) else torch.device(device)
        return self

    def __call__(self, waveform: torch.Tensor, weights=None) -> torch.Tensor:
        batch_size = waveform.shape[0]
        results = []
        for i in range(batch_size):
            wav_np = waveform[i].mean(dim=0).cpu().numpy().astype(np.float32)
            vec = self._model.extract(wav_np, sr=_SR)
            results.append(vec)
        return torch.tensor(np.array(results), dtype=torch.float32)


def _make_diart_embedding(our_model) -> DiartEmbeddingModel:
    callable_wrapper = _DiartEmbeddingCallable(our_model)

    def _loader():
        return callable_wrapper

    return DiartEmbeddingModel(loader=_loader)


# ─────────────────────────────────────────────────────────────────────────────
# RTTM loader
# ─────────────────────────────────────────────────────────────────────────────
def load_rttm(rttm_path: str) -> Annotation:
    ann = Annotation(uri=Path(rttm_path).stem)
    with open(rttm_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            start = float(parts[3])
            dur = float(parts[4])
            speaker = parts[7]
            ann[Segment(start, start + dur)] = speaker
    return ann


_FRAME_RES = 0.1  # seconds per frame for online DER state tracking


def _frames_to_annotation(frame_labels: dict[int, str], up_to_t: float) -> Annotation:
    """Convert frame-level state to Annotation (no overlaps, last-write wins)."""
    ann = Annotation()
    if not frame_labels:
        return ann
    sorted_frames = sorted(frame_labels.items())
    start_fi, cur_label = sorted_frames[0]
    end_fi = start_fi
    for fi, lbl in sorted_frames[1:]:
        t = fi * _FRAME_RES
        if t >= up_to_t:
            break
        if lbl == cur_label and fi == end_fi + 1:
            end_fi = fi
        else:
            t_s = start_fi * _FRAME_RES
            t_e = min((end_fi + 1) * _FRAME_RES, up_to_t)
            if t_e > t_s:
                ann[Segment(t_s, t_e)] = cur_label
            start_fi, cur_label, end_fi = fi, lbl, fi
    t_s = start_fi * _FRAME_RES
    t_e = min((end_fi + 1) * _FRAME_RES, up_to_t)
    if t_e > t_s:
        ann[Segment(t_s, t_e)] = cur_label
    return ann


def _compute_online_der(
    frame_labels: dict[int, str],
    reference: Annotation,
    up_to_t: float,
) -> float:
    """DER using frame-level state (no overlap inflation) up to audio time up_to_t."""
    hyp = _frames_to_annotation(frame_labels, up_to_t)
    ref_crop = reference.crop(Segment(0, up_to_t))
    der_metric = DiarizationErrorRate(collar=0.25)
    try:
        return float(der_metric(ref_crop, hyp))
    except Exception:
        return float("nan")


# ─────────────────────────────────────────────────────────────────────────────
# Single run (one embedding × one sample)
# ─────────────────────────────────────────────────────────────────────────────
def run_one(
    emb_name: str,
    our_model,
    sample_path: str,
    gt_rttm_path: str,
    hf_token: str | None,
    device: str = "cpu",
) -> dict:
    """Simulate live streaming on a WAV file, return metric dict."""
    monitor = ResourceMonitor(os.getpid())
    monitor.start()

    try:
        _device = torch.device(device)

        # Load diart models
        seg_model = SegmentationModel.from_pyannote(
            "pyannote/segmentation-3.0",
            use_hf_token=hf_token or True,
        )
        seg_block = SpeakerSegmentation(seg_model, device=_device)
        diart_emb = _make_diart_embedding(our_model)
        emb_block = OverlapAwareSpeakerEmbedding(model=diart_emb, device=_device)
        clusterer = OnlineSpeakerClustering(
            tau_active=_TAU_ACTIVE,
            rho_update=_RHO_UPDATE,
            delta_new=_DELTA_NEW,
            max_speakers=20,
        )

        # Load audio
        audio, file_sr = sf.read(sample_path, dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if file_sr != _SR:
            import torchaudio
            wav_t = torch.from_numpy(audio).unsqueeze(0)
            wav_t = torchaudio.functional.resample(wav_t, file_sr, _SR)
            audio = wav_t.squeeze(0).numpy()
        audio_dur = len(audio) / _SR

        reference = load_rttm(gt_rttm_path)

        # segment_log: (speaker, t_start, t_end) — for reporting counts
        segment_log: list[tuple[str, float, float]] = []
        # frame_labels: frame_index → speaker (last-write-wins, no overlap inflation)
        frame_labels: dict[int, str] = {}
        # emit_latencies: wallclock_at_emit - audio_t_end (positive = behind realtime)
        emit_latencies: list[float] = []
        # online DER snapshots
        der_at: dict[str, float] = {}

        stream_start_wc = time.perf_counter()
        pcm_buf = bytearray(audio.astype(np.float32).tobytes())
        buf_offset = 0
        session_t = 0.0

        # Sliding window loop (mirror demo_v03 diart_loop)
        while buf_offset + _WINDOW_SAMPLES * 4 <= len(pcm_buf):  # float32 = 4 bytes
            window = np.frombuffer(
                bytes(pcm_buf[buf_offset: buf_offset + _WINDOW_SAMPLES * 4]),
                dtype=np.float32,
            )
            audio_t_end = session_t + _WINDOW_S

            wav_t = torch.from_numpy(window).unsqueeze(0).unsqueeze(-1)  # (1, T, 1)

            # Segmentation (mirror demo_v03.py process_window pattern)
            seg_out = seg_block(wav_t)
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

            # Embedding
            emb_out = emb_block(wav_t, seg_out)
            emb_arr = emb_out.detach().cpu().numpy() if hasattr(emb_out, "detach") else np.array(emb_out)
            if emb_arr.ndim == 3:
                emb_arr = emb_arr[0]
            emb_arr = emb_arr.astype(np.float32)

            # Clustering
            frame_dur = _WINDOW_S / max(n_frames, 1)
            sw = SlidingWindow(duration=frame_dur, step=frame_dur, start=0.0)
            seg_swf = SlidingWindowFeature(seg_ml, sw)
            speaker_map = clusterer.identify(seg_swf, torch.from_numpy(emb_arr))
            local_spks, global_spks = speaker_map.valid_assignments()

            emit_wc = time.perf_counter() - stream_start_wc
            latency = emit_wc - audio_t_end  # positive = behind real-time
            emit_latencies.append(latency)

            n_local = seg_ml.shape[1]
            for l_spk, g_spk in zip(local_spks, global_spks):
                if l_spk >= n_local:
                    continue
                active = np.where(seg_ml[:, l_spk] > 0.5)[0]
                if len(active) == 0:
                    continue
                t_s = session_t + float(active[0]) / n_frames * _WINDOW_S
                t_e = session_t + float(active[-1] + 1) / n_frames * _WINDOW_S
                label = f"auto:{chr(ord('A') + int(g_spk) % 26)}"
                segment_log.append((label, t_s, t_e))
                # Update frame-level state (last-write-wins → no overlap inflation)
                fi_start = int(t_s / _FRAME_RES)
                fi_end = int(t_e / _FRAME_RES) + 1
                for fi in range(fi_start, fi_end):
                    frame_labels[fi] = label

            # DER snapshots at audio time checkpoints
            for t_check in (30.0, 60.0):
                key = f"online_der_at_{int(t_check)}s"
                if key not in der_at and audio_t_end >= t_check:
                    der_at[key] = _compute_online_der(frame_labels, reference, t_check)

            buf_offset += _STEP_SAMPLES * 4
            session_t += _STEP_S

        # Final online DER (entire session) — use frame-level state
        der_at["online_der_at_end"] = _compute_online_der(
            frame_labels, reference, audio_dur
        )

        # Final DER — same frame-level state for consistency
        hyp_final = _frames_to_annotation(frame_labels, audio_dur)
        der_metric = DiarizationErrorRate(collar=0.25)
        try:
            final_der = float(der_metric(reference, hyp_final))
        except Exception:
            final_der = float("nan")

        resource = monitor.stop()

        lats = np.array(emit_latencies)
        return {
            "embedding": emb_name,
            "sample": Path(sample_path).name,
            "mode": "live-streaming",
            "window_s": _WINDOW_S,
            "step_s": _STEP_S,
            "audio_dur_s": round(audio_dur, 1),
            "metrics": {
                "live_emit_latency_p50_s": float(np.percentile(lats, 50)) if len(lats) else float("nan"),
                "live_emit_latency_p95_s": float(np.percentile(lats, 95)) if len(lats) else float("nan"),
                "online_der_at_30s": der_at.get("online_der_at_30s", float("nan")),
                "online_der_at_60s": der_at.get("online_der_at_60s", float("nan")),
                "online_der_at_end": der_at.get("online_der_at_end", float("nan")),
                "final_der": final_der,
                "cpu_peak_pct": resource["cpu_peak_pct"],
                "cpu_avg_pct": resource["cpu_avg_pct"],
                "ram_peak_mb": resource["ram_peak_mb"],
                "ram_avg_mb": resource["ram_avg_mb"],
                "segment_count": len(segment_log),
                "emit_count": len(emit_latencies),
            },
            "error": None,
        }

    except Exception:
        monitor.stop()
        return {
            "embedding": emb_name,
            "sample": Path(sample_path).name,
            "mode": "live-streaming",
            "window_s": _WINDOW_S,
            "step_s": _STEP_S,
            "audio_dur_s": 0.0,
            "metrics": {},
            "error": traceback.format_exc(limit=8),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Model registry
# ─────────────────────────────────────────────────────────────────────────────
_MODEL_REGISTRY: dict[str, type] = {
    "pyannote/embedding": PyannoteEmbedding,
    "ecapa-tdnn": EcapaTdnnEmbedding,
}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Realtime ablation: live streaming metrics")
    # single-run mode
    parser.add_argument("--embedding", default=None,
                        help="Single embedding model name")
    parser.add_argument("--sample", default=None, help="Single WAV file path")
    parser.add_argument("--gt-rttm", default=None, help="Ground truth RTTM file path")
    # batch mode
    parser.add_argument("--embeddings", nargs="+", default=None)
    parser.add_argument("--samples", nargs="+", default=None)
    parser.add_argument("--gt-rttm-dir", default=None,
                        help="Directory with RTTM files matching sample basenames")
    # common
    parser.add_argument("--output", required=True, help="Output directory for JSON results")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        # Try loading from .env in project root
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("HF_TOKEN="):
                    hf_token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    os.environ["HF_TOKEN"] = hf_token
                    break

    if not hf_token:
        print("[realtime_ablation] ERROR: HF_TOKEN not set. Source .env or export HF_TOKEN.")
        sys.exit(1)

    # Build embedding × sample pairs
    if args.embedding and args.sample and args.gt_rttm:
        pairs = [(args.embedding, args.sample, args.gt_rttm)]
    elif args.embeddings and args.samples and args.gt_rttm_dir:
        gt_dir = Path(args.gt_rttm_dir)
        pairs = []
        for emb in args.embeddings:
            for sample in args.samples:
                rttm_path = gt_dir / (Path(sample).stem + ".rttm")
                if not rttm_path.exists():
                    print(f"[realtime_ablation] WARN: RTTM not found: {rttm_path}")
                    continue
                pairs.append((emb, sample, str(rttm_path)))
    else:
        parser.error("Provide either --embedding/--sample/--gt-rttm or "
                     "--embeddings/--samples/--gt-rttm-dir")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_rows: list[dict] = []

    # Group by embedding to load each model once
    emb_names = list(dict.fromkeys(emb for emb, _, _ in pairs))
    for emb_name in emb_names:
        if emb_name not in _MODEL_REGISTRY:
            print(f"[realtime_ablation] ERROR: Unknown embedding '{emb_name}'. "
                  f"Available: {list(_MODEL_REGISTRY)}")
            continue
        print(f"\n[realtime_ablation] Loading model: {emb_name}")
        try:
            model = _MODEL_REGISTRY[emb_name]()
            t_load = time.perf_counter()
            model.load(device=args.device)
            cold_load_s = time.perf_counter() - t_load
            print(f"[realtime_ablation] Model loaded in {cold_load_s:.1f}s")
        except Exception:
            print(f"[realtime_ablation] Model load FAILED:\n{traceback.format_exc(limit=5)}")
            continue

        for emb, sample, rttm in pairs:
            if emb != emb_name:
                continue
            print(f"  [{emb_name}] Measuring: {Path(sample).name}")
            row = run_one(
                emb_name=emb_name,
                our_model=model,
                sample_path=sample,
                gt_rttm_path=rttm,
                hf_token=hf_token,
                device=args.device,
            )
            row["cold_load_s"] = cold_load_s
            row["timestamp"] = datetime.now().isoformat()
            all_rows.append(row)
            if row.get("error"):
                print(f"  ERROR: {row['error'][:200]}")
            else:
                m = row["metrics"]
                print(
                    f"  final_der={m.get('final_der', 'nan'):.3f} "
                    f"latency_p50={m.get('live_emit_latency_p50_s', 'nan'):.2f}s "
                    f"latency_p95={m.get('live_emit_latency_p95_s', 'nan'):.2f}s"
                )

    # Save JSON
    json_path = output_dir / f"v03-realtime-{run_ts}.json"
    json_path.write_text(json.dumps(all_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[realtime_ablation] Saved: {json_path} ({len(all_rows)} rows)")


if __name__ == "__main__":
    main()
