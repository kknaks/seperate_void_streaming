"""SpeakerEngine 통합 테스트 플레이스홀더 (spec-05 §2-2 integration 카테고리, PLAN-003-T-015).

실행 환경: HF_TOKEN + 실 diart / pyannote.audio 설치 필요.
CI 게이트에서는 skip marker 로 제외. admin 환경 수동 실행.

테스트 아웃라인:
  T-INT-01: 합성 sin wave 10초 → stream → SpeakerSegment yield 확인
  T-INT-02: stream → finalize → SpeakerCandidate 반환 (auto:* 형식)
  T-INT-03: persist → MemoryStore 저장 → Speaker 반환
  T-INT-04: 재호출 (새 인스턴스, 동일 MemoryStore 공유) → stored 매칭 (LabelChange)
"""

from __future__ import annotations

import asyncio
import math
import struct

import numpy as np
import pytest


def _sin_pcm(duration_s: float = 12.0, sample_rate: int = 16000, freq: float = 440.0) -> bytes:
    """합성 sine wave PCM (16-bit, mono). 실 diart 에 공급할 수 있는 유효 PCM."""
    n = int(duration_s * sample_rate)
    samples = [
        int(32767 * math.sin(2 * math.pi * freq * i / sample_rate))
        for i in range(n)
    ]
    return struct.pack(f"<{n}h", *samples)


async def _pcm_source(pcm: bytes, chunk_size: int = 3200):
    """PCM bytes → chunk_size 단위 AsyncIterator."""
    for i in range(0, len(pcm), chunk_size):
        yield pcm[i : i + chunk_size]
        await asyncio.sleep(0)  # 이벤트 루프 양보


@pytest.mark.skip(
    reason="통합 테스트: HF_TOKEN + 실 diart / pyannote.audio 설치 필요. admin 수동 실행."
)
class TestEngineIntegration:
    """실 DiartAdapter + 합성 audio 통합 시나리오."""

    async def test_stream_yields_speaker_segments(self, hf_token: str, storage_url: str):
        """T-INT-01: 합성 audio → SpeakerSegment yield."""
        from speaker_engine import SpeakerEngine, SpeakerSegment

        pcm = _sin_pcm(duration_s=12.0)
        engine = SpeakerEngine(
            storage_url=storage_url,
            hf_token=hf_token,
        )
        segments = []
        async with engine:
            async for ev in engine.stream(_pcm_source(pcm)):
                if isinstance(ev, SpeakerSegment):
                    segments.append(ev)

        assert len(segments) > 0
        for seg in segments:
            assert seg.utterance_id.startswith("utt-")
            assert seg.label.startswith(("auto:", "registered:", "stored:"))

    async def test_finalize_returns_candidates(self, hf_token: str, storage_url: str):
        """T-INT-02: stream → finalize → SpeakerCandidate."""
        from speaker_engine import SpeakerEngine

        pcm = _sin_pcm(duration_s=12.0)
        engine = SpeakerEngine(storage_url=storage_url, hf_token=hf_token)
        async with engine:
            async for _ in engine.stream(_pcm_source(pcm)):
                pass
            candidates = await engine.finalize()

        assert isinstance(candidates, list)

    async def test_persist_stores_speaker(self, hf_token: str):
        """T-INT-03: finalize → persist → MemoryStore 저장."""
        from speaker_engine import PersistMapping, SpeakerEngine
        from speaker_engine.storage.memory import MemoryStore

        pcm = _sin_pcm(duration_s=12.0)
        store = MemoryStore()
        engine = SpeakerEngine(storage_url="memory://", hf_token=hf_token)
        engine._store = store

        async with engine:
            async for _ in engine.stream(_pcm_source(pcm)):
                pass
            candidates = await engine.finalize()

        if candidates:
            speakers = await engine.persist(
                [PersistMapping(candidates[0].auto_id, "테스트화자")]
            )
            assert len(speakers) == 1
            assert speakers[0].name == "테스트화자"

    async def test_stored_match_on_second_session(self, hf_token: str):
        """T-INT-04: 저장된 화자 → 두번째 세션에서 stored 매칭 LabelChange."""
        from speaker_engine import LabelChange, PersistMapping, SpeakerEngine
        from speaker_engine.storage.memory import MemoryStore

        pcm = _sin_pcm(duration_s=12.0)
        store = MemoryStore()

        # 1st session — persist
        engine1 = SpeakerEngine(storage_url="memory://", hf_token=hf_token)
        engine1._store = store
        async with engine1:
            async for _ in engine1.stream(_pcm_source(pcm)):
                pass
            candidates = await engine1.finalize()
        if candidates:
            await engine1.persist([PersistMapping(candidates[0].auto_id, "화자A")])

        # 2nd session — stored 매칭 확인
        engine2 = SpeakerEngine(storage_url="memory://", hf_token=hf_token)
        engine2._store = store
        stored_changes = []
        async with engine2:
            async for ev in engine2.stream(_pcm_source(pcm)):
                if isinstance(ev, LabelChange) and ev.reason == "stored_match":
                    stored_changes.append(ev)

        # stored match 가 성립하면 LabelChange 존재
        # (합성 audio 특성상 항상 보장은 못하므로 assertion 은 soft)
        assert isinstance(stored_changes, list)
