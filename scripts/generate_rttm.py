"""Generate RTTM ground-truth files for Korean evaluation samples.

Usage:
    HF_TOKEN=<token> python scripts/generate_rttm.py

Outputs:
    eval/data/korean/record_1.rttm
    eval/data/korean/record_3.rttm
"""

import os
import time
from pathlib import Path

from pyannote.audio import Pipeline


DATA_DIR = Path("eval/data/korean")
SAMPLES = ["record_1", "record_3"]


def main() -> None:
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise RuntimeError("HF_TOKEN environment variable not set")

    print("Loading pyannote/speaker-diarization-3.1 pipeline …")
    load_start = time.time()
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )
    load_elapsed = time.time() - load_start
    print(f"  pipeline loaded in {load_elapsed:.1f}s")

    for sample_name in SAMPLES:
        wav_path = DATA_DIR / f"{sample_name}.wav"
        rttm_path = DATA_DIR / f"{sample_name}.rttm"

        print(f"\nDiarizing {wav_path} …")
        run_start = time.time()
        diarization = pipeline(str(wav_path))
        run_elapsed = time.time() - run_start

        with open(rttm_path, "w") as f:
            diarization.write_rttm(f)

        speakers = set(label for _, _, label in diarization.itertracks(yield_label=True))
        rttm_lines = rttm_path.read_text().strip().splitlines()

        print(f"  done in {run_elapsed:.1f}s")
        print(f"  speakers detected: {len(speakers)} ({sorted(speakers)})")
        print(f"  RTTM lines: {len(rttm_lines)}")
        print(f"  RTTM written to: {rttm_path}")

        # Print first 5 lines as preview
        for line in rttm_lines[:5]:
            print(f"    {line}")
        if len(rttm_lines) > 5:
            print(f"    … ({len(rttm_lines) - 5} more lines)")


if __name__ == "__main__":
    main()
