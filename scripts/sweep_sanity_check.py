"""T-024 sweep sanity check — hdbscan_epsilon=0.1 vs 0.5 비교 (T-023f).

실행:
    export HF_TOKEN=<token>
    source .venv-py311/bin/activate
    python scripts/sweep_sanity_check.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

SESSION_DIR = Path(__file__).parent.parent / "tests" / "data" / "ami" / "ES2002a"
SAMPLE_RATE = 16_000
SLICE_SECONDS = 180.0  # shorter slice for speed


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


async def run_eval(hf_token: str, epsilon: float, slice_seconds: float | None) -> dict:
    from speaker_engine.eval.der import TuningConfig, evaluate

    config = TuningConfig(delta_new=1.0, hungarian_threshold=0.5, hdbscan_epsilon=epsilon)
    result = await evaluate(
        config=config,
        session_dir=SESSION_DIR,
        slice_seconds=slice_seconds,
        hf_token=hf_token,
        der_collar=0.25,
        der_skip_overlap=True,
    )
    return {
        "epsilon": epsilon,
        "slice_seconds": slice_seconds,
        "der": result.der,
        "false_alarm": result.false_alarm,
        "miss": result.miss,
        "confusion": result.confusion,
    }


async def main():
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        print("HF_TOKEN 미설정")
        sys.exit(1)

    _patch_hf_hub()
    _patch_audio()

    logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
    logging.getLogger("speechbrain").setLevel(logging.ERROR)
    logging.getLogger("torch").setLevel(logging.ERROR)

    slice_sec = SLICE_SECONDS
    print(f"\n=== T-024 sweep sanity check (slice={slice_sec}s) ===")
    print(f"{'epsilon':>8}  {'DER':>7}  {'FA':>7}  {'Miss':>7}  {'Conf':>7}")
    print("-" * 50)

    results = []
    for epsilon in [0.1, 0.5]:
        r = await run_eval(hf_token, epsilon=epsilon, slice_seconds=slice_sec)
        results.append(r)
        print(
            f"  {epsilon:>6.1f}  {r['der']*100:>6.2f}%  {r['false_alarm']*100:>6.2f}%"
            f"  {r['miss']*100:>6.2f}%  {r['confusion']*100:>6.2f}%"
        )

    der_diff = abs(results[0]["der"] - results[1]["der"])
    conf_diff = abs(results[0]["confusion"] - results[1]["confusion"])
    print(f"\n  DER diff (0.1 vs 0.5)       : {der_diff*100:.2f}%p")
    print(f"  Confusion diff (0.1 vs 0.5) : {conf_diff*100:.2f}%p")

    if der_diff > 0.001:
        print("\n  결론: hdbscan_epsilon 이 DER 에 영향 → T-024 sweep 신뢰 가능")
    else:
        print("\n  결론: hdbscan_epsilon 영향 미미 → sweep 신뢰 낮음, 추가 진단 필요")


if __name__ == "__main__":
    asyncio.run(main())
