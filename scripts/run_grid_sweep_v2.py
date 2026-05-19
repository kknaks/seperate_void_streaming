"""T-024b — speech-dense 60-360s slice 로 36 조합 re-sweep + hungarian_threshold trace.

진단 A:
  train = 60-360s (speech-dense, T-023d 확인 4화자 active)
  val   = 360-660s (300s hold-out, disjoint)
  full  = best 1개 full session (generalization)
진단 B:
  final.py Hungarian 매칭 DEBUG 로그 활성화 → cost_min/max/mean 수집
  → B-가/나/다 가설 ranking

실행:
    cd /Users/kknaks/git/library/seperate_void_streaming
    source .venv-py311/bin/activate
    python scripts/run_grid_sweep_v2.py
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

# --- logging 설정: final.py DEBUG 활성화 (진단 B) ---
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("speaker_engine.speaker.final").setLevel(logging.DEBUG)
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

# T-024b slice 설정
TRAIN_SLICE_START = 60.0     # speech-dense 시작 (T-023d: 0-50s 는 silence 4.99s)
TRAIN_SLICE_LENGTH = 300.0   # 60-360s
VAL_SLICE_START = 360.0      # hold-out 시작
VAL_SLICE_LENGTH = 300.0     # 360-660s
TOP_N_VAL = 5                # train DER 상위 N config → val

GRID: dict[str, list[float]] = {
    "delta_new": [0.4, 0.6, 0.8, 1.0],
    "hungarian_threshold": [0.3, 0.5, 0.7],
    "hdbscan_epsilon": [0.1, 0.3, 0.5],
}

V1_DEFAULT = {"delta_new": 1.0, "hungarian_threshold": 0.5, "hdbscan_epsilon": 0.3}
T024_BEST = {"delta_new": 1.0, "hungarian_threshold": 0.5, "hdbscan_epsilon": 0.5}

DER_COLLAR = 0.25
DER_SKIP_OVERLAP = True

# 진단 B: Hungarian cost 수집용
_hungarian_cost_log: list[dict] = []


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


def _patch_final_log_capture() -> None:
    """final.py DEBUG 로그를 _hungarian_cost_log 리스트에도 캡처."""
    import logging as _logging

    class _HungarianCaptureHandler(_logging.Handler):
        def emit(self, record: _logging.LogRecord) -> None:
            msg = record.getMessage()
            if "FinalReclusterer Hungarian" not in msg:
                return
            _hungarian_cost_log.append({"msg": msg, "levelname": record.levelname})

    _logging.getLogger("speaker_engine.speaker.final").addHandler(_HungarianCaptureHandler())


# ---------------------------------------------------------------------------
# JSONL append helpers
# ---------------------------------------------------------------------------

def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _result_to_record(result, note: str) -> dict:
    from dataclasses import asdict
    d = asdict(result)
    d["der_collar"] = DER_COLLAR
    d["der_skip_overlap"] = DER_SKIP_OVERLAP
    d["note"] = note
    return d


# ---------------------------------------------------------------------------
# grid sweep — train (60-360s)
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

    print(
        f"\n=== T-024b grid sweep ({total} combos × train {TRAIN_SLICE_START:.0f}-"
        f"{TRAIN_SLICE_START + TRAIN_SLICE_LENGTH:.0f}s) ==="
    )
    print(f"{'#':>3}  {'dn':>5}  {'ht':>5}  {'he':>5}  {'train DER':>10}  {'conf':>8}  {'miss':>8}  {'elapsed':>8}")
    print("-" * 70)

    t_sweep_start = time.perf_counter()

    for idx, (dn, ht, he) in enumerate(combos, start=1):
        config = TuningConfig(delta_new=dn, hungarian_threshold=ht, hdbscan_epsilon=he)
        result = await evaluate(
            config=config,
            session_dir=SESSION_DIR,
            slice_seconds=TRAIN_SLICE_LENGTH,
            slice_start_seconds=TRAIN_SLICE_START,
            hf_token=hf_token,
            der_collar=DER_COLLAR,
            der_skip_overlap=DER_SKIP_OVERLAP,
        )
        record = _result_to_record(
            result,
            note=f"T-024b train {TRAIN_SLICE_START:.0f}-{TRAIN_SLICE_START+TRAIN_SLICE_LENGTH:.0f}s idx={idx}/{total}",
        )
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
# val — 360-660s (top-N by train DER)
# ---------------------------------------------------------------------------

async def run_val(hf_token: str, train_results: list[dict]) -> list[dict]:
    from speaker_engine.eval.der import TuningConfig, evaluate

    sorted_train = sorted(train_results, key=lambda r: r["der"])
    top_n = sorted_train[:TOP_N_VAL]

    print(f"\n=== val {VAL_SLICE_START:.0f}-{VAL_SLICE_START+VAL_SLICE_LENGTH:.0f}s (top-{TOP_N_VAL} by train DER) ===")
    print(f"{'dn':>5}  {'ht':>5}  {'he':>5}  {'val DER':>10}  {'elapsed':>8}")
    print("-" * 50)

    val_results: list[dict] = []
    for r in top_n:
        cfg = r["config"]
        config = TuningConfig(**cfg)
        result = await evaluate(
            config=config,
            session_dir=SESSION_DIR,
            slice_seconds=VAL_SLICE_LENGTH,
            slice_start_seconds=VAL_SLICE_START,
            hf_token=hf_token,
            der_collar=DER_COLLAR,
            der_skip_overlap=DER_SKIP_OVERLAP,
        )
        record = _result_to_record(
            result,
            note=(
                f"T-024b val {VAL_SLICE_START:.0f}-{VAL_SLICE_START+VAL_SLICE_LENGTH:.0f}s "
                f"dn={cfg['delta_new']} ht={cfg['hungarian_threshold']} he={cfg['hdbscan_epsilon']}"
            ),
        )
        _append_jsonl(RESULTS_JSONL, record)
        val_results.append(record)

        print(
            f"{cfg['delta_new']:>5.1f}  {cfg['hungarian_threshold']:>5.1f}  {cfg['hdbscan_epsilon']:>5.1f}"
            f"  {result.der*100:>9.2f}%  {result.elapsed_seconds:>7.1f}s"
        )

    return val_results


# ---------------------------------------------------------------------------
# best config full session (generalization)
# ---------------------------------------------------------------------------

def _select_best(val_results: list[dict]) -> dict:
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


async def run_best_full(hf_token: str, best: dict) -> dict:
    from speaker_engine.eval.der import TuningConfig, evaluate

    cfg = best["config"]
    config = TuningConfig(**cfg)
    print(f"\n=== best config full session (dn={cfg['delta_new']} ht={cfg['hungarian_threshold']} he={cfg['hdbscan_epsilon']}) ===")

    result = await evaluate(
        config=config,
        session_dir=SESSION_DIR,
        slice_seconds=None,
        slice_start_seconds=0.0,
        hf_token=hf_token,
        der_collar=DER_COLLAR,
        der_skip_overlap=DER_SKIP_OVERLAP,
    )
    record = _result_to_record(result, note="T-024b best config full session")
    _append_jsonl(RESULTS_JSONL, record)

    print(f"  DER = {result.der*100:.2f}%  FA={result.false_alarm*100:.2f}%  miss={result.miss*100:.2f}%  conf={result.confusion*100:.2f}%")
    print(f"  elapsed = {result.elapsed_seconds:.1f}s")
    return record


# ---------------------------------------------------------------------------
# sensitivity analysis
# ---------------------------------------------------------------------------

def _sensitivity(train_results: list[dict]) -> dict[str, dict]:
    sensitivity: dict[str, dict] = {}
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

def _print_summary(
    train_results: list[dict],
    val_results: list[dict],
    best: dict,
    best_full: dict,
) -> None:
    T024_BEST_DER = 0.2089

    print("\n\n=== 표 0: T-024b vs T-024 비교 ===")
    print(f"  {'측정':<30}  {'train slice':<15}  {'val slice':<15}  {'best DER':>10}")
    print(f"  {'-'*75}")
    print(f"  {'T-024 (original)':<30}  {'0-300s':<15}  {'full 1272s':<15}  {T024_BEST_DER*100:>9.2f}%")
    bc = best["config"]
    print(
        f"  {'T-024b train best':<30}  "
        f"{TRAIN_SLICE_START:.0f}-{TRAIN_SLICE_START+TRAIN_SLICE_LENGTH:.0f}s{'':<9}  "
        f"{VAL_SLICE_START:.0f}-{VAL_SLICE_START+VAL_SLICE_LENGTH:.0f}s{'':<9}  "
        f"{best['der']*100:>9.2f}%"
    )
    print(f"  {'T-024b best full session':<30}  {'—':<15}  {'full 1272s':<15}  {best_full['der']*100:>9.2f}%")

    print("\n\n=== 표 1: best 3 train configs ===")
    sorted_train = sorted(train_results, key=lambda r: r["der"])
    val_map = {
        (r["config"]["delta_new"], r["config"]["hungarian_threshold"], r["config"]["hdbscan_epsilon"]): r["der"]
        for r in val_results
    }
    print(f"{'rank':>4}  {'dn':>5}  {'ht':>5}  {'he':>5}  {'train DER':>10}  {'val DER':>10}")
    print("-" * 55)
    for rank, r in enumerate(sorted_train[:5], 1):
        cfg = r["config"]
        key = (cfg["delta_new"], cfg["hungarian_threshold"], cfg["hdbscan_epsilon"])
        val_der = val_map.get(key)
        val_str = f"{val_der*100:>9.2f}%" if val_der is not None else "     N/A"
        print(
            f"{rank:>4}  {cfg['delta_new']:>5.1f}  {cfg['hungarian_threshold']:>5.1f}  {cfg['hdbscan_epsilon']:>5.1f}"
            f"  {r['der']*100:>9.2f}%  {val_str}"
        )

    print("\n\n=== 표 2: parameter sensitivity (train DER 평균) ===")
    sens = _sensitivity(train_results)
    print(f"{'파라미터':>22}  {'min avg DER':>12}  {'max avg DER':>12}  {'range':>8}")
    print("-" * 65)
    for param, s in sens.items():
        print(
            f"{param:>22}  {s['min_avg_der']*100:>11.2f}%"
            f"  {s['max_avg_der']*100:>11.2f}%  {s['range']*100:>7.2f}%p"
        )

    print("\n\n=== 표 3: best config full session ===")
    print(
        f"  config: delta_new={bc['delta_new']}, hungarian={bc['hungarian_threshold']}, "
        f"hdbscan_epsilon={bc['hdbscan_epsilon']}"
    )
    print(f"  DER        : {best_full['der']*100:.2f}%")
    print(f"  False Alarm: {best_full['false_alarm']*100:.2f}%")
    print(f"  Miss       : {best_full['miss']*100:.2f}%")
    print(f"  Confusion  : {best_full['confusion']*100:.2f}%")

    print("\n\n=== 표 4: baseline 비교 ===")
    best_der = best_full["der"]
    rows = [
        ("T-023f default (dn=1.0, ht=0.5, he=0.3)", T024_BEST_DER),
        ("T-024 best (dn=1.0, ht=0.5, he=0.5) full", T024_BEST_DER),
        (f"T-024b best full session", best_der),
        ("pyannote-3.0 reference", 0.1974),
        ("pyannote-3.1 reference", 0.1668),
    ]
    for label, val in rows:
        print(f"  {label:<50} {val*100:>8.2f}%")

    target = 0.15
    if best_der < target:
        print(f"\n  ✓ 목표 <15% 달성! ({best_der*100:.2f}% < 15%)")
    else:
        gap = best_der - target
        print(f"\n  ✗ 목표 미달성: {best_der*100:.2f}% (목표까지 {gap*100:.2f}%p 남음)")

    # T-024 ranking 안정성
    print("\n\n=== ranking 안정성 분석 ===")
    t024_best_key = (T024_BEST["delta_new"], T024_BEST["hungarian_threshold"], T024_BEST["hdbscan_epsilon"])
    found_rank = None
    for rank, r in enumerate(sorted_train, 1):
        cfg = r["config"]
        key = (cfg["delta_new"], cfg["hungarian_threshold"], cfg["hdbscan_epsilon"])
        if key == t024_best_key:
            found_rank = rank
            break
    if found_rank is not None:
        print(f"  T-024 best (dn=1.0, ht=0.5, he=0.5) T-024b train rank: #{found_rank}")
    else:
        print("  T-024 best config not in T-024b train results")

    # hungarian_threshold sensitivity in T-024b
    ht_range = sens["hungarian_threshold"]["range"]
    print(f"\n  hungarian_threshold range (T-024b): {ht_range*100:.4f}%p  (T-024: 0.0000%p)")
    if ht_range == 0.0:
        print("  → T-024b 에서도 hungarian_threshold 영향 없음 — B-다 가설 강화")
    else:
        print(f"  → T-024b 에서 hungarian_threshold 가 {ht_range*100:.4f}%p 영향 — B-다 가설 약화")


def _print_hungarian_trace() -> None:
    """진단 B: Hungarian cost 로그 요약 출력."""
    print("\n\n=== 진단 B: Hungarian cost trace ===")
    if not _hungarian_cost_log:
        print("  (로그 없음 — final.py DEBUG 레벨 미활성화 또는 matched=0)")
        return

    mins, maxs, means = [], [], []
    for entry in _hungarian_cost_log:
        msg = entry["msg"]
        try:
            cost_min = float(msg.split("cost_min=")[1].split()[0])
            cost_max = float(msg.split("cost_max=")[1].split()[0])
            cost_mean = float(msg.split("cost_mean=")[1].split()[0])
            mins.append(cost_min)
            maxs.append(cost_max)
            means.append(cost_mean)
        except (IndexError, ValueError):
            pass

    if not mins:
        print("  (cost 파싱 실패)")
        return

    print(f"  총 Hungarian 매칭 실행 횟수: {len(mins)}")
    print(f"  cost_min  — 전체 min={min(mins):.4f}  max={max(mins):.4f}  mean={sum(mins)/len(mins):.4f}")
    print(f"  cost_max  — 전체 min={min(maxs):.4f}  max={max(maxs):.4f}  mean={sum(maxs)/len(maxs):.4f}")
    print(f"  cost_mean — 전체 min={min(means):.4f}  max={max(means):.4f}  mean={sum(means)/len(means):.4f}")

    global_max_cost = max(maxs)
    if global_max_cost <= 0.3:
        print(f"\n  결론: 모든 matched pair cost <= {global_max_cost:.4f} < 0.3")
        print("  → hungarian_threshold 0.3/0.5/0.7 모두 동일하게 수락")
        print("  → 가설 B-다 (cost structure 상 threshold 무의미) 확정")
    elif global_max_cost <= 0.5:
        print(f"\n  결론: cost_max = {global_max_cost:.4f} (0.3 ~ 0.5 사이)")
        print("  → threshold=0.3 에서 일부 거부, 0.5/0.7 에서 수락 — 그러나 DER 차이 없음")
        print("  → 가설 B-다 (threshold 범위 내 cost 분포 — DER 에 영향 없는 매칭 변동)")
    else:
        print(f"\n  결론: cost_max = {global_max_cost:.4f} > 0.5")
        print("  → 일부 pair 가 높은 cost — threshold 에 따라 매칭 결과 달라질 수 있음")
        print("  → 가설 재검토 필요")


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
    _patch_final_log_capture()

    t_total_start = time.perf_counter()

    # 1. 36 조합 train sweep (60-360s)
    train_results = await run_grid(hf_token)

    # 2. top-N val (360-660s)
    val_results = await run_val(hf_token, train_results)

    # 3. best config 선택 (by val DER)
    best = _select_best(val_results)

    # 4. best config full session
    best_full = await run_best_full(hf_token, best)

    # 5. summary tables
    _print_summary(train_results, val_results, best, best_full)

    # 6. 진단 B
    _print_hungarian_trace()

    total_elapsed = time.perf_counter() - t_total_start
    print(f"\n  총 elapsed: {total_elapsed:.1f}s ({total_elapsed/60:.1f}min)")
    print(
        f"  JSONL 신규 행: {len(train_results)} (train) + {len(val_results)} (val) + 1 (best_full)"
        f" = {len(train_results)+len(val_results)+1}"
    )
    print(f"  seed: {SEED}")


if __name__ == "__main__":
    asyncio.run(main())
