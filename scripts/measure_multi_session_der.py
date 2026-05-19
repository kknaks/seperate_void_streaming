#!/usr/bin/env python3
"""PLAN-003-T-024c — AMI multi-session DER 측정 스크립트.

우리 pipeline default config vs pyannote-3.1 official × 4 AMI sessions.

사용법:
    export HF_TOKEN=<token>
    cd /Users/kknaks/git/library/seperate_void_streaming
    source .venv-py311/bin/activate
    python scripts/measure_multi_session_der.py

산출물:
    tests/eval/results.jsonl  — JSONL append (T-024c note)
    stdout                    — 결과 표 + corpus average + outcome 분기
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("measure_multi_session")

REPO_ROOT = Path(__file__).parent.parent
SESSIONS = ["ES2002a", "ES2003a", "ES2008a", "IS1000a"]
AMI_DIR = REPO_ROOT / "tests" / "data" / "ami"
RESULTS_JSONL = REPO_ROOT / "tests" / "eval" / "results.jsonl"
SAMPLE_RATE = 16_000

# T-023f default — spec-04 default 박제
DEFAULT_CONFIG = {"delta_new": 1.0, "hungarian_threshold": 0.5, "hdbscan_epsilon": 0.3}


# ---------------------------------------------------------------------------
# Step 1: download sessions
# ---------------------------------------------------------------------------

def download_session(session: str, hf_token: str) -> bool:
    session_dir = AMI_DIR / session
    if (session_dir / "audio.wav").exists() and (session_dir / "reference.rttm").exists():
        logger.info("[download] 이미 존재 — 스킵: %s", session_dir)
        return True

    logger.info("[download] %s 다운로드 시작...", session)
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "download_ami.py"),
        "--session", session,
        "--out", str(AMI_DIR),
    ]
    env = os.environ.copy()
    env["HF_TOKEN"] = hf_token
    result = subprocess.run(cmd, env=env, capture_output=False, text=True)
    if result.returncode != 0:
        logger.error("[download] %s 다운로드 실패 (returncode=%d)", session, result.returncode)
        return False
    return (session_dir / "audio.wav").exists()


# ---------------------------------------------------------------------------
# Step 2: our pipeline measurement
# ---------------------------------------------------------------------------

async def measure_ours(session: str, hf_token: str) -> dict:
    from speaker_engine.eval.der import TuningConfig, evaluate

    config = TuningConfig(
        delta_new=DEFAULT_CONFIG["delta_new"],
        hungarian_threshold=DEFAULT_CONFIG["hungarian_threshold"],
        hdbscan_epsilon=DEFAULT_CONFIG["hdbscan_epsilon"],
    )
    session_dir = AMI_DIR / session
    logger.info("[ours] %s 측정 시작 (full session)...", session)
    t0 = time.perf_counter()
    try:
        result = await evaluate(
            config,
            session_dir,
            slice_seconds=None,
            der_collar=0.25,
            der_skip_overlap=True,
            hf_token=hf_token,
        )
        elapsed = time.perf_counter() - t0
        logger.info("[ours] %s DER=%.2f%%  (elapsed=%.1fs)", session, result.der * 100, elapsed)
        row = json.loads(result.to_jsonl())
        row["note"] = f"T-024c session={session} pipeline=ours"
        return {"ok": True, "der": result.der, "fa": result.false_alarm,
                "miss": result.miss, "confusion": result.confusion,
                "duration": result.duration_seconds, "row": row}
    except Exception as exc:
        logger.error("[ours] %s 측정 실패: %s", session, exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Step 3: pyannote-3.1 measurement
# ---------------------------------------------------------------------------

def measure_pyannote31(session: str, pipeline) -> dict:
    import torchaudio
    from pyannote.database.util import load_rttm
    from pyannote.metrics.diarization import DiarizationErrorRate

    session_dir = AMI_DIR / session
    wav_path = session_dir / "audio.wav"
    rttm_path = session_dir / "reference.rttm"

    logger.info("[pyannote-3.1] %s 측정 시작...", session)
    t0 = time.perf_counter()

    waveform, sr = torchaudio.load(str(wav_path))
    if sr != SAMPLE_RATE:
        resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=SAMPLE_RATE)
        waveform = resampler(waveform)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    input_dict = {"waveform": waveform, "sample_rate": SAMPLE_RATE}
    hypothesis = pipeline(input_dict)

    # load reference
    annotations = load_rttm(str(rttm_path))
    if session in annotations:
        reference = annotations[session]
    else:
        reference = next(iter(annotations.values()))

    duration = float(waveform.shape[1]) / SAMPLE_RATE
    metric = DiarizationErrorRate(collar=0.25, skip_overlap=True)
    result = metric(reference, hypothesis, detailed=True)
    total = float(result.get("total", 1.0)) or 1.0

    der = float(result["diarization error rate"])
    fa = float(result.get("false alarm", 0.0)) / total
    miss = float(result.get("missed detection", 0.0)) / total
    confusion = float(result.get("confusion", 0.0)) / total
    elapsed = time.perf_counter() - t0

    logger.info("[pyannote-3.1] %s DER=%.2f%%  (elapsed=%.1fs)", session, der * 100, elapsed)

    n_speakers = len(set(hypothesis.labels()))
    row = {
        "pipeline": "pyannote-3.1",
        "session": session,
        "der": der,
        "false_alarm": fa,
        "miss": miss,
        "confusion": confusion,
        "duration_seconds": duration,
        "elapsed_seconds": elapsed,
        "n_speakers_detected": n_speakers,
        "note": f"T-024c session={session} pipeline=pyannote-3.1",
    }
    return {"ok": True, "der": der, "fa": fa, "miss": miss, "confusion": confusion,
            "duration": duration, "row": row}


# ---------------------------------------------------------------------------
# Step 4: session metadata
# ---------------------------------------------------------------------------

def session_meta(session: str) -> dict:
    rttm_path = AMI_DIR / session / "reference.rttm"
    wav_path = AMI_DIR / session / "audio.wav"
    if not rttm_path.exists():
        return {"segments": 0, "speakers": set(), "duration": 0.0}

    speakers: set[str] = set()
    segments = 0
    with open(rttm_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 8:
                speakers.add(parts[7])
                segments += 1

    duration = 0.0
    if wav_path.exists():
        import torchaudio
        info = torchaudio.info(str(wav_path))
        duration = info.num_frames / info.sample_rate

    return {"segments": segments, "speakers": speakers, "duration": duration}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main() -> None:
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        logger.error("HF_TOKEN 환경변수 미설정")
        sys.exit(1)

    # --- Step 1: download missing sessions ---
    print("\n" + "=" * 70)
    print("Step 1: AMI session 다운로드")
    print("=" * 70)
    downloaded_sessions = []
    for session in SESSIONS:
        ok = download_session(session, hf_token)
        if ok:
            downloaded_sessions.append(session)
        else:
            logger.warning("[main] %s 다운로드 실패 — 이 session 측정 스킵", session)

    if not downloaded_sessions:
        logger.error("모든 session 다운로드 실패")
        sys.exit(1)

    # --- Step 2: metadata ---
    print("\n" + "=" * 70)
    print("Step 2: session 메타데이터")
    print("=" * 70)
    metas = {}
    for session in downloaded_sessions:
        m = session_meta(session)
        metas[session] = m
        print(f"  {session}: duration={m['duration']:.1f}s  speakers={len(m['speakers'])}  "
              f"segments={m['segments']}  speaker_ids={sorted(m['speakers'])}")

    # --- Step 3: our pipeline ---
    print("\n" + "=" * 70)
    print("Step 3: 우리 pipeline 측정 (delta_new=1.0, ht=0.5, eps=0.3)")
    print("=" * 70)
    ours_results: dict[str, dict] = {}
    for session in downloaded_sessions:
        r = await measure_ours(session, hf_token)
        ours_results[session] = r

    # --- Step 4: pyannote-3.1 (load once, measure all) ---
    print("\n" + "=" * 70)
    print("Step 4: pyannote-3.1 공식 pipeline 측정")
    print("=" * 70)
    from pyannote.audio import Pipeline as PyannnotePipeline
    logger.info("[pyannote-3.1] pipeline 로드 중 (1회)...")
    p31_pipeline = PyannnotePipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )
    logger.info("[pyannote-3.1] pipeline 로드 완료")

    # --- Step 5-a: ours JSONL append (already have results) ---
    RESULTS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_JSONL, "a", encoding="utf-8") as f:
        for session in downloaded_sessions:
            if ours_results[session].get("ok"):
                f.write(json.dumps(ours_results[session]["row"], ensure_ascii=False) + "\n")
    logger.info("우리 pipeline JSONL append 완료")

    pyannote_results: dict[str, dict] = {}
    for session in downloaded_sessions:
        try:
            r = measure_pyannote31(session, p31_pipeline)
            pyannote_results[session] = r
            # 즉시 append — 하나씩 쓰면 중간 crash 시에도 보존
            if r.get("ok"):
                with open(RESULTS_JSONL, "a", encoding="utf-8") as f:
                    f.write(json.dumps(r["row"], ensure_ascii=False) + "\n")
                logger.info("[pyannote-3.1] %s JSONL append 완료", session)
        except Exception as exc:
            logger.error("[pyannote-3.1] %s 실패: %s", session, exc)
            pyannote_results[session] = {"ok": False, "error": str(exc)}

    logger.info("JSONL append 완료: %s", RESULTS_JSONL)

    # --- Step 6: 결과 표 출력 ---
    print("\n" + "=" * 70)
    print("결과 표 (collar=0.25, skip_overlap=True, full session)")
    print("=" * 70)
    print(f"{'session':<12} {'duration':>9} {'화자':>4} {'우리 DER':>10} {'p3.1 DER':>10} {'격차':>8}")
    print("-" * 60)

    ours_ders = []
    p31_ders = []
    for session in downloaded_sessions:
        m = metas[session]
        dur_str = f"{m['duration']:.1f}s"
        n_spk = len(m["speakers"])

        ours = ours_results[session]
        p31 = pyannote_results[session]

        ours_str = f"{ours['der']*100:.2f}%" if ours.get("ok") else "ERROR"
        p31_str = f"{p31['der']*100:.2f}%" if p31.get("ok") else "ERROR"

        if ours.get("ok"):
            ours_ders.append(ours["der"])
        if p31.get("ok"):
            p31_ders.append(p31["der"])

        gap = ""
        if ours.get("ok") and p31.get("ok"):
            gap_val = (ours["der"] - p31["der"]) * 100
            gap = f"{gap_val:+.2f}%p"

        print(f"{session:<12} {dur_str:>9} {n_spk:>4} {ours_str:>10} {p31_str:>10} {gap:>8}")

    if ours_ders or p31_ders:
        print("-" * 60)
        ours_avg_str = f"{np.mean(ours_ders)*100:.2f}%" if ours_ders else "N/A"
        ours_std_str = f"±{np.std(ours_ders)*100:.2f}%" if len(ours_ders) > 1 else ""
        p31_avg_str = f"{np.mean(p31_ders)*100:.2f}%" if p31_ders else "N/A"
        p31_std_str = f"±{np.std(p31_ders)*100:.2f}%" if len(p31_ders) > 1 else ""
        print(f"{'corpus avg':<12} {'':>9} {'':>4} {ours_avg_str+ours_std_str:>10} {p31_avg_str+p31_std_str:>10}")

    # --- Step 7: outcome 분기 ---
    print("\n" + "=" * 70)
    print("Outcome 분기 판정")
    print("=" * 70)

    ours_avg = float(np.mean(ours_ders)) if ours_ders else 1.0
    p31_avg = float(np.mean(p31_ders)) if p31_ders else 1.0
    SLA = 0.15

    if ours_avg <= SLA:
        branch = "δ"
        msg = (f"우리 corpus-avg {ours_avg*100:.2f}% ≤ SLA {SLA*100:.0f}% → SLA 통과! "
               "T-025 발주 가능. ES2002a 가 outlier.")
    elif ours_avg <= 0.19 and p31_avg <= SLA:
        branch = "ε"
        msg = (f"우리 corpus-avg {ours_avg*100:.2f}% (16-19%) + pyannote-3.1 avg {p31_avg*100:.2f}% ≤ {SLA*100:.0f}% "
               "→ pyannote-3.1 wrap 전환으로 SLA 달성 가능. wrap task 발주.")
    elif ours_avg <= 0.21 and p31_avg <= 0.18:
        branch = "ζ"
        msg = (f"우리 corpus-avg {ours_avg*100:.2f}% (20-21%) + pyannote-3.1 avg {p31_avg*100:.2f}% "
               "→ 단순 wrap 전환 부족. Bug-A fix + multi-session sweep 병행.")
    else:
        branch = "η"
        msg = (f"우리 corpus-avg {ours_avg*100:.2f}% + pyannote-3.1 avg {p31_avg*100:.2f}% 모두 ≥ 18% "
               "→ SLA 재협상 / customer SLA 정의 확인 우선.")

    print(f"  분기: ({branch})")
    print(f"  근거: {msg}")
    print()

    # variance analysis
    if len(ours_ders) > 1:
        ours_std = float(np.std(ours_ders)) * 100
        es2002a_der = ours_results.get("ES2002a", {}).get("der", 0.0)
        outlier_z = (es2002a_der - np.mean(ours_ders)) / (np.std(ours_ders) + 1e-9)
        print(f"  ES2002a outlier 판정: DER={es2002a_der*100:.2f}%  z={outlier_z:.2f}  "
              f"(|z|>1.5면 outlier 가능성)")
        print(f"  corpus stddev: 우리={ours_std:.2f}%p")

    print()
    print("측정 완료.")


if __name__ == "__main__":
    asyncio.run(main())
