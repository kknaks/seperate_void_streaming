"""PgvectorStore 단위 테스트 — mock 기반. spec-05 §2-2 unit 카테고리.

실 PostgreSQL 인스턴스 없이 검증:
  - DDL SQL 어셈블 (spec-02 §3-2 와 일치)
  - model_id별 테이블 suffix (Option A)
  - 예외 wrapping (UniqueViolationError → IntegrityError, ConnectionError → StorageError)
  - find_match SQL 어셈블 (registered 우선 / stored fallback / model_id 격리 WHERE)
  - centroid 재계산 (L2 normalized mean — spec-02 §4-3)
  - anon_NNN SQL 패턴
  - pool init / codec 등록 흐름 (asyncpg.create_pool mock)
"""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import numpy as np
import pytest

from speaker_engine.exceptions import IntegrityError, StorageError
from speaker_engine.storage.pgvector import (
    PgvectorStore,
    _compute_centroid,
    _constraint_name,
    _l2_normalize,
    _model_slug,
    _table_names,
    build_ddl,
    build_find_match_sql,
)

# ── 상수 ──────────────────────────────────────────────────────────────────────

DIM = 4
MODEL_DEFAULT = "pyannote/embedding"
MODEL_ALT = "wespeaker/community-1"
DSN = "postgresql://user:pw@localhost:5432/testdb"


