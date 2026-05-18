"""SqliteVecStore 단위 테스트 — spec-05 §2-2 unit 카테고리."""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pytest

try:
    import sqlite_vec as _sv  # noqa: F401

    HAS_SQLITE_VEC = True
except ImportError:
    HAS_SQLITE_VEC = False

pytestmark = pytest.mark.skipif(
    not HAS_SQLITE_VEC, reason="sqlite-vec 미설치 (pip install speaker_engine[sqlite])"
)

from speaker_engine.exceptions import IntegrityError, StorageError
from speaker_engine.storage import SpeakerStore, SqliteVecStore

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

DIM = 4
MODEL = "pyannote/embedding"
MODEL_ALT = "wespeaker/community-1"


def _rand_emb(seed: int, dim: int = DIM) -> np.ndarray:
    """seeded random unit vector. spec-05 §4.1."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _ortho_embs(n: int, dim: int = DIM) -> list[np.ndarray]:
    """hand-crafted 직교 단위 벡터. spec-05 §4.1."""
    assert dim >= n
    vecs = []
    for i in range(n):
        v = np.zeros(dim, dtype=np.float32)
        v[i] = 1.0
        vecs.append(v)
    return vecs


@pytest.fixture
def store() -> SqliteVecStore:
    return SqliteVecStore(":memory:")


@pytest.fixture
async def init_store() -> SqliteVecStore:
    s = SqliteVecStore(":memory:")
    await s.init_schema(embedding_dim=DIM, model_id=MODEL)
    return s


# ---------------------------------------------------------------------------
# init_schema
# ---------------------------------------------------------------------------


class TestInitSchema:
    async def test_idempotent(self, store: SqliteVecStore) -> None:
        """2회 호출 — CREATE IF NOT EXISTS 멱등. spec-02 §6."""
        await store.init_schema(DIM, MODEL)
        await store.init_schema(DIM, MODEL)  # 두 번째 호출 안전해야 함
        assert store._embedding_dim == DIM

    async def test_state_set(self, store: SqliteVecStore) -> None:
        await store.init_schema(DIM, MODEL)
        assert store._embedding_dim == DIM
        assert store._model_id == MODEL
        assert store._anon_counter == 1

    async def test_not_init_raises_storage_error(self, store: SqliteVecStore) -> None:
        with pytest.raises(StorageError):
            await store.save("x", _rand_emb(0), MODEL)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


class TestRegister:
    async def test_basic(self, init_store: SqliteVecStore) -> None:
        emb = _rand_emb(1)
        sp = await init_store.register("alice", emb, MODEL)
        assert sp.name == "alice"
        assert sp.origin == "registered"
        assert sp.model_id == MODEL
        assert sp.utterance_count == 1
        assert sp.registered_at is not None

    async def test_find_match_after_register(self, init_store: SqliteVecStore) -> None:
        emb = _rand_emb(2)
        sp = await init_store.register("bob", emb, MODEL)
        match = await init_store.find_match(emb, MODEL, threshold=0.9)
        assert match is not None
        assert match.speaker.id == sp.id
        assert match.origin == "registered"

    async def test_upsert_same_name_model(self, init_store: SqliteVecStore) -> None:
        emb1 = _rand_emb(3)
        emb2 = _rand_emb(4)
        sp1 = await init_store.register("carol", emb1, MODEL)
        sp2 = await init_store.register("carol", emb2, MODEL)
        assert sp1.id == sp2.id
        assert sp2.utterance_count == 2

    async def test_dim_mismatch_raises(self, init_store: SqliteVecStore) -> None:
        bad = np.ones(DIM + 1, dtype=np.float32)
        bad /= np.linalg.norm(bad)
        with pytest.raises(ValueError):
            await init_store.register("dave", bad, MODEL)


# ---------------------------------------------------------------------------
# save + anon_NNN
# ---------------------------------------------------------------------------


class TestSave:
    async def test_named(self, init_store: SqliteVecStore) -> None:
        sp = await init_store.save("eve", _rand_emb(10), MODEL)
        assert sp.name == "eve"
        assert sp.origin == "stored"
        assert sp.registered_at is None

    async def test_anon_first(self, init_store: SqliteVecStore) -> None:
        sp = await init_store.save(None, _rand_emb(11), MODEL)
        assert sp.name == "anon_001"

    async def test_anon_counter_monotone(self, init_store: SqliteVecStore) -> None:
        sp1 = await init_store.save(None, _rand_emb(12), MODEL)
        sp2 = await init_store.save(None, _rand_emb(13), MODEL)
        assert sp1.name == "anon_001"
        assert sp2.name == "anon_002"

    async def test_dim_mismatch_raises(self, init_store: SqliteVecStore) -> None:
        bad = np.ones(DIM + 2, dtype=np.float32)
        bad /= np.linalg.norm(bad)
        with pytest.raises(ValueError):
            await init_store.save(None, bad, MODEL)


# ---------------------------------------------------------------------------
# anon_NNN DB 재시작 초기화 (spec-02 §4-4)
# ---------------------------------------------------------------------------


class TestAnonRestart:
    async def test_counter_resumes_from_max(self, tmp_path: Path) -> None:
        """DB 재시작 시 기존 max anon 기반으로 카운터 초기화."""
        db_path = tmp_path / "test.db"

        s1 = SqliteVecStore(str(db_path))
        await s1.init_schema(DIM, MODEL)
        await s1.save(None, _rand_emb(20), MODEL)  # anon_001
        await s1.save(None, _rand_emb(21), MODEL)  # anon_002

        s2 = SqliteVecStore(str(db_path))
        await s2.init_schema(DIM, MODEL)
        sp = await s2.save(None, _rand_emb(22), MODEL)
        assert sp.name == "anon_003"  # 기존 max=2 기반 → 003 시작


# ---------------------------------------------------------------------------
# find_match — origin 우선순위 + model_id 격리
# ---------------------------------------------------------------------------


class TestFindMatch:
    async def test_any_prefers_registered(self, init_store: SqliteVecStore) -> None:
        """origin=any 시 registered hit 이면 stored 무시 — spec-02 §4-1."""
        vecs = _ortho_embs(2)
        await init_store.register("reg", vecs[0].copy(), MODEL)
        await init_store.save("sto", vecs[1].copy(), MODEL)

        match = await init_store.find_match(vecs[0], MODEL, threshold=0.9, origin="any")
        assert match is not None
        assert match.origin == "registered"
        assert match.speaker.name == "reg"

    async def test_any_falls_through_to_stored(self, init_store: SqliteVecStore) -> None:
        vecs = _ortho_embs(2)
        await init_store.register("reg", vecs[0].copy(), MODEL)
        await init_store.save("sto", vecs[1].copy(), MODEL)

        match = await init_store.find_match(vecs[1], MODEL, threshold=0.9, origin="any")
        assert match is not None
        assert match.origin == "stored"
        assert match.speaker.name == "sto"

    async def test_origin_registered_only(self, init_store: SqliteVecStore) -> None:
        vecs = _ortho_embs(2)
        await init_store.register("r", vecs[0].copy(), MODEL)
        await init_store.save("s", vecs[1].copy(), MODEL)

        match = await init_store.find_match(vecs[1], MODEL, threshold=0.5, origin="registered")
        assert match is None  # stored 는 검색 대상 아님

    async def test_origin_stored_only(self, init_store: SqliteVecStore) -> None:
        vecs = _ortho_embs(2)
        await init_store.register("r", vecs[0].copy(), MODEL)
        await init_store.save("s", vecs[1].copy(), MODEL)

        match = await init_store.find_match(vecs[0], MODEL, threshold=0.5, origin="stored")
        assert match is None  # registered 는 검색 대상 아님

    async def test_model_id_isolation(self, init_store: SqliteVecStore) -> None:
        q = _rand_emb(30)
        await init_store.register("x", q.copy(), MODEL_ALT)
        match = await init_store.find_match(q, MODEL, threshold=0.5)
        assert match is None  # 다른 model_id → 제외

    async def test_threshold_miss(self, init_store: SqliteVecStore) -> None:
        vecs = _ortho_embs(2)
        await init_store.register("a", vecs[0].copy(), MODEL)
        match = await init_store.find_match(vecs[1], MODEL, threshold=0.5)
        assert match is None  # 직교 → cosine 0 < 0.5

    async def test_dim_mismatch_raises(self, init_store: SqliteVecStore) -> None:
        bad = np.ones(DIM + 1, dtype=np.float32)
        bad /= np.linalg.norm(bad)
        with pytest.raises(ValueError):
            await init_store.find_match(bad, MODEL, threshold=0.5)


# ---------------------------------------------------------------------------
# centroid L2 정규화
# ---------------------------------------------------------------------------


class TestCentroid:
    async def test_unit_norm_after_register(self, init_store: SqliteVecStore) -> None:
        emb = _rand_emb(40)
        sp = await init_store.register("n", emb, MODEL)
        centroid = init_store._get_centroid(init_store._db, str(sp.id))
        assert centroid is not None
        assert np.linalg.norm(centroid) == pytest.approx(1.0, abs=1e-5)

    async def test_unit_norm_after_upsert(self, init_store: SqliteVecStore) -> None:
        sp = await init_store.register("nc", _rand_emb(41), MODEL)
        await init_store.register("nc", _rand_emb(42), MODEL)
        centroid = init_store._get_centroid(init_store._db, str(sp.id))
        assert centroid is not None
        assert np.linalg.norm(centroid) == pytest.approx(1.0, abs=1e-5)

    async def test_unit_norm_after_save(self, init_store: SqliteVecStore) -> None:
        sp = await init_store.save("s", _rand_emb(43), MODEL)
        centroid = init_store._get_centroid(init_store._db, str(sp.id))
        assert centroid is not None
        assert np.linalg.norm(centroid) == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------------------
# set_alias
# ---------------------------------------------------------------------------


class TestSetAlias:
    async def test_rename_ok(self, init_store: SqliteVecStore) -> None:
        sp = await init_store.register("orig", _rand_emb(50), MODEL)
        updated = await init_store.set_alias(sp.id, "renamed")
        assert updated.name == "renamed"
        assert updated.id == sp.id

    async def test_duplicate_raises_integrity_error(
        self, init_store: SqliteVecStore
    ) -> None:
        sp1 = await init_store.register("alice", _rand_emb(51), MODEL)
        await init_store.register("bob", _rand_emb(52), MODEL)
        with pytest.raises(IntegrityError):
            await init_store.set_alias(sp1.id, "bob")

    async def test_model_id_isolation(self, init_store: SqliteVecStore) -> None:
        """다른 model_id 에 같은 이름 존재해도 IntegrityError 아님."""
        sp1 = await init_store.register("shared", _rand_emb(53), MODEL)
        await init_store.register("shared", _rand_emb(54), MODEL_ALT)
        updated = await init_store.set_alias(sp1.id, "shared")  # self-rename
        assert updated.name == "shared"


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------


class TestMerge:
    async def test_utterance_count_sum(self, init_store: SqliteVecStore) -> None:
        vecs = _ortho_embs(2)
        src = await init_store.save("src", vecs[0].copy(), MODEL)
        tgt = await init_store.save("tgt", vecs[1].copy(), MODEL)
        merged = await init_store.merge(src.id, tgt.id)
        assert merged.utterance_count == src.utterance_count + tgt.utterance_count

    async def test_source_deleted(self, init_store: SqliteVecStore) -> None:
        vecs = _ortho_embs(2)
        src = await init_store.save("src2", vecs[0].copy(), MODEL)
        tgt = await init_store.save("tgt2", vecs[1].copy(), MODEL)
        await init_store.merge(src.id, tgt.id)
        all_ids = [sp.id async for sp in init_store.list_all()]
        assert src.id not in all_ids

    async def test_target_centroid_updated(self, init_store: SqliteVecStore) -> None:
        vecs = _ortho_embs(2)
        src = await init_store.save("src3", vecs[0].copy(), MODEL)
        tgt = await init_store.save("tgt3", vecs[1].copy(), MODEL)
        old_c = init_store._get_centroid(init_store._db, str(tgt.id))
        assert old_c is not None
        old_c = old_c.copy()
        await init_store.merge(src.id, tgt.id)
        new_c = init_store._get_centroid(init_store._db, str(tgt.id))
        assert new_c is not None
        assert not np.allclose(old_c, new_c)

    async def test_source_missing_raises(self, init_store: SqliteVecStore) -> None:
        tgt = await init_store.save("tgt4", _rand_emb(60), MODEL)
        with pytest.raises(ValueError):
            await init_store.merge(uuid.uuid4(), tgt.id)

    async def test_target_centroid_unit_norm(self, init_store: SqliteVecStore) -> None:
        vecs = _ortho_embs(2)
        src = await init_store.save("mns", vecs[0].copy(), MODEL)
        tgt = await init_store.save("mnt", vecs[1].copy(), MODEL)
        await init_store.merge(src.id, tgt.id)
        c = init_store._get_centroid(init_store._db, str(tgt.id))
        assert c is not None
        assert float(np.linalg.norm(c)) == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_removes_speaker(self, init_store: SqliteVecStore) -> None:
        sp = await init_store.save("to_del", _rand_emb(70), MODEL)
        await init_store.delete(sp.id)
        all_ids = [s.id async for s in init_store.list_all()]
        assert sp.id not in all_ids

    async def test_removes_centroid(self, init_store: SqliteVecStore) -> None:
        sp = await init_store.save("del_c", _rand_emb(71), MODEL)
        await init_store.delete(sp.id)
        assert init_store._get_centroid(init_store._db, str(sp.id)) is None

    async def test_missing_raises(self, init_store: SqliteVecStore) -> None:
        with pytest.raises(ValueError):
            await init_store.delete(uuid.uuid4())


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------


class TestListAll:
    async def test_no_filter(self, init_store: SqliteVecStore) -> None:
        await init_store.save("a", _rand_emb(80), MODEL)
        await init_store.save("b", _rand_emb(81), MODEL_ALT)
        results = [sp async for sp in init_store.list_all()]
        assert len(results) == 2

    async def test_model_id_filter(self, init_store: SqliteVecStore) -> None:
        await init_store.save("a", _rand_emb(82), MODEL)
        await init_store.save("b", _rand_emb(83), MODEL_ALT)
        results = [sp async for sp in init_store.list_all(model_id=MODEL)]
        assert len(results) == 1
        assert results[0].name == "a"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_isinstance_speaker_store(self) -> None:
        assert isinstance(SqliteVecStore(":memory:"), SpeakerStore)
