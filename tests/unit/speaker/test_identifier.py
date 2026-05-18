"""Identifier 단위 테스트 (spec-05 §2-2 unit 카테고리).

외부 의존 0 — numpy + 합성 embedding (seeded random / hand-crafted 직교, spec-05 §4.1).
SpeakerStore.find_match 는 Mock 으로 격리 (실 DB 0).
MemoryStore 통합 케이스는 클래스 말미에 선택 추가.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import numpy as np
import pytest

from speaker_engine.speaker.identifier import Identifier
from speaker_engine.storage.base import SpeakerMatch
from speaker_engine.types import Speaker


# ---------------------------------------------------------------------------
# 헬퍼 — 직교 unit vector
# ---------------------------------------------------------------------------

def unit(arr: list[float]) -> np.ndarray:
    """list → L2 정규화 ndarray (spec-05 §4.1 hand-crafted 직교)."""
    v = np.array(arr, dtype=float)
    return v / np.linalg.norm(v)


def make_speaker(name: str, origin: str = "stored") -> Speaker:
    return Speaker(
        id=uuid4(),
        name=name,
        origin=origin,  # type: ignore[arg-type]
        embedding_dim=3,
        model_id="pyannote/embedding",
        registered_at=None,
        first_seen=0.0,
        last_seen=0.0,
        utterance_count=1,
    )


def mock_store(match_result: SpeakerMatch | None = None) -> MagicMock:
    """find_match 를 AsyncMock 으로 고정한 SpeakerStore mock."""
    store = MagicMock()
    store.find_match = AsyncMock(return_value=match_result)
    return store


# ---------------------------------------------------------------------------
# §1 normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_unit_vector_unchanged(self):
        """norm=1 벡터 → 자기 자신 (오차 허용)."""
        v = unit([1.0, 0.0, 0.0])
        result = Identifier.normalize(v)
        assert np.allclose(result, v)
        assert abs(np.linalg.norm(result) - 1.0) < 1e-9

    def test_arbitrary_vector_becomes_unit(self):
        """임의 벡터 → norm=1."""
        v = np.array([3.0, 4.0, 0.0])
        result = Identifier.normalize(v)
        assert abs(np.linalg.norm(result) - 1.0) < 1e-9
        assert np.allclose(result, [0.6, 0.8, 0.0])

    def test_zero_vector_raises(self):
        """zero vector → ValueError (spec-04 §4.2)."""
        with pytest.raises(ValueError, match="zero vector"):
            Identifier.normalize(np.zeros(4))

    def test_nan_vector_raises(self):
        """NaN 포함 → ValueError (워커 결정 정책)."""
        v = np.array([1.0, float("nan"), 0.0])
        with pytest.raises(ValueError, match="NaN"):
            Identifier.normalize(v)

    def test_2d_array_raises(self):
        """2-d ndarray → ValueError."""
        v = np.array([[1.0, 0.0], [0.0, 1.0]])
        with pytest.raises(ValueError):
            Identifier.normalize(v)

    def test_preserves_direction(self):
        """정규화 후 방향 보존 — dot product ≈ 1 (단위 벡터끼리)."""
        v = np.array([1.0, 2.0, 3.0])
        normalized = Identifier.normalize(v)
        original_dir = v / np.linalg.norm(v)
        assert np.allclose(normalized, original_dir)


# ---------------------------------------------------------------------------
# §2 3-tier 매칭
# ---------------------------------------------------------------------------

class TestMatchRegistered:
    """Tier 1: registered dict 매칭 — SpeakerStore 호출 없음."""

    def _make_identifier(
        self,
        reg: dict[str, np.ndarray],
        threshold: float = 0.70,
    ) -> tuple[Identifier, MagicMock]:
        store = mock_store(match_result=None)
        ident = Identifier(
            store=store,
            model_id="pyannote/embedding",
            registered_speakers=reg,
            registered_threshold=threshold,
            stored_threshold=0.75,
        )
        return ident, store

    @pytest.mark.asyncio
    async def test_registered_hit_returns_label_and_no_store_call(self):
        """registered 매칭 → "registered:이지영" + find_match 호출 없음."""
        emb_a = unit([1.0, 0.0, 0.0])
        ident, store = self._make_identifier({"이지영": emb_a})

        label, speaker = await ident.match(emb_a.copy())

        assert label == "registered:이지영"
        assert speaker is None
        store.find_match.assert_not_called()

    @pytest.mark.asyncio
    async def test_registered_miss_falls_through_to_stored(self):
        """registered miss → stored 호출."""
        emb_a = unit([1.0, 0.0, 0.0])
        emb_b = unit([0.0, 1.0, 0.0])  # 직교 → cosine=0 < 0.70

        sp = make_speaker("박환자")
        store = mock_store(SpeakerMatch(speaker=sp, cosine_similarity=0.80, origin="stored"))
        ident = Identifier(
            store=store,
            model_id="pyannote/embedding",
            registered_speakers={"이지영": emb_a},
            registered_threshold=0.70,
        )

        label, speaker = await ident.match(emb_b)

        assert label == "stored:박환자"
        assert speaker is sp
        store.find_match.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_registered_threshold_exact_hit(self):
        """cosine 정확히 threshold (>=) → hit."""
        # 두 벡터의 cosine = threshold 가 되도록 설계
        # e1 = [1,0,0], e2 = [cos(theta), sin(theta), 0], cosine = cos(theta)
        theta = np.arccos(0.70)
        emb_reg = unit([1.0, 0.0, 0.0])
        emb_query = np.array([np.cos(theta), np.sin(theta), 0.0])
        emb_query = emb_query / np.linalg.norm(emb_query)

        ident, store = self._make_identifier({"화자A": emb_reg}, threshold=0.70)
        label, _ = await ident.match(emb_query)

        # cosine ≈ 0.70 → hit
        assert label == "registered:화자A"
        store.find_match.assert_not_called()

    @pytest.mark.asyncio
    async def test_registered_threshold_just_below_miss(self):
        """cosine < threshold → miss (registered)."""
        theta = np.arccos(0.69)
        emb_reg = unit([1.0, 0.0, 0.0])
        emb_query = np.array([np.cos(theta), np.sin(theta), 0.0])
        emb_query = emb_query / np.linalg.norm(emb_query)

        ident, store = self._make_identifier({"화자A": emb_reg}, threshold=0.70)
        label, _ = await ident.match(emb_query)

        assert label != "registered:화자A"
        store.find_match.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_threshold_override(self):
        """registered_threshold override 동작 검증."""
        emb_a = unit([1.0, 0.0, 0.0])
        # cosine ≈ 0.5 → 기본 0.70 이면 miss, override 0.40 이면 hit
        theta = np.arccos(0.50)
        emb_query = np.array([np.cos(theta), np.sin(theta), 0.0])
        emb_query = emb_query / np.linalg.norm(emb_query)

        # override 0.40 → hit
        ident_low, store_low = self._make_identifier({"화자A": emb_a}, threshold=0.40)
        label, _ = await ident_low.match(emb_query)
        assert label == "registered:화자A"
        store_low.find_match.assert_not_called()

        # default 0.70 → miss
        ident_hi, store_hi = self._make_identifier({"화자A": emb_a}, threshold=0.70)
        label2, _ = await ident_hi.match(emb_query)
        assert label2 != "registered:화자A"
        store_hi.find_match.assert_awaited_once()


class TestMatchStored:
    """Tier 2: stored 매칭."""

    @pytest.mark.asyncio
    async def test_stored_hit(self):
        """find_match → SpeakerMatch → "stored:<name>"."""
        sp = make_speaker("박환자")
        store = mock_store(SpeakerMatch(speaker=sp, cosine_similarity=0.80, origin="stored"))
        ident = Identifier(store=store, model_id="pyannote/embedding")

        emb = unit([0.0, 1.0, 0.0])
        label, speaker = await ident.match(emb)

        assert label == "stored:박환자"
        assert speaker is sp

    @pytest.mark.asyncio
    async def test_stored_miss_returns_auto_fallback(self):
        """find_match None → ("", None)."""
        store = mock_store(None)
        ident = Identifier(store=store, model_id="pyannote/embedding")
        emb = unit([0.0, 1.0, 0.0])
        label, speaker = await ident.match(emb)
        assert label == ""
        assert speaker is None

    @pytest.mark.asyncio
    async def test_stored_threshold_override(self):
        """stored_threshold 낮추면 더 쉽게 hit."""
        sp = make_speaker("테스트화자")
        store = mock_store(SpeakerMatch(speaker=sp, cosine_similarity=0.76, origin="stored"))
        ident = Identifier(
            store=store,
            model_id="pyannote/embedding",
            stored_threshold=0.75,
        )
        emb = unit([1.0, 0.0, 0.0])
        label, _ = await ident.match(emb)
        assert label == "stored:테스트화자"
        # find_match 에 stored_threshold=0.75 전달 검증
        call_kwargs = store.find_match.call_args.kwargs
        assert call_kwargs["threshold"] == 0.75
        assert call_kwargs["origin"] == "stored"

    @pytest.mark.asyncio
    async def test_model_id_passed_to_find_match(self):
        """find_match 호출 시 model_id 전달 검증 (spec-02 §4-2 격리)."""
        store = mock_store(None)
        ident = Identifier(store=store, model_id="pyannote/embedding")
        emb = unit([1.0, 0.0, 0.0])
        await ident.match(emb)
        call_kwargs = store.find_match.call_args.kwargs
        assert call_kwargs["model_id"] == "pyannote/embedding"


class TestMatchAllTierFallthrough:
    """registered miss + stored miss → ("", None)."""

    @pytest.mark.asyncio
    async def test_all_miss_returns_empty(self):
        emb_a = unit([1.0, 0.0, 0.0])
        emb_b = unit([0.0, 1.0, 0.0])  # 직교

        store = mock_store(None)
        ident = Identifier(
            store=store,
            model_id="pyannote/embedding",
            registered_speakers={"화자A": emb_a},
        )

        label, speaker = await ident.match(emb_b)
        assert label == ""
        assert speaker is None
        store.find_match.assert_awaited_once()


# ---------------------------------------------------------------------------
# §3 registered_speakers 초기화 처리
# ---------------------------------------------------------------------------

class TestRegisteredSpeakersInit:
    def _ident(self, reg: dict[str, np.ndarray] | None) -> Identifier:
        return Identifier(
            store=mock_store()[0] if isinstance(mock_store(), tuple) else mock_store(),
            model_id="pyannote/embedding",
            registered_speakers=reg,
        )

    def _make_ident_with_store(
        self, reg: dict[str, np.ndarray] | None
    ) -> tuple[Identifier, MagicMock]:
        store = mock_store()
        return Identifier(
            store=store,
            model_id="pyannote/embedding",
            registered_speakers=reg,
        ), store

    def test_init_normalizes_registered_embeddings(self):
        """init 시점에 registered embedding 들이 L2 normalize 됨."""
        raw = np.array([3.0, 4.0, 0.0])  # norm=5
        ident, _ = self._make_ident_with_store({"화자": raw})
        stored_emb = ident._registered["화자"]
        assert abs(np.linalg.norm(stored_emb) - 1.0) < 1e-9

    def test_none_registered_no_registered_tier(self):
        """registered_speakers=None → Tier 1 없음, 바로 stored."""
        ident, store = self._make_ident_with_store(None)
        assert ident._registered == {}

    def test_empty_dict_registered_no_registered_tier(self):
        """registered_speakers={} → Tier 1 없음."""
        ident, store = self._make_ident_with_store({})
        assert ident._registered == {}

    @pytest.mark.asyncio
    async def test_none_registered_calls_find_match(self):
        """registered=None 이면 match 시 바로 find_match 호출."""
        store = mock_store(None)
        ident = Identifier(store=store, model_id="pyannote/embedding", registered_speakers=None)
        await ident.match(unit([1.0, 0.0, 0.0]))
        store.find_match.assert_awaited_once()


# ---------------------------------------------------------------------------
# §4 예외 정책
# ---------------------------------------------------------------------------

class TestExceptions:
    @pytest.mark.asyncio
    async def test_match_2d_embedding_raises(self):
        """match 에 2-d ndarray → ValueError."""
        store = mock_store()
        ident = Identifier(store=store, model_id="pyannote/embedding")
        with pytest.raises(ValueError):
            await ident.match(np.ones((2, 3)))

    @pytest.mark.asyncio
    async def test_match_dim_mismatch_with_registered_raises(self):
        """registered dim != query dim → ValueError."""
        reg = {"화자": unit([1.0, 0.0, 0.0])}  # dim=3
        store = mock_store()
        ident = Identifier(store=store, model_id="pyannote/embedding", registered_speakers=reg)
        emb_wrong_dim = unit([1.0, 0.0, 0.0, 0.0])  # dim=4
        with pytest.raises(ValueError, match="dim"):
            await ident.match(emb_wrong_dim)

    def test_normalize_zero_raises(self):
        with pytest.raises(ValueError, match="zero vector"):
            Identifier.normalize(np.zeros(3))

    def test_normalize_nan_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            Identifier.normalize(np.array([1.0, float("nan")]))

    @pytest.mark.asyncio
    async def test_store_exception_propagates(self):
        """SpeakerStore.find_match 예외는 wrap 없이 전파."""
        store = MagicMock()
        store.find_match = AsyncMock(side_effect=RuntimeError("DB error"))
        ident = Identifier(store=store, model_id="pyannote/embedding")
        with pytest.raises(RuntimeError, match="DB error"):
            await ident.match(unit([1.0, 0.0, 0.0]))


# ---------------------------------------------------------------------------
# §5 async match 확인
# ---------------------------------------------------------------------------

class TestAsyncBehavior:
    @pytest.mark.asyncio
    async def test_match_is_coroutine(self):
        """match 가 coroutine (async) 임을 확인 — spec-04 §4.6."""
        import inspect
        store = mock_store()
        ident = Identifier(store=store, model_id="pyannote/embedding")
        coro = ident.match(unit([1.0, 0.0, 0.0]))
        assert inspect.iscoroutine(coro)
        await coro  # consume


# ---------------------------------------------------------------------------
# §6 MemoryStore 통합 (선택) — 실 MemoryStore 로 register/match 흐름 검증
# ---------------------------------------------------------------------------

class TestWithMemoryStore:
    """in-memory 실 MemoryStore 사용 — 외부 DB 0 (spec-05 §2-2 unit 허용)."""

    @pytest.mark.asyncio
    async def test_registered_then_match(self):
        """MemoryStore 에 stored 등록 후 Identifier 가 매칭."""
        from speaker_engine.storage.memory import MemoryStore

        store = MemoryStore()
        await store.init_schema(embedding_dim=3, model_id="pyannote/embedding")

        emb_stored = unit([0.0, 1.0, 0.0])
        sp = await store.save("김의사", emb_stored, "pyannote/embedding")

        ident = Identifier(store=store, model_id="pyannote/embedding")
        label, speaker = await ident.match(emb_stored)

        assert label == "stored:김의사"
        assert speaker is not None
        assert speaker.name == "김의사"

    @pytest.mark.asyncio
    async def test_registered_tier_skips_store_call_with_memorystore(self):
        """registered dict hit 시 MemoryStore.find_match 호출 횟수 0."""
        from unittest.mock import patch

        from speaker_engine.storage.memory import MemoryStore

        store = MemoryStore()
        await store.init_schema(embedding_dim=3, model_id="pyannote/embedding")

        emb = unit([1.0, 0.0, 0.0])
        ident = Identifier(
            store=store,
            model_id="pyannote/embedding",
            registered_speakers={"이지영": emb},
        )

        with patch.object(store, "find_match", wraps=store.find_match) as spy:
            label, _ = await ident.match(emb)

        assert label == "registered:이지영"
        spy.assert_not_called()
