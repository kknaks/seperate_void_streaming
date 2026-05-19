"""T-024 — 36 조합 grid sweep (delta_new × hungarian_threshold × hdbscan_epsilon).

train/val 분할 방식:
  - train: slice_seconds=300 (0-300s), 모든 36 조합 측정 (빠른 grid search).
    evaluate() API 는 offset 없음 — 0 부터만 지원. 시간 분할 true hold-out 불가.
  - val  : slice_seconds=None (full session), train DER 기준 상위 5 configs.
    best config = min val DER. 동률 시 v1 default (delta_new=1.0, hungarian=0.5, hdbscan=0.3) 우선.
  - 사유: evaluate() API 변경 금지(T-024 제약). 300s ≈ 23.6% of 1272.64s 를 proxy train 으로 사용.

실행:
    cd /Users/kknaks/git/library/seperate_void_streaming
    source .venv-py311/bin/activate
    python scripts/run_grid_sweep.py
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
logging.getLogger("speechbrain").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("pyannote").setLevel(logging.ERROR)

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

SESSION_DIR = Path(__file__).parent.parent / "tests" / "data" / "ami" / "ES2002a"
RESULTS_JSONL = Path(__file__).parent.parent / "tests" / "eval" / "results.jsonl"
SAMPLE_RATE = 16_000
TRAIN_SLICE = 300.0   # 0-300s for grid search (fast proxy)
TOP_N_VAL = 5         # top-N train DER configs → full-session val

GRID: dict[str, list[float]] = {
    "delta_new": [0.4, 0.6, 0.8, 1.0],
    "hungarian_threshold": [0.3, 0.5, 0.7],
    "hdbscan_epsilon": [0.1, 0.3, 0.5],
}

V1_DEFAULT = {"delta_new": 1.0, "hungarian_threshold": 0.5, "hdbscan_epsilon": 0.3}

DER_COLLAR = 0.25
DER_SKIP_OVERLAP = True


# ---------------------------------------------------------------------------
# compatibility patches (diart 0.9.2 + hf_hub 0.20+)
# ---------------------------------------------------------------------------

def _patch_hf_hub() -> None:
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


def _patch_audio() -> None:
    import soundfile as sf

    def _sf_load(
        wav_path: Path,
        slice_seconds: float | None = None,
        slice_start_seconds: float = 0.0,
    ) -> np.ndarray:
        data, sr = sf.read(str(wav_path), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if slice_seconds is not None:
            start = int(slice_start_seconds * SAMPLE_RATE)
            end = start + int(slice_seconds * SAMPLE_RATE)
            data = data[start:end]
        return data.astype(np.float32)

    import speaker_engine.eval.der as der_mod
    der_mod._load_audio_mono16k = _sf_load


# ---------------------------------------------------------------------------
# JSONL append helpers
# ---------------------------------------------------------------------------

def _append_jsonl(path: Path, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _result_to_record(result, note: str) -> dict:
    """DERResult → dict with extra fields matching JSONL schema."""
    from dataclasses import asdict
    d = asdict(result)
    d["der_collar"] = DER_COLLAR
    d["der_skip_overlap"] = DER_SKIP_OVERLAP
    d["note"] = note
    return d


# ---------------------------------------------------------------------------
# grid sweep
# ---------------------------------------------------------------------------

async def run_grid(hf_token: str) -> list[dict]:
    from speaker_engine.eval.der import TuningConfig, evaluate

    combos = list(itertools.product(
        GRID["delta_new"],
        GRID["hungarian_threshold"],
        GRID["hdbscan_epsilon"],
    ))
    assert len(combos) == 36, f"격자 크기 오류: {len(combos)}"

    results: list[dict] = []
    total = len(combos)

    print(f"\n=== T-024 grid sweep ({total} combos × {TRAIN_SLICE:.0f}s slice) ===")
    print(f"{'#':>3}  {'dn':>5}  {'ht':>5}  {'he':>5}  {'train DER':>10}  {'conf':>8}  {'miss':>8}  {'elapsed':>8}")
    print("-" * 70)

    t_sweep_start = time.perf_counter()

    for idx, (dn, ht, he) in enumerate(combos, start=1):
        config = TuningConfig(delta_new=dn, hungarian_threshold=ht, hdbscan_epsilon=he)
        result = await evaluate(
            config=config,
            session_dir=SESSION_DIR,
            slice_seconds=TRAIN_SLICE,
            hf_token=hf_token,
            der_collar=DER_COLLAR,
            der_skip_overlap=DER_SKIP_OVERLAP,
        )
        record = _result_to_record(result, note=f"T-024 grid sweep idx={idx}/{total}")
        _append_jsonl(RESULTS_JSONL, record)
        results.append(record)

        print(
            f"{idx:>3}  {dn:>5.1f}  {ht:>5.1f}  {he:>5.1f}"
            f"  {result.der*100:>9.2f}%  {result.confusion*100:>7.2f}%"
            f"  {result.miss*100:>7.2f}%  {result.elapsed_seconds:>7.1f}s"
        )

    elapsed_sweep = time.perf_counter() - t_sweep_start
    print(f"\n  sweep 완료: {elapsed_sweep:.1f}s ({elapsed_sweep/60:.1f}min)")
    return results


# ---------------------------------------------------------------------------
# val: full-session run for top-N configs
# ---------------------------------------------------------------------------

async def run_val(hf_token: str, train_results: list[dict]) -> list[dict]:
    from speaker_engine.eval.der import TuningConfig, evaluate

    sorted_train = sorted(train_results, key=lambda r: r["der"])
    top_n = sorted_train[:TOP_N_VAL]

    print(f"\n=== full-session val (top-{TOP_N_VAL} by train DER) ===")
    print(f"{'dn':>5}  {'ht':>5}  {'he':>5}  {'val DER':>10}  {'elapsed':>8}")
    print("-" * 50)

    val_results: list[dict] = []
    for r in top_n:
        cfg = r["config"]
        config = TuningConfig(**cfg)
        result = await evaluate(
            config=config,
            session_dir=SESSION_DIR,
            slice_seconds=None,
            hf_token=hf_token,
            der_collar=DER_COLLAR,
            der_skip_overlap=DER_SKIP_OVERLAP,
        )
        record = _result_to_record(
            result,
            note=f"T-024 val full session dn={cfg['delta_new']} ht={cfg['hungarian_threshold']} he={cfg['hdbscan_epsilon']}",
        )
        _append_jsonl(RESULTS_JSONL, record)
        val_results.append(record)

        print(
            f"{cfg['delta_new']:>5.1f}  {cfg['hungarian_threshold']:>5.1f}  {cfg['hdbscan_epsilon']:>5.1f}"
            f"  {result.der*100:>9.2f}%  {result.elapsed_seconds:>7.1f}s"
        )

    return val_results


# ---------------------------------------------------------------------------
# best config full-session 재측정 (이미 val 에서 수행됨 → 재사용)
# ---------------------------------------------------------------------------

def _select_best(val_results: list[dict]) -> dict:
    """val DER 최소값 기준. 동률 시 v1 default 우선."""
    best = None
    for r in val_results:
        if best is None or r["der"] < best["der"]:
            best = r
        elif r["der"] == best["der"]:
            cfg = r["config"]
            if all(cfg[k] == v for k, v in V1_DEFAULT.items()):
                best = r
    assert best is not None
    return best


# ---------------------------------------------------------------------------
# sensitivity analysis
# ---------------------------------------------------------------------------

def _sensitivity(train_results: list[dict]) -> dict[str, dict[str, float]]:
    """각 파라미터의 min/max val DER (= train DER 사용) 범위."""
    sensitivity: dict[str, dict[str, float]] = {}
    for param, values in GRID.items():
        ders_by_val: dict[float, list[float]] = {}
        for r in train_results:
            v = r["config"][param]
            ders_by_val.setdefault(v, []).append(r["der"])
        avg_by_val = {v: sum(ds) / len(ds) for v, ds in ders_by_val.items()}
        sensitivity[param] = {
            "min_avg_der": min(avg_by_val.values()),
            "max_avg_der": max(avg_by_val.values()),
            "range": max(avg_by_val.values()) - min(avg_by_val.values()),
            "avg_by_val": avg_by_val,
        }
    return sensitivity


# ---------------------------------------------------------------------------
# print summary tables
# ---------------------------------------------------------------------------

def _print_summary(train_results: list[dict], val_results: list[dict], best: dict) -> None:
    print("\n\n=== 표 1: best 3 configs (train DER 기준, val DER 포함) ===")
    sorted_train = sorted(train_results, key=lambda r: r["der"])
    val_map = {
        (r["config"]["delta_new"], r["config"]["hungarian_threshold"], r["config"]["hdbscan_epsilon"]): r["der"]
        for r in val_results
    }
    print(f"{'rank':>4}  {'dn':>5}  {'ht':>5}  {'he':>5}  {'train DER':>10}  {'val DER':>10}")
    print("-" * 55)
    for rank, r in enumerate(sorted_train[:3], 1):
        cfg = r["config"]
        key = (cfg["delta_new"], cfg["hungarian_threshold"], cfg["hdbscan_epsilon"])
        val_der = val_map.get(key)
        val_str = f"{val_der*100:>9.2f}%" if val_der is not None else "     N/A"
        print(f"{rank:>4}  {cfg['delta_new']:>5.1f}  {cfg['hungarian_threshold']:>5.1f}  {cfg['hdbscan_epsilon']:>5.1f}"
              f"  {r['der']*100:>9.2f}%  {val_str}")

    print("\n\n=== 표 2: parameter sensitivity (train DER 평균 기준) ===")
    sens = _sensitivity(train_results)
    print(f"{'파라미터':>22}  {'min avg DER':>12}  {'max avg DER':>12}  {'range':>8}")
    print("-" * 65)
    for param, s in sens.items():
        print(f"{param:>22}  {s['min_avg_der']*100:>11.2f}%  {s['max_avg_der']*100:>11.2f}%  {s['range']*100:>7.2f}%p")

    print("\n\n=== 표 3: best config full session ===")
    bc = best["config"]
    print(f"  config: delta_new={bc['delta_new']}, hungarian={bc['hungarian_threshold']}, hdbscan_epsilon={bc['hdbscan_epsilon']}")
    print(f"  DER          : {best['der']*100:.2f}%")
    print(f"  False Alarm  : {best['false_alarm']*100:.2f}%")
    print(f"  Miss         : {best['miss']*100:.2f}%")
    print(f"  Confusion    : {best['confusion']*100:.2f}%")

    print("\n\n=== 표 4: baseline 비교 ===")
    baseline = 0.2089
    pyannote30 = 0.1974
    pyannote31 = 0.1668
    best_der = best["der"]
    print(f"  {'config':<45} {'full session DER':>17}")
    print(f"  {'-'*63}")
    print(f"  {'T-023f default (dn=1.0, ht=0.5, he=0.3)':<45} {baseline*100:>16.2f}%")
    print(f"  {'T-024 best':<45} {best_der*100:>16.2f}%")
    print(f"  {'pyannote-3.0 reference':<45} {pyannote30*100:>16.2f}%")
    print(f"  {'pyannote-3.1 reference':<45} {pyannote31*100:>16.2f}%")

    target = 0.15
    if best_der < target:
        print(f"\n  ✓ 목표 <15% 달성! ({best_der*100:.2f}% < 15%)")
    else:
        gap = best_der - target
        print(f"\n  ✗ 목표 미달성: {best_der*100:.2f}% (목표까지 {gap*100:.2f}%p 남음)")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main() -> None:
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        print("HF_TOKEN 미설정")
        sys.exit(1)

    _patch_hf_hub()
    _patch_audio()

    t_total_start = time.perf_counter()

    # 1. 36 조합 train sweep
    train_results = await run_grid(hf_token)

    # 2. top-N configs full-session val
    val_results = await run_val(hf_token, train_results)

    # 3. best config 선택
    best = _select_best(val_results)
    bc = best["config"]

    # best config full session JSONL append (val 에서 이미 append 됨 — 별도 note로 재기록)
    # spec: "T-024 best config full session" note 필수
    _append_jsonl(RESULTS_JSONL, {**best, "note": "T-024 best config full session"})

    # 4. summary tables
    _print_summary(train_results, val_results, best)

    total_elapsed = time.perf_counter() - t_total_start

    # OBS-T023f-1 해소 여부
    print(f"\n\n=== OBS-T023f-1 해소 여부 ===")
    print(f"  best config delta_new = {bc['delta_new']}")
    if bc["delta_new"] < 1.0:
        print(f"  → delta_new < 1.0: 4화자 추적 개선 가능성 있음 (OBS-T023f-1 부분 해소)")
    else:
        print(f"  → delta_new = 1.0: OBS-T023f-1 미해소 (낮은 delta_new 가 도움 안됨)")

    print(f"\n  총 elapsed: {total_elapsed:.1f}s ({total_elapsed/60:.1f}min)")
    print(f"  JSONL 신규 행: {len(train_results)} (train) + {len(val_results)} (val) + 1 (best) = {len(train_results)+len(val_results)+1}")
    print(f"  seed: {SEED}")


if __name__ == "__main__":
    asyncio.run(main())
