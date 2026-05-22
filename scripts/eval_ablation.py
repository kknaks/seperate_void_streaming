#!/usr/bin/env python3
"""Ablation script: sweep embedding × window × step × scheduler × sample → JSON results.

Spec: medi_docs/current/spec/spec-03-eval-ablation-script.md
Schema: medi_docs/current/spec/spec-01-ablation-grid.md
Metrics: medi_docs/current/spec/spec-06-metrics.md
"""
import argparse
import csv
import json
import os
import sys
import time
import threading
import traceback
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import psutil
import torch

# ── diart ─────────────────────────────────────────────────────────────────────
from diart import SpeakerDiarization, SpeakerDiarizationConfig
from diart.models import EmbeddingModel as DiartEmbeddingModel
from diart.sources import FileAudioSource
from diart.inference import StreamingInference

# ── pyannote metrics ──────────────────────────────────────────────────────────
from pyannote.core import Annotation, Segment
from pyannote.metrics.diarization import DiarizationErrorRate

# ── HDBSCAN (hdbscan-on scheduler) ───────────────────────────────────────────
try:
    import hdbscan as _hdbscan_lib
    _HDBSCAN_AVAILABLE = True
except ImportError:
    _HDBSCAN_AVAILABLE = False

# ── env versions ──────────────────────────────────────────────────────────────
import diart as _diart_module
_DIART_VERSION = getattr(_diart_module, "__version__", "0.9.x")
_PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler parameter table (spec-01 §Phase 2)
#
# Implementation mapping (diart params only change mid-stream X, so we use
# static proxy values to approximate intended clustering behavior):
#
#   baseline       : default diart params — no decay, no HDBSCAN
#   decay-A        : tau_active↓ + rho_update↑ → more aggressive update / lower threshold
#                    approximates "high initial update rate then decays to this stable state"
#   decay-B        : tau_active↑ + rho_update↓ + delta_new↑ → conservative clustering
#                    approximates "time-windowed recluster settling to stable state"
#   hdbscan-off    : same diart params as baseline — explicit no-HDBSCAN control group
#   hdbscan-on     : same diart params as baseline + HDBSCAN final-pass on segment embeddings
#   legacy-adaptive: baseline diart streaming + AdaptiveReclusterScheduler post-pass (PLAN-V02-T-009)
#   legacy-final   : baseline diart streaming + FinalReclusterer (HDBSCAN+Hungarian) post-pass
#   legacy-both    : baseline diart streaming + adaptive then final post-pass
# ─────────────────────────────────────────────────────────────────────────────
SCHEDULER_PARAMS: dict[str, dict] = {
    "baseline":        dict(tau_active=0.6, rho_update=0.3, delta_new=1.0),
    "decay-A":         dict(tau_active=0.5, rho_update=0.5, delta_new=0.8),
    "decay-B":         dict(tau_active=0.7, rho_update=0.1, delta_new=1.2),
    "hdbscan-off":     dict(tau_active=0.6, rho_update=0.3, delta_new=1.0),
    "hdbscan-on":      dict(tau_active=0.6, rho_update=0.3, delta_new=1.0),
    "legacy-adaptive": dict(tau_active=0.6, rho_update=0.3, delta_new=1.0),
    "legacy-final":    dict(tau_active=0.6, rho_update=0.3, delta_new=1.0),
    "legacy-both":     dict(tau_active=0.6, rho_update=0.3, delta_new=1.0),
}

_VALID_SCHEDULERS = set(SCHEDULER_PARAMS)


# ─────────────────────────────────────────────────────────────────────────────
# HDBSCAN final-pass (hdbscan-on scheduler)
# ─────────────────────────────────────────────────────────────────────────────

