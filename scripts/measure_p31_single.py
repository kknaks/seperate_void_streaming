#!/usr/bin/env python3
"""pyannote-3.1 단일 session 측정. measure_multi_session_der.py 의 Step 4 단위 실행용.

사용법:
    python scripts/measure_p31_single.py ES2002a
"""
from __future__ import annotations
import json, logging, os, sys, time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("p31_single")

REPO_ROOT = Path(__file__).parent.parent
AMI_DIR = REPO_ROOT / "tests" / "data" / "ami"
RESULTS_JSONL = REPO_ROOT / "tests" / "eval" / "results.jsonl"
SAMPLE_RATE = 16_000


def main(session: str) -> None:
    import torchaudio
    from pyannote.audio import Pipeline
    from pyannote.database.util import load_rttm
    from pyannote.metrics.diarization import DiarizationErrorRate

    hf_token = os.environ.get("HF_TOKEN", "")
    session_dir = AMI_DIR / session
    wav_path = session_dir / "audio.wav"
    rttm_path = session_dir / "reference.rttm"

    logger.info("[pyannote-3.1] %s 측정 시작...", session)
    t0 = time.perf_counter()

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )
    logger.info("[pyannote-3.1] pipeline 로드 완료 (device=cpu)")

    waveform, sr = torchaudio.load(str(wav_path))
    if sr != SAMPLE_RATE:
        from torchaudio.transforms import Resample
        waveform = Resample(orig_freq=sr, new_freq=SAMPLE_RATE)(waveform)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    duration = float(waveform.shape[1]) / SAMPLE_RATE
    logger.info("[pyannote-3.1] audio loaded: %.1fs", duration)

    hypothesis = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE})
    n_speakers = len(set(hypothesis.labels()))
    logger.info("[pyannote-3.1] diarization done: %d speakers", n_speakers)

    annotations = load_rttm(str(rttm_path))
    reference = annotations.get(session) or next(iter(annotations.values()))

    metric = DiarizationErrorRate(collar=0.25, skip_overlap=True)
    result = metric(reference, hypothesis, detailed=True)
    total = float(result.get("total", 1.0)) or 1.0

    der = float(result["diarization error rate"])
    fa = float(result.get("false alarm", 0.0)) / total
    miss = float(result.get("missed detection", 0.0)) / total
    confusion = float(result.get("confusion", 0.0)) / total
    elapsed = time.perf_counter() - t0

    logger.info("[pyannote-3.1] %s DER=%.2f%%  FA=%.2f%%  Miss=%.2f%%  Conf=%.2f%%  (%.1fs)",
                session, der*100, fa*100, miss*100, confusion*100, elapsed)

    row = {
        "pipeline": "pyannote-3.1",
        "session": session,
        "der": der, "false_alarm": fa, "miss": miss, "confusion": confusion,
        "duration_seconds": duration, "elapsed_seconds": elapsed,
        "n_speakers_detected": n_speakers,
        "note": f"T-024c session={session} pipeline=pyannote-3.1",
    }

    RESULTS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    logger.info("JSONL append 완료")

    print(f"\nRESULT: session={session} DER={der*100:.2f}% FA={fa*100:.2f}% Miss={miss*100:.2f}% Confusion={confusion*100:.2f}% elapsed={elapsed:.1f}s")


if __name__ == "__main__":
    session = sys.argv[1] if len(sys.argv) > 1 else "ES2002a"
    main(session)
