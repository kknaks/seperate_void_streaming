#!/usr/bin/env python3
"""pyannote-3.1 4 session 전체 측정 — T-024c (file path 방식, T-023e 패턴).

실행:
    source .venv-py311/bin/activate
    nohup python scripts/run_p31_all.py >> /tmp/p31_all.log 2>&1 &
"""
from __future__ import annotations
import json, logging, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("/tmp/p31_all.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("p31_all")

AMI_DIR = Path("tests/data/ami")
RESULTS_JSONL = Path("tests/eval/results.jsonl")
SESSIONS = ["ES2002a", "ES2003a", "ES2008a", "IS1000a"]
HF_TOKEN = os.environ.get("HF_TOKEN", "")


def main() -> None:
    import torchaudio
    from pyannote.audio import Pipeline
    from pyannote.database.util import load_rttm
    from pyannote.metrics.diarization import DiarizationErrorRate

    logger.info("Loading pyannote-3.1 pipeline (file-path approach)...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=HF_TOKEN,
    )
    logger.info("Pipeline loaded")

    for session in SESSIONS:
        wav_path = AMI_DIR / session / "audio.wav"
        rttm_path = AMI_DIR / session / "reference.rttm"
        t0 = time.perf_counter()

        logger.info("Session %s: running pipeline on file path...", session)
        hyp = pipeline(str(wav_path))
        n_spk = len(set(hyp.labels()))
        logger.info("Session %s: %d speakers detected", session, n_spk)

        annotations = load_rttm(str(rttm_path))
        ref = annotations.get(session) or next(iter(annotations.values()))

        info = torchaudio.info(str(wav_path))
        duration = info.num_frames / info.sample_rate

        metric = DiarizationErrorRate(collar=0.25, skip_overlap=True)
        result = metric(ref, hyp, detailed=True)
        total = float(result.get("total", 1.0)) or 1.0

        der = float(result["diarization error rate"])
        fa = float(result.get("false alarm", 0.0)) / total
        miss = float(result.get("missed detection", 0.0)) / total
        conf = float(result.get("confusion", 0.0)) / total
        elapsed = time.perf_counter() - t0

        logger.info(
            "Session %s: DER=%.2f%%  FA=%.2f%%  Miss=%.2f%%  Conf=%.2f%%  elapsed=%.1fs",
            session, der * 100, fa * 100, miss * 100, conf * 100, elapsed,
        )

        row = {
            "pipeline": "pyannote-3.1",
            "session": session,
            "der": der, "false_alarm": fa, "miss": miss, "confusion": conf,
            "duration_seconds": duration, "elapsed_seconds": elapsed,
            "n_speakers_detected": n_spk,
            "note": f"T-024c session={session} pipeline=pyannote-3.1",
        }
        with open(RESULTS_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        logger.info("Session %s: JSONL written", session)
        del hyp

    logger.info("ALL DONE")


if __name__ == "__main__":
    main()