def _rand_emb(dim: int = DIM, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


# ── 1. model_id slug / table_names / constraint_name ─────────────────────────


class TestModelSlug:
    def test_default_model_id(self) -> None:
        assert _model_slug(MODEL_DEFAULT) == "pyannote_embedding"

    def test_alt_model_id(self) -> None:
        assert _model_slug(MODEL_ALT) == "wespeaker_community_1"

    def test_special_chars(self) -> None:
        slug = _model_slug("org/model-v1.0")
        assert re.match(r"^[a-z0-9_]+$", slug)

    def test_table_names_default(self) -> None:
        sp, ct = _table_names(MODEL_DEFAULT)
        assert sp == "speakers"
        assert ct == "speaker_centroids"

    def test_table_names_alt(self) -> None:
        sp, ct = _table_names(MODEL_ALT)
        assert sp == "speakers_wespeaker_community_1"
        assert ct == "speaker_centroids_wespeaker_community_1"

    def test_constraint_name_default(self) -> None:
        assert _constraint_name(MODEL_DEFAULT) == "uq_name_per_model"

    def test_constraint_name_alt(self) -> None:
        cn = _constraint_name(MODEL_ALT)
        assert cn == "uq_name_per_model_wespeaker_community_1"


# ── 2. DDL SQL 어셈블 — spec-02 §3-2 일치 검증 ───────────────────────────────


class TestBuildDDL:
    def setup_method(self) -> None:
        self.stmts = build_ddl(embedding_dim=512, model_id=MODEL_DEFAULT)

    def test_extension_stmt(self) -> None:
        assert any("CREATE EXTENSION IF NOT EXISTS vector" in s for s in self.stmts)

    def test_speakers_table_created(self) -> None:
        speakers_ddl = "\n".join(self.stmts)
        assert "CREATE TABLE IF NOT EXISTS speakers" in speakers_ddl

    def test_vector_dim(self) -> None:
        combined = "\n".join(self.stmts)
        assert "VECTOR(512)" in combined

    def test_embeddings_array_column(self) -> None:
        combined = "\n".join(self.stmts)
        assert "VECTOR(512)[]" in combined

    def test_unique_constraint_name(self) -> None:
        combined = "\n".join(self.stmts)
        assert "uq_name_per_model" in combined

    def test_centroids_table_created(self) -> None:
        combined = "\n".join(self.stmts)
        assert "CREATE TABLE IF NOT EXISTS speaker_centroids" in combined

    def test_hnsw_index(self) -> None:
        combined = "\n".join(self.stmts)
        assert "hnsw" in combined
        assert "vector_cosine_ops" in combined

    def test_hnsw_partial_index_uses_original_model_id(self) -> None:
        combined = "\n".join(self.stmts)
        assert "pyannote/embedding" in combined

    def test_cascade_delete_on_centroids(self) -> None:
        combined = "\n".join(self.stmts)
        assert "ON DELETE CASCADE" in combined

    def test_origin_check_constraint(self) -> None:
        combined = "\n".join(self.stmts)
        assert "registered" in combined and "stored" in combined

    def test_all_stmts_are_idempotent(self) -> None:
        for s in self.stmts:
            assert "IF NOT EXISTS" in s, f"비멱등 DDL: {s[:60]}"

    def test_alt_model_id_table_suffix(self) -> None:
        stmts = build_ddl(embedding_dim=256, model_id=MODEL_ALT)
        combined = "\n".join(stmts)
        assert "speakers_wespeaker_community_1" in combined
        assert "speaker_centroids_wespeaker_community_1" in combined
        assert "VECTOR(256)" in combined
        # HNSW partial index 는 원본 model_id 리터럴 (슬러그 아님)
        assert "wespeaker/community-1" in combined

    def test_default_model_no_suffix(self) -> None:
        stmts = build_ddl(embedding_dim=512, model_id=MODEL_DEFAULT)
        combined = "\n".join(stmts)
        # default 테이블은 suffix 없음
        assert "speakers_pyannote" not in combined


# ── 3. find_match SQL 어셈블 ──────────────────────────────────────────────────


class TestBuildFindMatchSQL:
    def test_registered_filter(self) -> None:
        sql = build_find_match_sql("speakers", "speaker_centroids", "registered")
        assert "s.origin = 'registered'" in sql
        assert "cosine_sim" in sql
        assert "ORDER BY" in sql and "LIMIT 1" in sql

    def test_stored_filter(self) -> None:
        sql = build_find_match_sql("speakers", "speaker_centroids", "stored")
        assert "s.origin = 'stored'" in sql

    def test_no_origin_filter(self) -> None:
        sql = build_find_match_sql("speakers", "speaker_centroids", None)
        assert "s.origin" not in sql

    def test_model_id_isolation(self) -> None:
        sql = build_find_match_sql("speakers", "speaker_centroids", "registered")
        assert "s.model_id = $2" in sql

    def test_cosine_distance_operator(self) -> None:
        sql = build_find_match_sql("speakers", "speaker_centroids", "registered")
        # pgvector cosine distance operator
        assert "<=>" in sql

    def test_join_on_centroids(self) -> None:
        sql = build_find_match_sql("speakers", "speaker_centroids", "registered")
        assert "JOIN speaker_centroids sc ON sc.speaker_id = s.id" in sql


# ── 4. centroid 재계산 — spec-02 §4-3 ────────────────────────────────────────


class TestCentroidComputation:
    def test_single_embedding_centroid_is_normalized(self) -> None:
        e = _rand_emb(seed=1)
        c = _compute_centroid([e])
        assert abs(np.linalg.norm(c) - 1.0) < 1e-5

    def test_mean_then_normalize(self) -> None:
        e1 = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        e2 = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        c = _compute_centroid([e1, e2])
        expected = np.array([1.0, 1.0, 0.0, 0.0], dtype=np.float32)
        expected /= np.linalg.norm(expected)
        np.testing.assert_allclose(c, expected, atol=1e-5)

    def test_zero_vector_raises(self) -> None:
        with pytest.raises(ValueError, match="zero vector"):
            _l2_normalize(np.zeros(4, dtype=np.float32))


# ── 5. pool init / codec 등록 흐름 — asyncpg mock ────────────────────────────


class TestPoolInit:
    """asyncpg.create_pool 을 mock 으로 교체 — pool init 흐름 검증."""

    def _make_conn_mock(self) -> AsyncMock:
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)
        conn.fetchrow = AsyncMock(return_value={"max_anon": None})
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)
        return conn

    def _make_pool_mock(self, conn: AsyncMock) -> MagicMock:
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=conn)
        return pool

    @pytest.mark.asyncio
    async def test_init_schema_calls_create_pool(self) -> None:
        conn = self._make_conn_mock()
        pool = self._make_pool_mock(conn)

        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)) as mock_cp, \
             patch(
                 "speaker_engine.storage.pgvector.PgvectorStore._register_codecs",
                 new=AsyncMock(),
             ):
            store = PgvectorStore(DSN)
            await store.init_schema(embedding_dim=DIM, model_id=MODEL_DEFAULT)

        mock_cp.assert_awaited_once()
        call_kwargs = mock_cp.call_args
        assert call_kwargs.args[0] == DSN or call_kwargs.kwargs.get("dsn") == DSN or DSN in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_init_schema_sets_anon_counter(self) -> None:
        conn = self._make_conn_mock()
        conn.fetchrow = AsyncMock(return_value={"max_anon": 5})
        pool = self._make_pool_mock(conn)

        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)), \
             patch(
                 "speaker_engine.storage.pgvector.PgvectorStore._register_codecs",
                 new=AsyncMock(),
             ):
            store = PgvectorStore(DSN)
            await store.init_schema(embedding_dim=DIM, model_id=MODEL_DEFAULT)

        assert store._anon_counter == 6

    @pytest.mark.asyncio
    async def test_init_schema_anon_counter_starts_at_1_when_empty(self) -> None:
        conn = self._make_conn_mock()
        conn.fetchrow = AsyncMock(return_value={"max_anon": None})
        pool = self._make_pool_mock(conn)

        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)), \
             patch(
                 "speaker_engine.storage.pgvector.PgvectorStore._register_codecs",
                 new=AsyncMock(),
             ):
            store = PgvectorStore(DSN)
            await store.init_schema(embedding_dim=DIM, model_id=MODEL_DEFAULT)

        assert store._anon_counter == 1

    @pytest.mark.asyncio
    async def test_init_schema_storage_error_on_pool_failure(self) -> None:
        with patch("asyncpg.create_pool", new=AsyncMock(side_effect=OSError("refused"))):
            store = PgvectorStore(DSN)
            with pytest.raises(StorageError, match="pool 초기화"):
                await store.init_schema(embedding_dim=DIM, model_id=MODEL_DEFAULT)

    @pytest.mark.asyncio
    async def test_pool_or_raise_before_init(self) -> None:
        store = PgvectorStore(DSN)
        with pytest.raises(StorageError, match="init_schema"):
            store._pool_or_raise()


