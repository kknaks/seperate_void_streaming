"""V-01 baseline 진단 스크립트 (PLAN-003-T-023b).

진단 1: collar=0.25/skip_overlap=True 표준 옵션으로 재측정
진단 2: pyannote 표준 pipeline 으로 동일 audio 측정 (reference comparison)
진단 3: 60s slice DER 1169% 원인 디버그
진단 4: pyannote/AMI HF dataset 접근 확인

실행:
    export HF_TOKEN=<token>
    cd /Users/kknaks/git/library/seperate_void_streaming
    python scripts/diagnose_baseline.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("diagnose_baseline")

SESSION_DIR = Path(__file__).parent.parent / "tests" / "data" / "ami" / "ES2002a"
RESULTS_JSONL = Path(__file__).parent.parent / "tests" / "eval" / "results.jsonl"
SAMPLE_RATE = 16_000
WINDOW_SAMPLES = SAMPLE_RATE * 10


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def _load_audio_mono16k(wav_path: Path, slice_seconds: float | None = None) -> np.ndarray:
    import torchaudio
    waveform, sr = torchaudio.load(str(wav_path))
    if sr != SAMPLE_RATE:
        resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=SAMPLE_RATE)
        waveform = resampler(waveform)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    waveform = waveform[0]
    if slice_seconds is not None:
        waveform = waveform[: int(slice_seconds * SAMPLE_RATE)]
    return waveform.numpy().astype(np.float32)


def _load_reference(rttm_path: Path, session: str, slice_seconds: float | None = None):
    from pyannote.core import Segment
    from pyannote.database.util import load_rttm
    annotations = load_rttm(str(rttm_path))
    ref = annotations.get(session) or next(iter(annotations.values()))
    if slice_seconds is not None:
        ref = ref.crop(Segment(0.0, slice_seconds))
    return ref


def _measure_der(reference, hypothesis, collar: float = 0.25, skip_overlap: bool = True) -> dict:
    from pyannote.metrics.diarization import DiarizationErrorRate
    metric = DiarizationErrorRate(collar=collar, skip_overlap=skip_overlap)
    result = metric(reference, hypothesis, detailed=True)
    total = float(result.get("total", 1.0)) or 1.0
    return {
        "der": float(result["diarization error rate"]),
        "false_alarm": float(result.get("false alarm", 0.0)) / total,
        "miss": float(result.get("missed detection", 0.0)) / total,
        "confusion": float(result.get("confusion", 0.0)) / total,
        "total": total,
        "collar": collar,
        "skip_overlap": skip_overlap,
    }


# ---------------------------------------------------------------------------
# 진단 1 — collar=0.25/skip_overlap=True 표준 옵션 재측정
# ---------------------------------------------------------------------------

async def diag1_standard_kwargs(hf_token: str) -> dict:
    """진단 1: evaluate() 에 표준 collar/skip_overlap 적용 후 baseline 재측정."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from speaker_engine.eval.der import TuningConfig, evaluate

    logger.info("=== 진단 1: 표준 collar/skip_overlap 재측정 ===")
    config = TuningConfig(delta_new=1.0, hungarian_threshold=0.5, hdbscan_epsilon=0.3)

    result = await evaluate(
        config=config,
        session_dir=SESSION_DIR,
        slice_seconds=None,
        hf_token=hf_token,
        der_collar=0.25,
        der_skip_overlap=True,
    )

    d = {
        "diag": 1,
        "collar": 0.25,
        "skip_overlap": True,
        "der": result.der,
        "false_alarm": result.false_alarm,
        "miss": result.miss,
        "confusion": result.confusion,
        "duration_seconds": result.duration_seconds,
        "elapsed_seconds": result.elapsed_seconds,
    }
    logger.info("진단 1 결과: DER=%.2f%%  FA=%.2f%%  Miss=%.2f%%  Confusion=%.2f%%",
                d["der"] * 100, d["false_alarm"] * 100, d["miss"] * 100, d["confusion"] * 100)

    # JSONL append (표준 옵션 baseline 기록)
    jsonl_row = result.to_jsonl()
    # result.to_jsonl() 에는 collar/skip_overlap 없으므로 별도 기록
    row_with_meta = json.loads(jsonl_row)
    row_with_meta["der_collar"] = 0.25
    row_with_meta["der_skip_overlap"] = True
    row_with_meta["note"] = "T-023b diag1 standard kwargs"
    RESULTS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(row_with_meta, ensure_ascii=False) + "\n")
    logger.info("JSONL 기록 완료: %s", RESULTS_JSONL)

    return d


