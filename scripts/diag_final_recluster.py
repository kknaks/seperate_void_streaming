"""BUG-FINAL-1 진단 스크립트 (T-023f).

89 clusters 원인 진단:
  (a) online 라벨 unique 수
  (b) FinalReclusterer 입력 segment 수
  (c) HDBSCAN output cluster 수

실행:
    export HF_TOKEN=<token>
    source .venv-py311/bin/activate
    python scripts/diag_final_recluster.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

import numpy as np

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

SESSION_DIR = Path(__file__).parent.parent / "tests" / "data" / "ami" / "ES2002a"
SAMPLE_RATE = 16_000
WINDOW_SAMPLES = SAMPLE_RATE * 10


# ---------------------------------------------------------------------------
# patches
# ---------------------------------------------------------------------------

def _patch_hf_hub():
    import huggingface_hub as _hfh
    from huggingface_hub import hf_hub_download as _orig
    def _compat(*args, use_auth_token=None, **kw):
        if use_auth_token is not None and "token" not in kw:
            kw["token"] = use_auth_token
        return _orig(*args, **kw)
    _hfh.hf_hub_download = _compat
    try:
        import pyannote.audio.core.model as _pam
        _pam.hf_hub_download = _compat
    except Exception:
        pass


def _patch_audio():
    import soundfile as sf
    def _sf_load(wav_path, slice_seconds=None):
        data, sr = sf.read(str(wav_path), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if slice_seconds is not None:
            data = data[: int(slice_seconds * SAMPLE_RATE)]
        return data.astype(np.float32)
    import speaker_engine.eval.der as der_mod
    der_mod._load_audio_mono16k = _sf_load


# ---------------------------------------------------------------------------
# instrumented HDBSCAN runner
# ---------------------------------------------------------------------------

_hdbscan_results: list[dict] = []

def _patched_run_hdbscan(self, X):
    import hdbscan as _hdb
    sim = X @ X.T
    dist = np.clip(1.0 - sim, 0.0, None)
    np.fill_diagonal(dist, 0.0)
    clusterer = _hdb.HDBSCAN(
        min_cluster_size=self._min_cluster_size,
        min_samples=self._min_samples,
        metric="precomputed",
        cluster_selection_epsilon=self._cluster_selection_epsilon,
        cluster_selection_method=self._cluster_selection_method,
    )
    labels = clusterer.fit_predict(dist).astype(int)
    unique_labels = set(labels.tolist()) - {-1}
    noise_count = int((labels == -1).sum())
    _hdbscan_results.append({
        "input_size": len(X),
        "hdbscan_clusters": len(unique_labels),
        "noise_count": noise_count,
        "min_cluster_size": self._min_cluster_size,
        "epsilon": self._cluster_selection_epsilon,
    })
    return labels


async def run_diagnostic(hf_token: str, slice_seconds: float | None, label: str):
    """evaluate() 흐름을 내부 계측하며 실행."""
    from speaker_engine.eval.der import TuningConfig
    from speaker_engine.speaker.final import FinalReclusterer

    # patch FinalReclusterer._run_hdbscan
    FinalReclusterer._run_hdbscan = _patched_run_hdbscan

    from speaker_engine.diart_adapter import DiartAdapter
    from speaker_engine.speaker.online import OnlineSpeakerClusterer
    from speaker_engine.eval.der import _UtteranceRecord, _load_audio_mono16k, _load_reference, _apply_final_recluster

    import soundfile as sf

    wav_path = SESSION_DIR / "audio.wav"
    rttm_path = SESSION_DIR / "reference.rttm"

    token = hf_token
    config = TuningConfig(delta_new=1.0, hungarian_threshold=0.5, hdbscan_epsilon=0.3)

    # load audio
    waveform = _load_audio_mono16k(wav_path, slice_seconds)

    # build adapter
    clusterer = OnlineSpeakerClusterer(delta_new=config.delta_new)
    adapter = DiartAdapter(hf_token=token, clusterer=clusterer)

    utterances: list[_UtteranceRecord] = []
    n_windows = max(1, int(np.ceil(len(waveform) / WINDOW_SAMPLES)))

    for i in range(n_windows):
        start_sample = i * WINDOW_SAMPLES
        chunk = waveform[start_sample: start_sample + WINDOW_SAMPLES]
        if len(chunk) < WINDOW_SAMPLES:
            chunk = np.pad(chunk, (0, WINDOW_SAMPLES - len(chunk)), mode="constant")
        chunk = chunk.astype(np.float32)
        t_window_start = float(start_sample) / SAMPLE_RATE

        try:
            events = await adapter.process_window(chunk)
        except Exception:
            continue

        for ev in events:
            uid = str(uuid4())
            abs_t_start = t_window_start + ev.t_start
            abs_t_end = t_window_start + ev.t_end
            duration_seconds = float(len(waveform)) / SAMPLE_RATE
            abs_t_end = min(abs_t_end, duration_seconds)
            if abs_t_end <= abs_t_start:
                continue
            label_str = OnlineSpeakerClusterer.idx_to_letter(min(ev.local_speaker_id, 19))
            utterances.append(
                _UtteranceRecord(
                    utterance_id=uid,
                    label=label_str,
                    embedding=ev.embedding,
                    is_locked=False,
                    t_start=abs_t_start,
                    t_end=abs_t_end,
                )
            )

    await adapter.close()

    online_unique = set(u.label for u in utterances)
    auto_utts = [u for u in utterances if not u.is_locked]

    print(f"\n=== {label} ===")
    print(f"  total utterance records  : {len(utterances)}")
    print(f"  online unique labels     : {len(online_unique)}  → {sorted(online_unique)}")
    print(f"  FinalReclusterer input   : {len(auto_utts)} utterances")

    _hdbscan_results.clear()

    # run final recluster (will raise RuntimeError if >20 clusters)
    try:
        _apply_final_recluster(utterances, clusterer, config)
        if _hdbscan_results:
            h = _hdbscan_results[-1]
            print(f"  HDBSCAN input size       : {h['input_size']}")
            print(f"  HDBSCAN clusters (pre-noise-absorb): {h['hdbscan_clusters']}")
            print(f"  HDBSCAN noise count      : {h['noise_count']}")
        print(f"  FinalReclusterer         : OK (≤20 clusters)")
    except RuntimeError as e:
        if _hdbscan_results:
            h = _hdbscan_results[-1]
            print(f"  HDBSCAN input size       : {h['input_size']}")
            print(f"  HDBSCAN clusters (pre-noise-absorb): {h['hdbscan_clusters']}")
            print(f"  HDBSCAN noise count      : {h['noise_count']}")
        print(f"  FinalReclusterer         : FAIL → {e}")

    return utterances, clusterer


async def main():
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        print("HF_TOKEN 미설정")
        sys.exit(1)

    _patch_hf_hub()
    _patch_audio()

    # suppress noisy logs
    logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
    logging.getLogger("speechbrain").setLevel(logging.ERROR)
    logging.getLogger("torch").setLevel(logging.ERROR)

    print("진단 1: 60초 slice")
    utts_60, clust_60 = await run_diagnostic(hf_token, slice_seconds=60.0, label="60s slice")

    print("\n진단 2: 180초 slice")
    utts_180, clust_180 = await run_diagnostic(hf_token, slice_seconds=180.0, label="180s slice")

    print("\n진단 3: full session")
    utts_full, clust_full = await run_diagnostic(hf_token, slice_seconds=None, label="full session")

    # per-window utterance count estimate
    print("\n=== 요약 ===")
    for label, n_utts, n_sec in [
        ("60s", len(utts_60), 60),
        ("180s", len(utts_180), 180),
        ("full", len(utts_full), 1272),
    ]:
        n_windows = n_sec // 10
        per_window = n_utts / max(n_windows, 1)
        print(f"  {label}: {n_utts} utterances / {n_windows} windows = {per_window:.1f} events/window")


if __name__ == "__main__":
    asyncio.run(main())