# ── 6. 예외 wrapping — UniqueViolationError → IntegrityError ─────────────────


class TestExceptionWrapping:
    """set_alias 의 UniqueViolationError → IntegrityError wrapping 검증."""

    @pytest.mark.asyncio
    async def test_set_alias_unique_violation_wrapped(self) -> None:
        speaker_id = uuid4()

        # asyncpg UniqueViolationError 시뮬레이션 (mock 으로 raise)
        class FakeUniqueError(Exception):
            pass

        fake_row = {
            "id": str(speaker_id),
            "name": "alice",
            "origin": "registered",
            "embedding_dim": DIM,
            "model_id": MODEL_DEFAULT,
            "registered_at": None,
            "first_seen": MagicMock(timestamp=lambda: 1.0),
            "last_seen": MagicMock(timestamp=lambda: 1.0),
            "utterance_count": 1,
        }

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=fake_row)
        conn.execute = AsyncMock(
            side_effect=FakeUniqueError("unique constraint uq_name_per_model")
        )
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)

        pool = MagicMock()
        pool.acquire = MagicMock(return_value=conn)

        store = PgvectorStore(DSN)
        store._pool = pool
        store._embedding_dim = DIM
        store._model_id = MODEL_DEFAULT

        with pytest.raises(IntegrityError):
            await store.set_alias(speaker_id, "bob")

    @pytest.mark.asyncio
    async def test_delete_not_found_raises_value_error(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)

        pool = MagicMock()
        pool.acquire = MagicMock(return_value=conn)

        store = PgvectorStore(DSN)
        store._pool = pool
        store._embedding_dim = DIM
        store._model_id = MODEL_DEFAULT

        with pytest.raises(ValueError, match="not found"):
            await store.delete(uuid4())

    @pytest.mark.asyncio
    async def test_merge_source_not_found_raises_value_error(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)

        tx = AsyncMock()
        tx.__aenter__ = AsyncMock(return_value=tx)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)

        pool = MagicMock()
        pool.acquire = MagicMock(return_value=conn)

        store = PgvectorStore(DSN)
        store._pool = pool
        store._embedding_dim = DIM
        store._model_id = MODEL_DEFAULT

        with pytest.raises(ValueError, match="not found"):
            await store.merge(uuid4(), uuid4())


# ── 7. anon_NNN SQL 패턴 — init_schema fetchrow 쿼리 검증 ────────────────────


class TestAnonSQL:
    """init_schema 가 max anon 조회 시 올바른 SQL / model_id 격리 사용 검증."""

    @pytest.mark.asyncio
    async def test_anon_query_uses_model_id_filter(self) -> None:
        captured_sqls: list[str] = []
        captured_args: list[tuple] = []

        async def fake_fetchrow(sql: str, *args):  # noqa: ANN001
            captured_sqls.append(sql)
            captured_args.append(args)
            return {"max_anon": None}

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)
        conn.fetchrow = AsyncMock(side_effect=fake_fetchrow)
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)

        pool = MagicMock()
        pool.acquire = MagicMock(return_value=conn)

        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)), \
             patch(
                 "speaker_engine.storage.pgvector.PgvectorStore._register_codecs",
                 new=AsyncMock(),
             ):
            store = PgvectorStore(DSN)
            await store.init_schema(embedding_dim=DIM, model_id=MODEL_DEFAULT)

        assert any(
            "anon_" in sql.lower() or "max" in sql.lower()
            for sql in captured_sqls
        ), "anon_NNN max 조회 SQL 미발급"
        assert any(MODEL_DEFAULT in str(args) for args in captured_args), \
            "model_id 파라미터 미포함"
