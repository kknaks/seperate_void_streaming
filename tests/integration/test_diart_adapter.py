"""integration tests — speaker_engine.diart_adapter (PLAN-003-T-013, spec-05 §2-2).

실 diart 모델 호출 — HF_TOKEN 환경변수 필수.
실행: pytest tests/integration/test_diart_adapter.py -v -m integration

CI 게이트: HF cache 액션으로 다운로드 시간 절감.
관리자 환경에서 1회 실행 권장.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

pytestmark = pytest.mark.integration

HF_TOKEN = os.environ.get("HF_TOKEN", "")


@pytest.fixture(scope="module")
def hf_token() -> str:
    if not HF_TOKEN:
        pytest.skip("HF_TOKEN 환경변수 미설정 — integration 테스트 스킵")
    return HF_TOKEN


@pytest.fixture(scope="module")
def adapter(hf_token: str):
    from speaker_engine.diart_adapter import DiartAdapter
    from speaker_engine.speaker.online import OnlineSpeakerClusterer

    clusterer = OnlineSpeakerClusterer()  # E-03 DI 패턴 (spec-04 §2-2)
    a = DiartAdapter(hf_token=hf_token, clusterer=clusterer)
    yield a
    import asyncio

    asyncio.run(a.close())


def _sin_wave(duration: float = 10.0, freq: float = 440.0, sr: int = 16_000) -> np.ndarray:
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * 0.3).astype(np.float32)


class TestDiartAdapterIntegration:
    async def test_sin_wave_returns_list(self, adapter):
        """합성 sin wave 10초 → process_window 가 list 반환."""
        waveform = _sin_wave()
        result = await adapter.process_window(waveform)
        assert isinstance(result, list)

    async def test_embedding_l2_normalized(self, adapter):
        """실 모델 출력 embedding L2 norm ≈ 1.0 (spec-03 §4-5)."""
        waveform = _sin_wave()
        result = await adapter.process_window(waveform)
        for event in result:
            norm = float(np.linalg.norm(event.embedding))
            assert norm == pytest.approx(1.0, abs=1e-4), f"norm={norm}"

    async def test_embedding_dim_dynamic(self, adapter):
        """embedding_dim 이 모델별 동적 — 0 이 아닌 양수 (reference-07)."""
        dim = adapter.embedding_dim
        assert dim > 0
        assert dim in (256, 512), f"예상 256 또는 512, 실제: {dim}"

    async def test_event_fields_valid(self, adapter):
        """반환 이벤트 필드 타입·범위 검증."""
        from speaker_engine.diart_adapter import RawSpeakerEvent

        waveform = _sin_wave()
        result = await adapter.process_window(waveform)
        for event in result:
            assert isinstance(event, RawSpeakerEvent)
            assert 0 <= event.local_speaker_id < 20
            assert 0.0 <= event.confidence <= 1.0
            assert event.t_start < event.t_end
            assert isinstance(event.audio, bytes)
            assert len(event.audio) > 0