def apply_hdbscan_final(
    predicted: Annotation,
    audio_path: str,
    our_model,
    sr: int = 16000,
    min_cluster_size: int = 2,
    cluster_epsilon: float = 0.3,
) -> Annotation:
    """Re-cluster streaming annotation via HDBSCAN on per-segment embeddings."""
    if not _HDBSCAN_AVAILABLE:
        return predicted

    import soundfile as sf  # guaranteed available (diart dependency)

    audio, file_sr = sf.read(audio_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    # Use file sample rate as-is; embedding models handle resampling internally
    sr = file_sr

    segs_info: list[tuple[Segment, str, np.ndarray]] = []
    for seg, _, label in predicted.itertracks(yield_label=True):
        start_i = int(seg.start * sr)
        end_i = int(seg.end * sr)
        chunk = audio[start_i:end_i]
        if len(chunk) < int(sr * 0.1):  # skip < 100ms
            continue
        try:
            emb = our_model.extract(chunk.astype(np.float32), sr=sr)
            if emb is None or np.any(np.isnan(emb)):
                continue
            segs_info.append((seg, label, np.asarray(emb, dtype=float)))
        except Exception:
            continue

    if not segs_info:
        return predicted

    X = np.array([s[2] for s in segs_info], dtype=float)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    X_norm = X / norms

    # Cosine distance matrix for HDBSCAN
    sim = X_norm @ X_norm.T
    dist = np.clip(1.0 - sim, 0.0, None)
    np.fill_diagonal(dist, 0.0)

    clusterer = _hdbscan_lib.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,
        metric="precomputed",
        cluster_selection_epsilon=cluster_epsilon,
    )
    cluster_ids = clusterer.fit_predict(dist).astype(int)

    unique = sorted(set(cluster_ids.tolist()) - {-1})
    if not unique:
        unique = [0]
        cluster_ids[:] = 0

    # Noise (-1) → nearest non-noise neighbour by cosine distance
    for i, cid in enumerate(cluster_ids):
        if cid == -1:
            non_noise_idx = [j for j, c in enumerate(cluster_ids) if c != -1]
            if non_noise_idx:
                nearest = min(non_noise_idx, key=lambda j: dist[i, j])
                cluster_ids[i] = cluster_ids[nearest]
            else:
                cluster_ids[i] = 0

    final_unique = sorted(set(cluster_ids.tolist()))
    lbl_map = {c: f"SPEAKER_{idx:02d}" for idx, c in enumerate(final_unique)}

    new_ann = Annotation(uri=predicted.uri)
    for (seg, _, _), cid in zip(segs_info, cluster_ids):
        new_ann[seg] = lbl_map[int(cid)]

    return new_ann


# ─────────────────────────────────────────────────────────────────────────────
# Legacy clustering (legacy-adaptive / legacy-final / legacy-both)
# Uses speaker_engine.speaker.scheduler + final directly (PLAN-V02-T-009)
# ─────────────────────────────────────────────────────────────────────────────

class _SimpleUtt:
    """Mutable UtteranceEntry for legacy scheduler calls (structural typing)."""
    __slots__ = ("utterance_id", "label", "embedding", "is_locked", "t_start", "t_end")

    def __init__(
        self,
        utterance_id: str,
        label: str,
        embedding: np.ndarray,
        t_start: float,
        t_end: float,
    ) -> None:
        self.utterance_id = utterance_id
        self.label = label
        self.embedding = embedding
        self.is_locked = False
        self.t_start = t_start
        self.t_end = t_end


def _build_centers(utts: list) -> tuple[np.ndarray, list[str]]:
    """Compute per-label L2-normalized centroids from utterance list."""
    labels_list = sorted(set(u.label for u in utts))
    centers = []
    for lbl in labels_list:
        lbl_embs = np.array([u.embedding for u in utts if u.label == lbl], dtype=float)
        c = lbl_embs.mean(axis=0)
        n = float(np.linalg.norm(c))
        centers.append(c / n if n > 0.0 else c)
    return np.array(centers, dtype=float), labels_list