# ---------------------------------------------------------------------------
# 진단 2 — pyannote 표준 pipeline reference comparison
# ---------------------------------------------------------------------------

def diag2_pyannote_reference(hf_token: str, wav_path: Path, rttm_path: Path, session: str) -> dict:
    """진단 2: pyannote/speaker-diarization-3.1 로 동일 audio 측정."""
    import torch
    import torchaudio
    from pyannote.audio import Pipeline

    logger.info("=== 진단 2: pyannote 표준 pipeline reference 측정 ===")

    # Pipeline 로드
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        logger.info("pyannote/speaker-diarization-3.1 로드 성공")
        model_name = "pyannote/speaker-diarization-3.1"
    except Exception as e:
        logger.warning("speaker-diarization-3.1 로드 실패: %s — 3.0 시도", e)
        try:
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.0",
                use_auth_token=hf_token,
            )
            model_name = "pyannote/speaker-diarization-3.0"
        except Exception as e2:
            return {"diag": 2, "error": str(e2), "model": None}

    # 오디오 로드 (torchaudio → tensor 직접 전달 — audio_path 대신)
    waveform, sr = torchaudio.load(str(wav_path))
    if sr != SAMPLE_RATE:
        resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=SAMPLE_RATE)
        waveform = resampler(waveform)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    logger.info("오디오 로드: shape=%s sr=%d", waveform.shape, SAMPLE_RATE)

    # pipeline 실행 (waveform dict 전달)
    input_dict = {"waveform": waveform, "sample_rate": SAMPLE_RATE}
    try:
        hypothesis = pipeline(input_dict)
        logger.info("pipeline 실행 완료 — %d speakers detected", len(set(hypothesis.labels())))
    except Exception as e:
        return {"diag": 2, "error": str(e), "model": model_name}

    reference = _load_reference(rttm_path, session, slice_seconds=None)

    # 표준 옵션으로 DER 측정
    metrics_std = _measure_der(reference, hypothesis, collar=0.25, skip_overlap=True)
    # harsh 옵션으로도 측정 (T-023 original 비교)
    metrics_harsh = _measure_der(reference, hypothesis, collar=0.0, skip_overlap=False)

    logger.info("진단 2 결과 (표준): DER=%.2f%%  FA=%.2f%%  Miss=%.2f%%  Confusion=%.2f%%",
                metrics_std["der"] * 100, metrics_std["false_alarm"] * 100,
                metrics_std["miss"] * 100, metrics_std["confusion"] * 100)
    logger.info("진단 2 결과 (harsh): DER=%.2f%%  FA=%.2f%%  Miss=%.2f%%  Confusion=%.2f%%",
                metrics_harsh["der"] * 100, metrics_harsh["false_alarm"] * 100,
                metrics_harsh["miss"] * 100, metrics_harsh["confusion"] * 100)

    return {
        "diag": 2,
        "model": model_name,
        "standard": metrics_std,
        "harsh": metrics_harsh,
    }


# ---------------------------------------------------------------------------
# 진단 3 — 60s slice DER 1169% 원인 분석
# ---------------------------------------------------------------------------

