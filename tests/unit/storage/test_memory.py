"""MemoryStore 단위 테스트 — spec-05 §2-2 unit 카테고리."""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import numpy as np
import pytest
import pytest_asyncio

from speaker_engine.exceptions import IntegrityError
from speaker_engine.storage import MemoryStore, SpeakerStore
from speaker_engine.storage.base import SpeakerMatch


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------

DIM = 4
MODEL = "pyannote/embedding"
MODEL_ALT = "wespeaker/community-1"

RNG = np.random.default_rng(42)


def _rand_emb(dim: int = DIM, seed: int | None = None) -> np.ndarray:
    """seeded random unit vector. spec-05 §4.1."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _ortho_embs(n: int, dim: int = DIM) -> list[np.ndarray]:
    """hand-crafted 직교 단위 벡터 n개 (dim >= n 필요). spec-05 §4.1."""
    assert dim >= n
    vecs = []
    for i in range(n):
        v = np.zeros(dim, dtype=np.float32)
        v[i] = 1.0
        vecs.append(v)
    return vecs


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
async def init_store() -> MemoryStore:
    s = MemoryStore()
    await s.init_schema(embedding_dim=DIM, model_id=MODEL)
    return s


# ---------------------------------------------------------------------------
# init_schema
# ---------------------------------------------------------------------------

class TestInitSchema:
    @pytest.mark.asyncio
    async def test_embedding_dim_stored(self, store: MemoryStore) -> None:
        await store.init_schema(embedding_dim=DIM, model_id=MODEL)
        assert store._embedding_dim == DIM
        assert store._model_id == MODEL

    @pytest.mark.asyncio
    async def test_init_schema_idempotent(self, store: MemoryStore) -> None:
        await store.init_schema(embedding_dim=DIM, model_id=MODEL)
        await store.init_schema(embedding_dim=DIM, model_id=MODEL)
        assert store._embedding_dim == DIM


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

class TestRegister:
    @pytest.mark.asyncio
    async def test_register_returns_speaker(self, init_store: MemoryStore) -> None:
        emb = _rand_emb(seed=1)
        sp = await init_store.register("alice", emb, MODEL)
        assert sp.name == "alice"
        assert sp.origin == "registered"
        assert sp.model_id == MODEL
        assert sp.utterance_count == 1

    @pytest.mark.asyncio
    async def test_register_find_match_immediate_hit(self, init_store: MemoryStore) -> None:
        emb = _rand_emb(seed=2)
        sp = await init_store.register("bob", emb, MODEL)
        match = await init_store.find_match(emb, MODEL, threshold=0.9)
        assert match is not None
        assert match.speaker.id == sp.id
        assert match.origin == "registered"

    @pytest.mark.asyncio
    async def test_register_upsert_same_name_model(self, init_store: MemoryStore) -> None:
        emb1 = _rand_emb(seed=3)
        emb2 = _rand_emb(seed=4)
        sp1 = await init_store.register("carol", emb1, MODEL)
        sp2 = await init_store.register("carol", emb2, MODEL)
        assert sp1.id == sp2.id
        assert sp2.utterance_count == 2
        # centroid 은 2 embedding 의 평균 → norm 검증은 별도 테스트

    @pytest.mark.asyncio
    async def test_register_dim_mismatch_raises(self, init_store: MemoryStore) -> None:
        bad_emb = np.ones(DIM + 1, dtype=np.float32)
        bad_emb /= np.linalg.norm(bad_emb)
        with pytest.raises(ValueError):
            await init_store.register("dave", bad_emb, MODEL)


# ---------------------------------------------------------------------------
# save + anon_NNN
# ---------------------------------------------------------------------------

class TestSave:
    @pytest.mark.asyncio
    async def test_save_named(self, init_store: MemoryStore) -> None:
        emb = _rand_emb(seed=10)
        sp = await init_store.save("eve", emb, MODEL)
        assert sp.name == "eve"
        assert sp.origin == "stored"
        assert sp.registered_at is None

    @pytest.mark.asyncio
    async def test_save_anon_first(self, init_store: MemoryStore) -> None:
        emb = _rand_emb(seed=11)
        sp = await init_store.save(None, emb, MODEL)
        assert sp.name == "anon_001"

    @pytest.mark.asyncio
    async def test_save_anon_counter_monotone(self, init_store: MemoryStore) -> None:
        sp1 = await init_store.save(None, _rand_emb(seed=12), MODEL)
        sp2 = await init_store.save(None, _rand_emb(seed=13), MODEL)
        assert sp1.name == "anon_001"
        assert sp2.name == "anon_002"

    @pytest.mark.asyncio
    async def test_save_dim_mismatch_raises(self, init_store: MemoryStore) -> None:
        bad = np.ones(DIM + 2, dtype=np.float32)
        bad /= np.linalg.norm(bad)
        with pytest.raises(ValueError):
            await init_store.save(None, bad, MODEL)


# ---------------------------------------------------------------------------
# find_match — origin 우선순위 + model_id 격리
# ---------------------------------------------------------------------------

class TestFindMatch:
    @pytest.mark.asyncio
    async def test_origin_any_prefers_registered(self, init_store: MemoryStore) -> None:
        """registered hit 시 stored 를 확인하지 않음 — spec-02 §4-1 mermaid."""
        vecs = _ortho_embs(2, DIM)
        query = vecs[0]

        await init_store.register("reg_alice", query.copy(), MODEL)
        await init_store.save("stored_bob", vecs[1].copy(), MODEL)

        match = await init_store.find_match(query, MODEL, threshold=0.9, origin="any")
        assert match is not None
        assert match.origin == "registered"
        assert match.speaker.name == "reg_alice"

    @pytest.mark.asyncio
    async def test_origin_any_falls_through_to_stored(self, init_store: MemoryStore) -> None:
        vecs = _ortho_embs(2, DIM)
        query = vecs[1]

        # registered: vecs[0] (직교 → cosine 0 → miss)
        await init_store.register("reg_alice", vecs[0].copy(), MODEL)
        # stored: vecs[1] (동일 → hit)
        await init_store.save("stored_bob", vecs[1].copy(), MODEL)

        match = await init_store.find_match(query, MODEL, threshold=0.9, origin="any")
        assert match is not None
        assert match.origin == "stored"
        assert match.speaker.name == "stored_bob"

    @pytest.mark.asyncio
    async def test_origin_registered_only(self, init_store: MemoryStore) -> None:
        vecs = _ortho_embs(2, DIM)
        await init_store.register("r", vecs[0].copy(), MODEL)
        await init_store.save("s", vecs[1].copy(), MODEL)

        match = await init_store.find_match(vecs[1], MODEL, threshold=0.5, origin="registered")
        assert match is None  # stored 는 검색 안 함

    @pytest.mark.asyncio
    async def test_origin_stored_only(self, init_store: MemoryStore) -> None:
        vecs = _ortho_embs(2, DIM)
        await init_store.register("r", vecs[0].copy(), MODEL)
        await init_store.save("s", vecs[1].copy(), MODEL)

        match = await init_store.find_match(vecs[0], MODEL, threshold=0.5, origin="stored")
        assert match is None  # registered 는 검색 안 함

    @pytest.mark.asyncio
    async def test_model_id_isolation(self, init_store: MemoryStore) -> None:
        query = _rand_emb(seed=20)
        await init_store.register("x", query.copy(), MODEL_ALT)  # 다른 model_id
        match = await init_store.find_match(query, MODEL, threshold=0.5)
        assert match is None  # 다른 model_id → 제외

    @pytest.mark.asyncio
    async def test_threshold_miss(self, init_store: MemoryStore) -> None:
        vecs = _ortho_embs(2, DIM)
        await init_store.register("a", vecs[0].copy(), MODEL)
        match = await init_store.find_match(vecs[1], MODEL, threshold=0.5)
        assert match is None  # 직교 → cosine 0 < 0.5

    @pytest.mark.asyncio
    async def test_dim_mismatch_raises(self, init_store: MemoryStore) -> None:
        bad = np.ones(DIM + 1, dtype=np.float32)
        bad /= np.linalg.norm(bad)
        with pytest.raises(ValueError):
            await init_store.find_match(bad, MODEL, threshold=0.5)


# ---------------------------------------------------------------------------
# centroid L2 정규화
# ---------------------------------------------------------------------------

class TestCentroid:
    @pytest.mark.asyncio
    async def test_centroid_unit_norm_after_register(self, init_store: MemoryStore) -> None:
        emb = _rand_emb(seed=30)
        sp = await init_store.register("norm_test", emb, MODEL)
        centroid = init_store._centroids[sp.id]
        assert np.linalg.norm(centroid) == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_centroid_unit_norm_after_upsert(self, init_store: MemoryStore) -> None:
        sp1 = await init_store.register("nc", _rand_emb(seed=31), MODEL)
        await init_store.register("nc", _rand_emb(seed=32), MODEL)
        centroid = init_store._centroids[sp1.id]
        assert np.linalg.norm(centroid) == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_centroid_determinism(self, init_store: MemoryStore) -> None:
        emb = _rand_emb(seed=99)
        sp = await init_store.register("det", emb, MODEL)
        c1 = init_store._centroids[sp.id].copy()
        # 재조회해도 동일
        c2 = init_store._centroids[sp.id].copy()
        assert np.allclose(c1, c2)

    @pytest.mark.asyncio
    async def test_centroid_cache_not_recomputed_on_find_match(
        self, init_store: MemoryStore
    ) -> None:
        """find_match 는 캐시 centroid 만 사용 — embeddings 재평균 X."""
        emb = _rand_emb(seed=50)
        sp = await init_store.register("cache_test", emb, MODEL)
        centroid_before = init_store._centroids[sp.id].copy()

        # 직접 centroid dict 를 오염시켜 cache 사용 여부 검증
        sentinel = np.zeros(DIM, dtype=np.float32)
        sentinel[0] = 1.0
        init_store._centroids[sp.id] = sentinel

        match = await init_store.find_match(sentinel, MODEL, threshold=0.9)
        # centroid 가 sentinel 로 교체됐으므로 sentinel query 와 매치돼야 함
        assert match is not None
        assert match.speaker.id == sp.id
        # _embeddings 는 원래 emb 이지만 centroid 는 sentinel → cache 사용 확인
        assert np.allclose(init_store._centroids[sp.id], sentinel)


# ---------------------------------------------------------------------------
# set_alias
# ---------------------------------------------------------------------------

class TestSetAlias:
    @pytest.mark.asyncio
    async def test_set_alias_ok(self, init_store: MemoryStore) -> None:
        sp = await init_store.register("original", _rand_emb(seed=60), MODEL)
        updated = await init_store.set_alias(sp.id, "renamed")
        assert updated.name == "renamed"
        assert updated.id == sp.id

    @pytest.mark.asyncio
    async def test_set_alias_duplicate_raises_integrity_error(
        self, init_store: MemoryStore
    ) -> None:
        sp1 = await init_store.register("alice", _rand_emb(seed=61), MODEL)
        await init_store.register("bob", _rand_emb(seed=62), MODEL)
        with pytest.raises(IntegrityError):
            await init_store.set_alias(sp1.id, "bob")  # bob already exists

    @pytest.mark.asyncio
    async def test_set_alias_same_model_id_isolation(self, init_store: MemoryStore) -> None:
        """다른 model_id 에 같은 이름 존재해도 IntegrityError 아님."""
        sp1 = await init_store.register("shared", _rand_emb(seed=63), MODEL)
        await init_store.register("shared", _rand_emb(seed=64), MODEL_ALT)
        # sp1 을 "shared" 로 set_alias — 같은 model_id 에 같은 이름이므로 upsert 됐을 것
        # 실제로 sp1 는 이미 name="shared" 이므로 self-rename
        updated = await init_store.set_alias(sp1.id, "shared")
        assert updated.name == "shared"


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

class TestMerge:
    @pytest.mark.asyncio
    async def test_merge_utterance_count(self, init_store: MemoryStore) -> None:
        vecs = _ortho_embs(2, DIM)
        src = await init_store.save("src", vecs[0].copy(), MODEL)
        tgt = await init_store.save("tgt", vecs[1].copy(), MODEL)
        merged = await init_store.merge(src.id, tgt.id)
        assert merged.utterance_count == src.utterance_count + tgt.utterance_count

    @pytest.mark.asyncio
    async def test_merge_source_deleted(self, init_store: MemoryStore) -> None:
        vecs = _ortho_embs(2, DIM)
        src = await init_store.save("src2", vecs[0].copy(), MODEL)
        tgt = await init_store.save("tgt2", vecs[1].copy(), MODEL)
        await init_store.merge(src.id, tgt.id)
        assert src.id not in init_store._speakers

    @pytest.mark.asyncio
    async def test_merge_target_centroid_updated(self, init_store: MemoryStore) -> None:
        vecs = _ortho_embs(2, DIM)
        src = await init_store.save("src3", vecs[0].copy(), MODEL)
        tgt = await init_store.save("tgt3", vecs[1].copy(), MODEL)
        old_centroid = init_store._centroids[tgt.id].copy()
        await init_store.merge(src.id, tgt.id)
        new_centroid = init_store._centroids[tgt.id]
        assert not np.allclose(old_centroid, new_centroid)  # centroid 갱신됨

    @pytest.mark.asyncio
    async def test_merge_source_missing_raises(self, init_store: MemoryStore) -> None:
        tgt = await init_store.save("tgt4", _rand_emb(seed=70), MODEL)
        fake_id = uuid.uuid4()
        with pytest.raises(ValueError):
            await init_store.merge(fake_id, tgt.id)

    @pytest.mark.asyncio
    async def test_merge_centroid_unit_norm(self, init_store: MemoryStore) -> None:
        vecs = _ortho_embs(2, DIM)
        src = await init_store.save("mns", vecs[0].copy(), MODEL)
        tgt = await init_store.save("mnt", vecs[1].copy(), MODEL)
        await init_store.merge(src.id, tgt.id)
        norm = float(np.linalg.norm(init_store._centroids[tgt.id]))
        assert norm == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_speaker(self, init_store: MemoryStore) -> None:
        sp = await init_store.save("to_delete", _rand_emb(seed=80), MODEL)
        await init_store.delete(sp.id)
        results = [s async for s in init_store.list_all()]
        assert all(s.id != sp.id for s in results)

    @pytest.mark.asyncio
    async def test_delete_removes_centroid(self, init_store: MemoryStore) -> None:
        sp = await init_store.save("del_c", _rand_emb(seed=81), MODEL)
        await init_store.delete(sp.id)
        assert sp.id not in init_store._centroids

    @pytest.mark.asyncio
    async def test_delete_missing_raises(self, init_store: MemoryStore) -> None:
        with pytest.raises(ValueError):
            await init_store.delete(uuid.uuid4())


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------

class TestListAll:
    @pytest.mark.asyncio
    async def test_list_all_no_filter(self, init_store: MemoryStore) -> None:
        await init_store.save("a", _rand_emb(seed=90), MODEL)
        await init_store.save("b", _rand_emb(seed=91), MODEL_ALT)
        results = [s async for s in init_store.list_all()]
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_all_model_id_filter(self, init_store: MemoryStore) -> None:
        await init_store.save("a", _rand_emb(seed=92), MODEL)
        await init_store.save("b", _rand_emb(seed=93), MODEL_ALT)
        results = [s async for s in init_store.list_all(model_id=MODEL)]
        assert len(results) == 1
        assert results[0].name == "a"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    def test_isinstance_speaker_store(self) -> None:
        assert isinstance(MemoryStore(), SpeakerStore)