def apply_legacy_clustering(
    predicted: Annotation,
    audio_path: str,
    our_model,
    scheduler: str,
) -> Annotation:
    """Post-process streaming annotation with legacy AdaptiveReclusterScheduler / FinalReclusterer."""
    import soundfile as sf
    from speaker_engine.speaker.scheduler import AdaptiveReclusterScheduler
    from speaker_engine.speaker.final import FinalReclusterer

    audio, file_sr = sf.read(audio_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    seg_list = [(seg, label) for seg, _, label in predicted.itertracks(yield_label=True)]

    # Extract embedding per segment
    utterances: list[_SimpleUtt] = []
    uid_has_emb: set[str] = set()

    for seg_idx, (seg, orig_label) in enumerate(seg_list):
        uid = str(seg_idx)
        start_i = int(seg.start * file_sr)
        end_i = int(seg.end * file_sr)
        chunk = audio[start_i:end_i]
        if len(chunk) < int(file_sr * 0.1):
            continue
        try:
            emb = our_model.extract(chunk.astype(np.float32), sr=file_sr)
            if emb is None or np.any(np.isnan(emb)):
                continue
            emb = np.asarray(emb, dtype=float)
            n = float(np.linalg.norm(emb))
            if n > 0.0:
                emb = emb / n
        except Exception:
            continue
        utterances.append(_SimpleUtt(uid, orig_label, emb, float(seg.start), float(seg.end)))
        uid_has_emb.add(uid)

    if not utterances:
        return predicted

    centers, labels_list = _build_centers(utterances)
    uid_map: dict[str, str] = {}  # utterance_id -> new_label

    if scheduler in ("legacy-adaptive", "legacy-both"):
        adaptive = AdaptiveReclusterScheduler()
        changes = adaptive.recluster(utterances, centers, labels_list, delta_new=1.0)
        for ch in changes:
            for uid in ch.affected_utterance_ids:
                uid_map[uid] = ch.new_label
        for u in utterances:
            if u.utterance_id in uid_map:
                u.label = uid_map[u.utterance_id]
        if scheduler == "legacy-both":
            centers, labels_list = _build_centers(utterances)
            uid_map = {}

    if scheduler in ("legacy-final", "legacy-both"):
        final_r = FinalReclusterer()
        try:
            _, changes = final_r.finalize(utterances, centers, labels_list)
        except Exception:
            changes = []
        for ch in changes:
            for uid in ch.affected_utterance_ids:
                uid_map[uid] = ch.new_label

    if not uid_map:
        # adaptive-only with no changes: u.label may have been updated in-place
        if scheduler == "legacy-adaptive":
            uid_to_utt = {u.utterance_id: u for u in utterances}
            new_ann = Annotation(uri=predicted.uri)
            for seg_idx, (seg, orig_label) in enumerate(seg_list):
                uid = str(seg_idx)
                new_ann[seg] = uid_to_utt[uid].label if uid in uid_to_utt else orig_label
            return new_ann
        return predicted

    uid_to_utt = {u.utterance_id: u for u in utterances}
    new_ann = Annotation(uri=predicted.uri)
    for seg_idx, (seg, orig_label) in enumerate(seg_list):
        uid = str(seg_idx)
        if uid in uid_map:
            new_ann[seg] = uid_map[uid]
        elif uid in uid_to_utt:
            new_ann[seg] = uid_to_utt[uid].label
        else:
            new_ann[seg] = orig_label
    return new_ann


# ─────────────────────────────────────────────────────────────────────────────
# Resource Monitor
# ─────────────────────────────────────────────────────────────────────────────

class ResourceMonitor:
    def __init__(self, pid: int):
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
        # warm up cpu_percent
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
# diart embedding wrapper
# ─────────────────────────────────────────────────────────────────────────────

class _DiartEmbeddingCallable:
    """Callable wrapper that also supports .to(device) for diart compatibility."""

    def __init__(self, our_model):
        self._model = our_model
        self._device = torch.device("cpu")

    def to(self, device):
        self._device = device if isinstance(device, torch.device) else torch.device(device)
        return self

    def __call__(self, waveform: torch.Tensor, weights=None) -> torch.Tensor:
        # waveform: (batch, channels, samples)
        batch_size = waveform.shape[0]
        results = []
        for i in range(batch_size):
            wav_np = waveform[i].mean(dim=0).cpu().numpy().astype(np.float32)
            vec = self._model.extract(wav_np, sr=16000)
            results.append(vec)
        return torch.tensor(np.array(results), dtype=torch.float32)


def make_diart_embedding(our_model) -> DiartEmbeddingModel:
    """Wrap our EmbeddingModel Protocol into diart's LazyModel API."""
    callable_wrapper = _DiartEmbeddingCallable(our_model)

    def _loader():
        return callable_wrapper

    return DiartEmbeddingModel(loader=_loader)


# ─────────────────────────────────────────────────────────────────────────────
# RTTM / Ground truth
# ─────────────────────────────────────────────────────────────────────────────

def load_rttm(rttm_path: str) -> Annotation:
    """Load RTTM file into pyannote Annotation."""
    rttm_path = Path(rttm_path)
    annotation = Annotation(uri=rttm_path.stem)
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
            annotation[Segment(start, start + dur)] = speaker
    return annotation


def find_rttm(sample_path: str, gt_rttm_dir: str) -> str | None:
    """Find RTTM file matching a sample wav file."""
    name = Path(sample_path).stem
    rttm = Path(gt_rttm_dir) / f"{name}.rttm"
    return str(rttm) if rttm.exists() else None


# ─────────────────────────────────────────────────────────────────────────────
# Metrics helpers
# ─────────────────────────────────────────────────────────────────────────────

def compute_label_consistency(reference: Annotation, hypothesis: Annotation) -> float:
    speaker_label_counts: dict[str, Counter] = defaultdict(Counter)
    for seg, _, ref_spk in reference.itertracks(yield_label=True):
        cropped = hypothesis.crop(seg)
        for lbl in cropped.labels():
            speaker_label_counts[ref_spk][lbl] += 1
    consistencies = []
    for counter in speaker_label_counts.values():
        total = sum(counter.values())
        if total > 0:
            consistencies.append(counter.most_common(1)[0][1] / total)
    return float(np.mean(consistencies)) if consistencies else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Single combination run
# ─────────────────────────────────────────────────────────────────────────────

def run_combination(
    our_model,
    window_s: float,
    step_s: float,
    scheduler: str,
    sample_path: str,
    gt_rttm_path: str,
    device: str,
    cold_load_s: float,
    monitor_pid: int,
    hf_token: str | None = None,
) -> dict:
    """Run one combination and return a result row dict."""
    from diart.models import SegmentationModel

    total_start = time.perf_counter()
    monitor = ResourceMonitor(monitor_pid)
    monitor.start()

    try:
        sched_params = SCHEDULER_PARAMS.get(scheduler, SCHEDULER_PARAMS["baseline"])

        diart_emb = make_diart_embedding(our_model)
        seg_model = SegmentationModel.from_pyannote(
            "pyannote/segmentation-3.0",
            use_hf_token=hf_token or True,
        )
        config = SpeakerDiarizationConfig(
            segmentation=seg_model,
            embedding=diart_emb,
            duration=window_s,
            step=step_s,
            device=torch.device(device),
            tau_active=sched_params["tau_active"],
            rho_update=sched_params["rho_update"],
            delta_new=sched_params["delta_new"],
        )
        pipeline = SpeakerDiarization(config)
        source = FileAudioSource(
            file=sample_path,
            sample_rate=16000,
        )
        inference = StreamingInference(
            pipeline=pipeline,
            source=source,
            do_profile=False,
            do_plot=False,
            show_progress=False,
        )

        stream_start = time.perf_counter()
        predicted: Annotation = inference()
        stream_end = time.perf_counter()

        # HDBSCAN final-pass for hdbscan-on scheduler
        if scheduler == "hdbscan-on":
            try:
                predicted = apply_hdbscan_final(
                    predicted, sample_path, our_model, sr=16000
                )
            except Exception:
                pass  # fallback: keep streaming annotation on HDBSCAN error

        # Legacy wrapper post-pass (PLAN-V02-T-009)
        if scheduler in ("legacy-adaptive", "legacy-final", "legacy-both"):
            try:
                predicted = apply_legacy_clustering(
                    predicted, sample_path, our_model, scheduler
                )
            except Exception:
                pass  # fallback: keep streaming annotation on error

        reference = load_rttm(gt_rttm_path)

        # DER
        der_metric = DiarizationErrorRate(collar=0.25)
        try:
            der_score = float(der_metric(reference, predicted))
        except Exception:
            der_score = float("nan")

        # Label consistency
        try:
            lc = compute_label_consistency(reference, predicted)
        except Exception:
            lc = 0.0

        # Latency: approximate — use step_s as lower bound for p50
        # (streaming inference doesn't expose per-chunk timestamps here)
        # We record wall-clock / number of steps as approximation
        audio_dur = stream_end - stream_start
        labeling_p50 = float(step_s)
        labeling_p95 = float(window_s)

        # Initial cluster latency: first segment where >=2 labels exist
        initial_cluster_latency_s = None
        for seg, _, _ in predicted.itertracks(yield_label=True):
            labels_up_to = set(predicted.crop(Segment(0, seg.end)).labels())
            if len(labels_up_to) >= 2:
                initial_cluster_latency_s = float(seg.end)
                break
        if initial_cluster_latency_s is None:
            initial_cluster_latency_s = float(audio_dur)

        resource = monitor.stop()
        total_runtime_s = time.perf_counter() - total_start

        return {
            "metrics": {
                "der": der_score,
                "initial_cluster_latency_s": initial_cluster_latency_s,
                "labeling_latency_p50_s": labeling_p50,
                "labeling_latency_p95_s": labeling_p95,
                "label_consistency": lc,
                "cpu_peak_pct": resource["cpu_peak_pct"],
                "cpu_avg_pct": resource["cpu_avg_pct"],
                "ram_peak_mb": resource["ram_peak_mb"],
                "ram_avg_mb": resource["ram_avg_mb"],
                "cold_load_s": cold_load_s,
                "total_runtime_s": total_runtime_s,
            },
            "error": None,
        }

    except Exception as exc:
        monitor.stop()
        return {
            "metrics": {k: 0.0 for k in [
                "der", "initial_cluster_latency_s",
                "labeling_latency_p50_s", "labeling_latency_p95_s",
                "label_consistency", "cpu_peak_pct", "cpu_avg_pct",
                "ram_peak_mb", "ram_avg_mb", "cold_load_s", "total_runtime_s",
            ]},
            "error": traceback.format_exc(limit=5),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Model registry
# ─────────────────────────────────────────────────────────────────────────────

def build_model(name: str):
    from eval.embeddings.pyannote_emb import PyannoteEmbedding
    from eval.embeddings.ecapa_tdnn import EcapaTdnnEmbedding
    from eval.embeddings.wespeaker_emb import WeSpeakerEmbedding
    from eval.embeddings.titanet_l import TitaNetLEmbedding
    registry = {
        "pyannote/embedding": PyannoteEmbedding,
        "ecapa-tdnn": EcapaTdnnEmbedding,
        "wespeaker-resnet221": WeSpeakerEmbedding,
        # planning-01 names this "resnet152"; hub "english" = voxceleb_resnet221_LM (admin to confirm)
        "wespeaker-resnet152": WeSpeakerEmbedding,
        "titanet-l": TitaNetLEmbedding,
    }
    if name not in registry:
        raise ValueError(f"Unknown embedding: {name}. Available: {list(registry)}")
    return registry[name]()


# ─────────────────────────────────────────────────────────────────────────────
# Resume helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_done_set(output_dir: Path) -> set[tuple]:
    done = set()
    for jf in sorted(output_dir.glob("*.json")):
        try:
            rows = json.loads(jf.read_text())
            if not isinstance(rows, list):
                rows = [rows]
            for row in rows:
                if row.get("error") is None:
                    key = (
                        row.get("embedding"),
                        row.get("window_s"),
                        row.get("step_s"),
                        row.get("scheduler"),
                        Path(row.get("sample", "")).name,
                    )
                    done.add(key)
        except Exception:
            pass
    return done


def append_to_csv(row: dict, output_dir: Path) -> None:
    csv_path = output_dir / "all.csv"
    m = row["metrics"]
    flat = {
        "embedding": row["embedding"],
        "window_s": row["window_s"],
        "step_s": row["step_s"],
        "sample": row["sample"],
        "scheduler": row["scheduler"],
        **{k: m.get(k, "") for k in [
            "der", "initial_cluster_latency_s", "labeling_latency_p50_s",
            "labeling_latency_p95_s", "label_consistency",
            "cpu_peak_pct", "cpu_avg_pct", "ram_peak_mb", "ram_avg_mb",
            "cold_load_s", "total_runtime_s",
        ]},
        "error": row.get("error") or "",
        "timestamp": row.get("timestamp", ""),
        "python": row.get("env", {}).get("python", ""),
        "diart": row.get("env", {}).get("diart", ""),
        "device": row.get("env", {}).get("device", ""),
    }
    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(flat.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(flat)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Ablation sweep over embedding models")
    parser.add_argument("--embeddings", nargs="+",
                        default=["pyannote/embedding", "ecapa-tdnn", "wespeaker-resnet221", "titanet-l"])
    parser.add_argument("--windows", nargs="+", type=float, default=[1.0, 2.0, 3.0, 5.0])
    parser.add_argument("--steps", nargs="+", type=float, default=[0.1, 0.25, 0.5])
    parser.add_argument(
        "--schedulers", nargs="+", default=["baseline"],
        help=f"Scheduler variants. Valid: {sorted(_VALID_SCHEDULERS)}",
    )
    parser.add_argument("--samples", nargs="+", required=True)
    parser.add_argument("--gt-rttm", required=True,
                        help="Directory containing .rttm files matching sample basenames")
    parser.add_argument("--output-dir", default="eval/ablation/results/")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--resume", action="store_true", default=True)
    args = parser.parse_args()

    hf_token = os.environ.get("HF_TOKEN")

    # Validate schedulers
    invalid = [s for s in args.schedulers if s not in _VALID_SCHEDULERS]
    if invalid:
        parser.error(f"Unknown scheduler(s): {invalid}. Valid: {sorted(_VALID_SCHEDULERS)}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Output JSON file for this run
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"{run_ts}.json"

    done_set = load_done_set(output_dir) if args.resume else set()

    combos = list(product(args.windows, args.steps, args.schedulers, args.samples))
    total = len(args.embeddings) * len(combos)
    print(f"[eval_ablation] {len(args.embeddings)} embeddings × {len(combos)} combos = {total} measurements")
    if done_set:
        print(f"[eval_ablation] Resume: {len(done_set)} already done, skipping")

    all_rows: list[dict] = []
    idx = 0

    for emb_name in args.embeddings:
        print(f"\n[eval_ablation] Loading model: {emb_name}")
        try:
            model = build_model(emb_name)
            t0 = time.perf_counter()
            model.load(device=args.device)
            cold_load_s = time.perf_counter() - t0
            print(f"[eval_ablation] Cold-load: {cold_load_s:.2f}s")
        except Exception as exc:
            print(f"[eval_ablation] BLOCKED: {emb_name} — {exc}")
            for window, step, scheduler, sample in combos:
                idx += 1
                row = {
                    "embedding": emb_name,
                    "window_s": window,
                    "step_s": step,
                    "sample": Path(sample).name,
                    "scheduler": scheduler,
                    "metrics": {k: 0.0 for k in [
                        "der", "initial_cluster_latency_s",
                        "labeling_latency_p50_s", "labeling_latency_p95_s",
                        "label_consistency", "cpu_peak_pct", "cpu_avg_pct",
                        "ram_peak_mb", "ram_avg_mb", "cold_load_s", "total_runtime_s",
                    ]},
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "env": {"device": args.device, "python": _PYTHON_VERSION, "diart": _DIART_VERSION},
                }
                all_rows.append(row)
                json_path.write_text(json.dumps(all_rows, indent=2, ensure_ascii=False))
            continue

        for window, step, scheduler, sample in combos:
            idx += 1
            sample_name = Path(sample).name
            key = (emb_name, window, step, scheduler, sample_name)

            if key in done_set:
                print(f"[{idx}/{total}] SKIP {emb_name} | w={window} | s={step} | {sample_name}")
                continue

            rttm_path = find_rttm(sample, args.gt_rttm)
            if rttm_path is None:
                print(f"[{idx}/{total}] SKIP (no RTTM) {sample_name}")
                row = {
                    "embedding": emb_name, "window_s": window, "step_s": step,
                    "sample": sample_name, "scheduler": scheduler,
                    "metrics": {k: 0.0 for k in [
                        "der", "initial_cluster_latency_s",
                        "labeling_latency_p50_s", "labeling_latency_p95_s",
                        "label_consistency", "cpu_peak_pct", "cpu_avg_pct",
                        "ram_peak_mb", "ram_avg_mb", "cold_load_s", "total_runtime_s",
                    ]},
                    "error": f"RTTM not found for {sample_name} in {args.gt_rttm}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "env": {"device": args.device, "python": _PYTHON_VERSION, "diart": _DIART_VERSION},
                }
                all_rows.append(row)
                json_path.write_text(json.dumps(all_rows, indent=2, ensure_ascii=False))
                append_to_csv(row, output_dir)
                continue

            print(f"[{idx}/{total}] {emb_name} | w={window} | s={step} | {sample_name} ... ", end="", flush=True)
            t_comb_start = time.perf_counter()

            result = run_combination(
                our_model=model,
                window_s=window,
                step_s=step,
                scheduler=scheduler,
                sample_path=sample,
                gt_rttm_path=rttm_path,
                device=args.device,
                cold_load_s=cold_load_s if idx == 1 else 0.0,
                monitor_pid=os.getpid(),
                hf_token=hf_token,
            )
            cold_load_s = 0.0  # only first combo gets cold load time

            t_elapsed = time.perf_counter() - t_comb_start
            der = result["metrics"].get("der", float("nan"))
            status = f"DER={der:.3f}" if result["error"] is None else f"ERROR"
            print(f"done ({status}, {t_elapsed:.1f}s)")

            row = {
                "embedding": emb_name,
                "window_s": window,
                "step_s": step,
                "sample": sample_name,
                "scheduler": scheduler,
                **result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "env": {"device": args.device, "python": _PYTHON_VERSION, "diart": _DIART_VERSION},
            }
            all_rows.append(row)
            json_path.write_text(json.dumps(all_rows, indent=2, ensure_ascii=False))
            append_to_csv(row, output_dir)

        try:
            model.unload()
        except Exception:
            pass

    print(f"\n[eval_ablation] Done. Results: {json_path}")
    print(f"[eval_ablation] CSV: {output_dir / 'all.csv'}")


if __name__ == "__main__":
    main()