def diag3_slice_debug(rttm_path: Path, session: str) -> dict:
    """진단 3: 60s slice DER 1169% 원인 규명."""
    from pyannote.core import Segment
    from pyannote.database.util import load_rttm

    logger.info("=== 진단 3: 60s slice 1169%% 원인 분석 ===")

    annotations = load_rttm(str(rttm_path))
    ref_full = annotations.get(session) or next(iter(annotations.values()))

    results = {}

    for start, end in [(0, 60), (60, 120), (120, 180), (300, 360)]:
        crop = ref_full.crop(Segment(float(start), float(end)))
        duration = crop.get_timeline().duration()
        n_seg = len(crop)
        labels = list(crop.labels())
        results[f"{start}-{end}s"] = {
            "reference_duration": round(duration, 3),
            "n_segments": n_seg,
            "labels": labels,
        }
        logger.info("  ref[%d-%ds]: duration=%.3fs  segments=%d  speakers=%s",
                    start, end, duration, n_seg, labels)

    # 핵심 진단: 0-60s ref duration
    ref_0_60 = results["0-60s"]["reference_duration"]
    if ref_0_60 < 5.0:
        cause = "SILENT_SLICE"
        explanation = (
            f"reference[0-60s].duration={ref_0_60:.3f}s ≈ 0 → "
            "DER 분모(total reference duration)가 거의 0 → FA/total 폭발. "
            "harness 수학 자체는 정상. 60s 가 무음 구간이라 측정 무의미."
        )
    else:
        cause = "OTHER"
        explanation = (
            f"reference[0-60s].duration={ref_0_60:.3f}s — 무음 아님. "
            "audio/annotation 시간축 mismatch 또는 harness 버그 가능성."
        )

    logger.info("진단 3 원인: %s — %s", cause, explanation)

    return {
        "diag": 3,
        "cause": cause,
        "explanation": explanation,
        "slice_reference_durations": results,
    }


# ---------------------------------------------------------------------------
# 진단 4 — pyannote/AMI HF dataset 접근 확인
# ---------------------------------------------------------------------------

