"""Bug-B fix 후 baseline 재측정 + pyannote-3.1 reference 측정 (T-023e).

실행:
    export HF_TOKEN=<token>
    cd /Users/kknaks/git/library/seperate_void_streaming
    python scripts/bugfix_baseline.py
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
logger = logging.getLogger("bugfix_baseline")

SESSION_DIR = Path(__file__).parent.parent / "tests" / "data" / "ami" / "ES2002a"
RESULTS_JSONL = Path(__file__).parent.parent / "tests" / "eval" / "results.jsonl"
SAMPLE_RATE = 16_000
WINDOW_SAMPLES = SAMPLE_RATE * 10


# ---------------------------------------------------------------------------
# huggingface_hub use_auth_token → token 패치 (diart 0.9.2 / hf_hub 0.20+)
# ---------------------------------------------------------------------------

def _patch_hf_hub():
    """hf_hub_download 의 deprecated use_auth_token kwarg → token 으로 변환."""
    import huggingface_hub as _hfh
    from huggingface_hub import hf_hub_download as _orig

    def _compat_download(*args, use_auth_token=None, **kwargs):
        if use_auth_token is not None and "token" not in kwargs:
            kwargs["token"] = use_auth_token
        return _orig(*args, **kwargs)

    _hfh.hf_hub_download = _compat_download
    # pyannote.audio imports hf_hub_download directly; patch there too
    try:
        import pyannote.audio.core.model as _pam
        _pam.hf_hub_download = _compat_download  # type: ignore[attr-defined]
    except Exception:
        pass
    logger.info("hf_hub_download use_auth_token → token 패치 완료")


# ---------------------------------------------------------------------------
# torchaudio → soundfile 패치 (Python 3.14 torchaudio.list_audio_backends 미존재)
# ---------------------------------------------------------------------------

def _patch_audio_loader():
    """der.py 내부 _load_audio_mono16k 를 soundfile fallback 으로 패치."""
    import soundfile as sf

    def _soundfile_load(wav_path: Path, slice_seconds: float | None) -> np.ndarray:
        data, sr = sf.read(str(wav_path), dtype="float32")
        if sr != SAMPLE_RATE:
            raise RuntimeError(f"SR mismatch: {sr} != {SAMPLE_RATE}")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if slice_seconds is not None:
            data = data[: int(slice_seconds * SAMPLE_RATE)]
        return data.astype(np.float32)

    import speaker_engine.eval.der as der_module
    der_module._load_audio_mono16k = _soundfile_load  # type: ignore[attr-defined]
    logger.info("der._load_audio_mono16k → soundfile 패치 완료")


# ---------------------------------------------------------------------------
# 진단 1 — Bug-B fix baseline 재측정 (full session, collar=0.25)
# ---------------------------------------------------------------------------

async def measure_bugfix_baseline(hf_token: str) -> dict:
    from speaker_engine.eval.der import TuningConfig, evaluate

    logger.info("=== Bug-B fix baseline 재측정 (full session) ===")
    config = TuningConfig(delta_new=1.0, hungarian_threshold=0.5, hdbscan_epsilon=0.3)

    result = await evaluate(
        config=config,
        session_dir=SESSION_DIR,
        slice_seconds=None,
        hf_token=hf_token,
        der_collar=0.25,
        der_skip_overlap=True,
    )

    row = {
        "config": {
            "delta_new": result.config.delta_new,
            "hungarian_threshold": result.config.hungarian_threshold,
            "hdbscan_epsilon": result.config.hdbscan_epsilon,
        },
        "der": result.der,
        "false_alarm": result.false_alarm,
        "miss": result.miss,
        "confusion": result.confusion,
        "session": result.session,
        "slice_seconds": result.slice_seconds,
        "duration_seconds": result.duration_seconds,
        "elapsed_seconds": result.elapsed_seconds,
        "der_collar": 0.25,
        "der_skip_overlap": True,
        "note": "T-023e Bug-B fixed baseline",
    }

    logger.info(
        "Bug-B fix baseline — DER=%.2f%% FA=%.2f%% Miss=%.2f%% Confusion=%.2f%%",
        row["der"] * 100,
        row["false_alarm"] * 100,
        row["miss"] * 100,
        row["confusion"] * 100,
    )
    return row


# ---------------------------------------------------------------------------
# 진단 2 — pyannote-3.1 공식 pipeline reference
# ---------------------------------------------------------------------------

def measure_pyannote31(hf_token: str) -> dict | None:
    """pyannote/speaker-diarization-3.1 공식 pipeline 으로 DER 측정."""
    logger.info("=== pyannote-3.1 공식 pipeline reference ===")

    # soundfile 로 직접 로드 (pyannote Pipeline 은 자체 audio loader 사용)
    try:
        import soundfile as sf
        from pyannote.core import Annotation, Segment
        from pyannote.database.util import load_rttm
        from pyannote.metrics.diarization import DiarizationErrorRate
    except ImportError as e:
        logger.warning("pyannote import 실패 — skip: %s", e)
        return None

    wav_path = SESSION_DIR / "audio.wav"
    rttm_path = SESSION_DIR / "reference.rttm"

    # reference 로드
    annotations = load_rttm(str(rttm_path))
    reference = next(iter(annotations.values()))

    # pyannote Pipeline 로드
    try:
        # pyannote.audio Pipeline 은 torchaudio 없이도 동작하는지 확인
        from pyannote.audio import Pipeline as PyannotePipeline
        pipeline = PyannotePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        hypothesis = pipeline(str(wav_path))
    except AttributeError as e:
        logger.warning(
            "pyannote-3.1 SKIP — torchaudio Python 3.14 compat error (OQ-03-2): %s", e
        )
        return None
    except Exception as e:
        logger.warning("pyannote-3.1 SKIP — 로드 실패: %s", e)
        return None

    # DER 측정
    metric = DiarizationErrorRate(collar=0.25, skip_overlap=True)
    result = metric(reference, hypothesis, detailed=True)
    total = float(result.get("total", 1.0)) or 1.0

    row = {
        "pipeline": "pyannote/speaker-diarization-3.1",
        "der": float(result["diarization error rate"]),
        "false_alarm": float(result.get("false alarm", 0.0)) / total,
        "miss": float(result.get("missed detection", 0.0)) / total,
        "confusion": float(result.get("confusion", 0.0)) / total,
        "der_collar": 0.25,
        "der_skip_overlap": True,
        "note": "T-023e pyannote-3.1 official reference",
    }
    logger.info(
        "pyannote-3.1 — DER=%.2f%% FA=%.2f%% Miss=%.2f%% Confusion=%.2f%%",
        row["der"] * 100,
        row["false_alarm"] * 100,
        row["miss"] * 100,
        row["confusion"] * 100,
    )
    return row


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        logger.error("HF_TOKEN 환경변수 미설정")
        sys.exit(1)

    _patch_hf_hub()
    _patch_audio_loader()

    results = []

    # 1. Bug-B fix baseline
    try:
        row = await measure_bugfix_baseline(hf_token)
        results.append(row)
    except Exception as e:
        logger.error("baseline 측정 실패: %s", e, exc_info=True)

    # 2. pyannote-3.1 reference (Python 3.14 compat 이슈로 skip 가능)
    try:
        row31 = measure_pyannote31(hf_token)
        if row31:
            results.append(row31)
    except Exception as e:
        logger.warning("pyannote-3.1 측정 중 예외: %s", e)

    # JSONL append
    RESULTS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_JSONL, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    logger.info("JSONL %d행 append → %s", len(results), RESULTS_JSONL)

    # 비교 표 출력
    print("\n" + "=" * 70)
    print("비교 표 (T-023e)")
    print("=" * 70)
    print(f"{'pipeline':<40} {'DER':>7} {'FA':>7} {'Miss':>7} {'Conf':>7}")
    print("-" * 70)

    prev = [
        ("우리 (Bug-B 미수정, T-023b)", 0.7020, 0.5500, 0.0122, 0.1398),
        ("pyannote-3.0 manual (T-023b)", 0.1974, 0.1393, 0.0220, 0.0362),
    ]
    for name, der, fa, miss, conf in prev:
        print(f"{name:<40} {der*100:>6.2f}% {fa*100:>6.2f}% {miss*100:>6.2f}% {conf*100:>6.2f}%")

    for r in results:
        if "note" in r and "Bug-B fixed" in r.get("note", ""):
            print(
                f"{'우리 (Bug-B 수정, T-023e)':<40}"
                f" {r['der']*100:>6.2f}% {r['false_alarm']*100:>6.2f}%"
                f" {r['miss']*100:>6.2f}% {r['confusion']*100:>6.2f}%"
            )
        elif "pyannote-3.1" in r.get("note", ""):
            print(
                f"{'pyannote-3.1 official (T-023e)':<40}"
                f" {r['der']*100:>6.2f}% {r['false_alarm']*100:>6.2f}%"
                f" {r['miss']*100:>6.2f}% {r['confusion']*100:>6.2f}%"
            )
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
