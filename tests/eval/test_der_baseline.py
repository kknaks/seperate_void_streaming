"""V-01 DER 베이스라인 측정 — eval marker (spec-05 §3, PLAN-003-T-023).

실행:
    export HF_TOKEN=<token>
    pytest tests/eval/test_der_baseline.py -v -m eval

사전 조건:
    python scripts/download_ami.py --session ES2002a --out tests/data/ami/

결과: tests/eval/results.jsonl 에 JSONL 1줄 append (assert 없음 — 측정만 수행).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.eval

SESSION = "ES2002a"
SESSION_DIR = Path(__file__).parent.parent / "data" / "ami" / SESSION
RESULTS_JSONL = Path(__file__).parent / "results.jsonl"

HF_TOKEN = os.environ.get("HF_TOKEN", "")


@pytest.fixture(scope="module")
def hf_token() -> str:
    if not HF_TOKEN:
        pytest.skip("HF_TOKEN 환경변수 미설정 — eval 테스트 스킵")
    return HF_TOKEN


@pytest.fixture(scope="module")
def session_dir() -> Path:
    if not (SESSION_DIR / "audio.wav").exists():
        pytest.skip(
            f"AMI audio 없음: {SESSION_DIR / 'audio.wav'}\n"
            f"먼저 실행: python scripts/download_ami.py --session {SESSION}"
        )
    if not (SESSION_DIR / "reference.rttm").exists():
        pytest.skip(f"reference.rttm 없음: {SESSION_DIR / 'reference.rttm'}")
    return SESSION_DIR


class TestDERBaseline:
    """spec-05 §3 DER 베이스라인 측정 — 회귀 assert 없음 (v1 spec-05 §3-5)."""

    async def test_baseline_full_session(self, hf_token, session_dir):
        """default config 로 full session DER 측정 + JSONL append."""
        from speaker_engine.eval import DERResult, TuningConfig, evaluate

        baseline_config = TuningConfig(
            delta_new=1.0,           # spec-04 default
            hungarian_threshold=0.5, # FinalReclusterer default
            hdbscan_epsilon=0.3,     # adr-08 default
        )

        result = await evaluate(
            config=baseline_config,
            session_dir=session_dir,
            slice_seconds=None,
            hf_token=hf_token,
        )

        assert isinstance(result, DERResult)
        assert 0.0 <= result.der
        assert result.session == SESSION
        assert result.duration_seconds > 0
        assert result.elapsed_seconds > 0

        # JSONL append
        RESULTS_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with open(RESULTS_JSONL, "a", encoding="utf-8") as f:
            f.write(result.to_jsonl() + "\n")

        # sanity report
        print(f"\n[baseline] DER = {result.der * 100:.2f}%  (session={SESSION}, full)")
        print(f"  false_alarm={result.false_alarm * 100:.2f}%")
        print(f"  miss={result.miss * 100:.2f}%")
        print(f"  confusion={result.confusion * 100:.2f}%")
        print(f"  duration={result.duration_seconds:.1f}s  elapsed={result.elapsed_seconds:.1f}s")

    async def test_baseline_slice_300s(self, hf_token, session_dir):
        """300초 slice 측정 — T-024 sweep cost 추정용."""
        from speaker_engine.eval import DERResult, TuningConfig, evaluate

        baseline_config = TuningConfig(
            delta_new=1.0,
            hungarian_threshold=0.5,
            hdbscan_epsilon=0.3,
        )

        result = await evaluate(
            config=baseline_config,
            session_dir=session_dir,
            slice_seconds=300.0,
            hf_token=hf_token,
        )

        assert isinstance(result, DERResult)
        assert result.slice_seconds == pytest.approx(300.0)

        RESULTS_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with open(RESULTS_JSONL, "a", encoding="utf-8") as f:
            f.write(result.to_jsonl() + "\n")

        print(f"\n[slice300s] DER = {result.der * 100:.2f}%  elapsed={result.elapsed_seconds:.1f}s")