def diag4_hf_access(hf_token: str) -> dict:
    """진단 4: pyannote/AMI HF dataset 접근 가능성 분석."""
    from huggingface_hub import HfApi

    logger.info("=== 진단 4: pyannote/AMI HF dataset 접근 확인 ===")

    api = HfApi()
    results: dict = {}

    # 후보 repo 이름들
    candidates = [
        ("pyannote/AMI", "dataset"),
        ("pyannote/AMI-diarization-setup", "dataset"),
        ("pyannote/AMI-diarization-setup", "model"),
        ("diarizers-community/ami", "dataset"),
    ]

    for repo_id, repo_type in candidates:
        key = f"{repo_id}({repo_type})"
        try:
            files = list(api.list_repo_files(repo_id, repo_type=repo_type, token=hf_token))
            results[key] = {"status": "ok", "n_files": len(files), "sample": files[:5]}
            logger.info("  ✓ %s: %d files", key, len(files))
        except Exception as e:
            err_str = str(e)
            if "401" in err_str or "403" in err_str:
                status = "auth_required"
            elif "404" in err_str:
                status = "not_found"
            else:
                status = "error"
            results[key] = {"status": status, "error": err_str[:200]}
            logger.info("  ✗ %s: %s — %s", key, status, err_str[:100])

    # diarizers-community/ami IHM 설명 (접근 성공 시)
    ihm_note = (
        "diarizers-community/ami 는 IHM (Individual Headset Microphone) audio 를 parquet 으로 제공. "
        "pyannote AMI benchmark 는 IHM-mix (IHM channels 의 room-level mixing) 을 사용. "
        "mixing 절차 차이로 FA 특성이 다를 수 있음 — pyannote/AMI 접근 시 재검토 필요."
    )

    logger.info("진단 4 완료. IHM note: %s", ihm_note)

    return {
        "diag": 4,
        "repo_access": results,
        "ihm_note": ihm_note,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main() -> None:
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        logger.error("HF_TOKEN 환경변수 미설정. export HF_TOKEN=<token> 후 재실행.")
        sys.exit(1)

    wav_path = SESSION_DIR / "audio.wav"
    rttm_path = SESSION_DIR / "reference.rttm"
    session = SESSION_DIR.name

    if not wav_path.exists() or not rttm_path.exists():
        logger.error(
            "AMI data 없음: %s\n먼저 실행: python scripts/download_ami.py --session ES2002a",
            SESSION_DIR,
        )
        sys.exit(1)

    logger.info("진단 시작 — session=%s", session)
    all_results: dict = {}

    # 진단 3 (cheapest, no model load)
    d3 = diag3_slice_debug(rttm_path, session)
    all_results["diag3"] = d3

    # 진단 4 (HF access, no model load)
    d4 = diag4_hf_access(hf_token)
    all_results["diag4"] = d4

    # 진단 1 (our pipeline, standard kwargs)
    d1 = await diag1_standard_kwargs(hf_token)
    all_results["diag1"] = d1

    # 진단 2 (pyannote reference pipeline)
    d2 = diag2_pyannote_reference(hf_token, wav_path, rttm_path, session)
    all_results["diag2"] = d2

    # 결과 요약 출력
    print("\n" + "=" * 70)
    print("T-023b 진단 결과 요약")
    print("=" * 70)

    print("\n[진단 1] 표준 kwargs (collar=0.25, skip_overlap=True)")
    if "error" not in d1:
        print(f"  DER={d1['der']*100:.2f}%  FA={d1['false_alarm']*100:.2f}%  "
              f"Miss={d1['miss']*100:.2f}%  Confusion={d1['confusion']*100:.2f}%")
    else:
        print(f"  ERROR: {d1.get('error')}")

    print("\n[진단 2] pyannote 표준 pipeline")
    if "error" not in d2:
        std = d2.get("standard", {})
        print(f"  Model: {d2.get('model')}")
        print(f"  DER(표준)={std.get('der',0)*100:.2f}%  FA={std.get('false_alarm',0)*100:.2f}%  "
              f"Miss={std.get('miss',0)*100:.2f}%  Confusion={std.get('confusion',0)*100:.2f}%")
    else:
        print(f"  ERROR: {d2.get('error')}")

    print("\n[진단 3] 60s slice 1169% 원인")
    print(f"  원인: {d3['cause']}")
    print(f"  {d3['explanation']}")

    print("\n[진단 4] HF dataset 접근")
    for repo, info in d4["repo_access"].items():
        print(f"  {repo}: {info['status']}")

    # 분기 판정
    print("\n" + "=" * 70)
    print("Outcome 분기 판정")
    print("=" * 70)
    d1_der = d1.get("der", 1.0)
    d2_std = d2.get("standard", {}).get("der", 1.0) if "error" not in d2 else 1.0

    if d1_der <= 0.30 and "error" not in d1:
        branch = "(a)"
        reason = f"우리 pipeline 표준 옵션 DER={d1_der*100:.1f}% ≤ 30% → 정상 범위. T-024 진행 가능."
    elif abs(d2_std - d1_der) < 0.20 and d2_std > 0.50:
        branch = "(b)"
        reason = (f"우리({d1_der*100:.1f}%)와 pyannote 표준({d2_std*100:.1f}%) 둘 다 70% 근방 "
                  "→ audio/RTTM 정합 문제. dataset 교체 검토.")
    elif d2_std < 0.35 and d1_der > 0.50:
        branch = "(c)"
        reason = (f"pyannote 표준 DER={d2_std*100:.1f}% vs 우리={d1_der*100:.1f}% "
                  "→ 우리 pipeline 에 실제 버그. T-024 시기 상조.")
    else:
        branch = "AMBIGUOUS"
        reason = (f"명확한 분기 판정 불가: 우리DER={d1_der*100:.1f}%, pyannote DER={d2_std*100:.1f}%. "
                  "추가 분석 필요.")

    print(f"  분기: {branch}")
    print(f"  근거: {reason}")
    print()

    # JSON 전체 저장
    out_path = Path(__file__).parent.parent / "tests" / "eval" / "diag_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    logger.info("전체 진단 결과 저장: %s", out_path)

    # summary dict return for test integration
    return {"branch": branch, "reason": reason, "diag1": d1, "diag2": d2, "diag3": d3, "diag4": d4}


if __name__ == "__main__":
    asyncio.run(main())
