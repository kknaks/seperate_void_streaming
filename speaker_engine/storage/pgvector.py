"""PgvectorStore — PostgreSQL + pgvector 백엔드 (S-04, extras [pgvector], spec-02 §3/§6)."""

from __future__ import annotations

import re
from typing import AsyncIterator, Literal
from uuid import UUID, uuid4

import numpy as np

from speaker_engine.exceptions import IntegrityError, StorageError
from speaker_engine.storage.base import SpeakerMatch
from speaker_engine.types import Speaker

_DEFAULT_MODEL_ID = "pyannote/embedding"
_POOL_MIN_SIZE = 1
_POOL_MAX_SIZE = 5


# ── 순수 헬퍼 ─────────────────────────────────────────────────────────────────


def _model_slug(model_id: str) -> str:
    """model_id → 안전한 테이블·인덱스 이름 suffix.

    e.g. "pyannote/embedding" → "pyannote_embedding"
    """
    return re.sub(r"[^a-zA-Z0-9]", "_", model_id).strip("_").lower()


def _table_names(model_id: str) -> tuple[str, str]:
    """(speakers_table, centroids_table).

    default model_id → ("speakers", "speaker_centroids").
    기타 → ("speakers_{slug}", "speaker_centroids_{slug}") — spec-02 §3-1 Option A.
    """
    if model_id == _DEFAULT_MODEL_ID:
        return "speakers", "speaker_centroids"
    slug = _model_slug(model_id)
    return f"speakers_{slug}", f"speaker_centroids_{slug}"


def _constraint_name(model_id: str) -> str:
    """UNIQUE constraint 이름 — 테이블 이름 충돌 방지."""
    if model_id == _DEFAULT_MODEL_ID:
        return "uq_name_per_model"
    return f"uq_name_per_model_{_model_slug(model_id)}"


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    if norm == 0.0:
        raise ValueError("zero vector — L2 정규화 불가")
    return v / norm


def _compute_centroid(embeddings: list[np.ndarray]) -> np.ndarray:
    """mean(embeddings) → L2 normalize — spec-02 §4-3."""
    return _l2_normalize(np.mean(embeddings, axis=0))


def _row_to_speaker(row: object) -> Speaker:
    """asyncpg Record → Speaker dataclass. TIMESTAMPTZ → epoch float."""
    reg_at = row["registered_at"]
    return Speaker(
        id=UUID(str(row["id"])),
        name=row["name"],
        origin=row["origin"],
        embedding_dim=row["embedding_dim"],
        model_id=row["model_id"],
        registered_at=reg_at.timestamp() if reg_at is not None else None,
        first_seen=row["first_seen"].timestamp(),
        last_seen=row["last_seen"].timestamp(),
        utterance_count=row["utterance_count"],
    )


def _sql_escape_literal(s: str) -> str:
    """SQL literal 안 단일 따옴표 escape (DDL 인라인 리터럴 전용)."""
    return s.replace("'", "''")


# ── DDL 어셈블 (테스트 가능 순수 함수) ────────────────────────────────────────


def build_ddl(embedding_dim: int, model_id: str) -> list[str]:
    """spec-02 §3-2 DDL SQL 목록 반환. 모두 멱등 (IF NOT EXISTS).

    model_id → table names via Option A 정책 (_table_names).
    HNSW partial index WHERE 절에는 원본 model_id 리터럴 사용.
    """
    sp, ct = _table_names(model_id)
    slug = _model_slug(model_id)
    uq = _constraint_name(model_id)
    mid_lit = _sql_escape_literal(model_id)

    return [
        "CREATE EXTENSION IF NOT EXISTS vector",
        f"""CREATE TABLE IF NOT EXISTS {sp} (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    origin          TEXT NOT NULL CHECK (origin IN ('registered', 'stored')),
    embeddings      VECTOR({embedding_dim})[] NOT NULL,
    embedding_dim   INTEGER NOT NULL DEFAULT {embedding_dim},
    model_id        TEXT NOT NULL DEFAULT '{mid_lit}',
    registered_at   TIMESTAMPTZ,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    utterance_count INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT {uq} UNIQUE (name, model_id)
)""",
        f"CREATE INDEX IF NOT EXISTS idx_{sp}_origin_model ON {sp} (origin, model_id)",
        f"CREATE INDEX IF NOT EXISTS idx_{sp}_last_seen ON {sp} (last_seen)",
        f"""CREATE TABLE IF NOT EXISTS {ct} (
    speaker_id  UUID PRIMARY KEY REFERENCES {sp}(id) ON DELETE CASCADE,
    centroid    VECTOR({embedding_dim}) NOT NULL,
    model_id    TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""",
        f"""CREATE INDEX IF NOT EXISTS idx_{ct}_hnsw_{slug}
    ON {ct}
    USING hnsw (centroid vector_cosine_ops)
    WHERE model_id = '{mid_lit}'""",
    ]


def build_find_match_sql(sp: str, ct: str, origin_filter: str | None = None) -> str:
    """find_match 쿼리 어셈블. $1=embedding, $2=model_id, $3=1-threshold (distance 상한).

    origin_filter=None → WHERE 절 없음 (전체).
    """
    origin_clause = f"AND s.origin = '{origin_filter}'" if origin_filter else ""
    return (
        f"SELECT s.*, 1 - (sc.centroid <=> $1) AS cosine_sim "
        f"FROM {sp} s "
        f"JOIN {ct} sc ON sc.speaker_id = s.id "
        f"WHERE s.model_id = $2 {origin_clause} "
        f"ORDER BY sc.centroid <=> $1 "
        f"LIMIT 1"
    )


# ── PgvectorStore ──────────────────────────────────────────────────────────────


class PgvectorStore:
    """PostgreSQL + pgvector 영속 저장소.

    spec-02 §3-2 DDL 박제. Option A model_id별 테이블.
    asyncpg connection pool. extras [pgvector] 필요.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: object | None = None
        self._embedding_dim: int | None = None
        self._model_id: str | None = None
        self._anon_counter: int = 1

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _pool_or_raise(self) -> object:
        if self._pool is None:
            raise StorageError("init_schema() 미호출 — pool 없음")
        return self._pool

    @property
    def _sp_ct(self) -> tuple[str, str]:
        assert self._model_id is not None
        return _table_names(self._model_id)

    def _validate_dim(self, embedding: np.ndarray) -> None:
        if self._embedding_dim is not None and embedding.shape[0] != self._embedding_dim:
            raise ValueError(
                f"embedding dim {embedding.shape[0]} != expected {self._embedding_dim}"
            )

    @staticmethod
    async def _register_codecs(conn: object) -> None:
        """asyncpg pool init 콜백 — pgvector numpy codec 등록."""
        try:
            from pgvector.asyncpg import register_vector  # type: ignore[import]
        except ImportError as e:
            raise StorageError(
                "pgvector 미설치. pip install 'speaker_engine[pgvector]'"
            ) from e
        await register_vector(conn)

    async def _upsert_centroid(
        self, conn: object, speaker_id: UUID, centroid: np.ndarray, model_id: str
    ) -> None:
        """speaker_centroids upsert — ON CONFLICT speaker_id DO UPDATE."""
        sp, ct = _table_names(model_id)
        await conn.execute(
            f"INSERT INTO {ct} (speaker_id, centroid, model_id, updated_at) "
            f"VALUES ($1, $2, $3, NOW()) "
            f"ON CONFLICT (speaker_id) DO UPDATE "
            f"SET centroid = EXCLUDED.centroid, updated_at = NOW()",
            speaker_id,
            centroid,
            model_id,
        )

    async def _fetch_embeddings(
        self, conn: object, speaker_id: UUID, sp: str
    ) -> list[np.ndarray]:
        """speakers.embeddings 배열 → list[numpy]."""
        row = await conn.fetchrow(
            f"SELECT embeddings FROM {sp} WHERE id = $1", speaker_id
        )
        if row is None or row["embeddings"] is None:
            return []
        return list(row["embeddings"])

    # ── SpeakerStore Protocol 8 메서드 ────────────────────────────────────────

    async def init_schema(self, embedding_dim: int, model_id: str) -> None:
        """DDL 멱등 실행 + pool 생성 + anon 카운터 초기화. spec-02 §6."""
        try:
            import asyncpg  # type: ignore[import]
        except ImportError as e:
            raise StorageError(
                "asyncpg 미설치. pip install 'speaker_engine[pgvector]'"
            ) from e

        try:
            pool = await asyncpg.create_pool(
                self._dsn,
                min_size=_POOL_MIN_SIZE,
                max_size=_POOL_MAX_SIZE,
                init=self._register_codecs,
            )
        except Exception as e:
            raise StorageError(f"PostgreSQL pool 초기화 실패: {e}") from e

        self._pool = pool
        self._embedding_dim = embedding_dim
        self._model_id = model_id

        sp, _ = _table_names(model_id)

        try:
            async with pool.acquire() as conn:
                for stmt in build_ddl(embedding_dim, model_id):
                    try:
                        await conn.execute(stmt)
                    except Exception as e:
                        if "extension" in str(e).lower() and "vector" in str(e).lower():
                            raise StorageError(
                                "pgvector extension 미설치. "
                                "PostgreSQL 에서 CREATE EXTENSION vector 필요"
                            ) from e
                        raise StorageError(f"DDL 실행 실패: {e}") from e

                # anon_NNN 카운터 — DB 재시작 시 max 기반 초기화 (spec-02 §4-4)
                row = await conn.fetchrow(
                    f"SELECT MAX(CAST(SUBSTR(name, 6) AS INTEGER)) AS max_anon "
                    f"FROM {sp} "
                    f"WHERE name LIKE 'anon_%' AND model_id = $1",
                    model_id,
                )
                max_anon = row["max_anon"] if row and row["max_anon"] is not None else 0
                self._anon_counter = max_anon + 1

        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"init_schema 실패: {e}") from e

    async def register(
        self,
        name: str,
        embedding: np.ndarray,
        model_id: str,
    ) -> Speaker:
        """origin=registered 저장. 동일 (name, model_id) 존재 시 upsert + centroid 재계산."""
        self._validate_dim(embedding)
        sp, ct = _table_names(model_id)
        pool = self._pool_or_raise()

        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"SELECT id FROM {sp} WHERE name = $1 AND model_id = $2",
                    name,
                    model_id,
                )

                if row is not None:
                    speaker_id = UUID(str(row["id"]))
                    # upsert — 기존 embeddings 에 append + 카운터 증가
                    await conn.execute(
                        f"UPDATE {sp} "
                        f"SET embeddings = array_append(embeddings, $1::vector), "
                        f"    last_seen = NOW(), "
                        f"    utterance_count = utterance_count + 1, "
                        f"    registered_at = COALESCE(registered_at, NOW()) "
                        f"WHERE id = $2",
                        embedding,
                        speaker_id,
                    )
                    embs = await self._fetch_embeddings(conn, speaker_id, sp)
                else:
                    # 신규 INSERT
                    # VECTOR(D)[] 배열: ARRAY[$1::vector] — asyncpg + pgvector codec
                    result = await conn.fetchrow(
                        f"INSERT INTO {sp} "
                        f"(name, origin, embeddings, embedding_dim, model_id, "
                        f" registered_at, first_seen, last_seen, utterance_count) "
                        f"VALUES ($1, 'registered', ARRAY[$2::vector], $3, $4, "
                        f"        NOW(), NOW(), NOW(), 1) "
                        f"RETURNING id",
                        name,
                        embedding,
                        embedding.shape[0],
                        model_id,
                    )
                    speaker_id = UUID(str(result["id"]))
                    embs = [embedding]

                centroid = _compute_centroid(embs)
                await self._upsert_centroid(conn, speaker_id, centroid, model_id)

                speaker_row = await conn.fetchrow(
                    f"SELECT * FROM {sp} WHERE id = $1", speaker_id
                )
                return _row_to_speaker(speaker_row)

    async def find_match(
        self,
        embedding: np.ndarray,
        model_id: str,
        threshold: float,
        origin: Literal["registered", "stored", "any"] = "any",
    ) -> SpeakerMatch | None:
        """cosine 유사도 1-NN. registered 우선 + model_id 격리. spec-02 §4-1.

        pgvector `<=>` = cosine distance → similarity = 1 - distance.
        HNSW partial index 활용.
        """
        self._validate_dim(embedding)
        sp, ct = _table_names(model_id)
        pool = self._pool_or_raise()

        async def _query_origin(orig: str) -> SpeakerMatch | None:
            sql = build_find_match_sql(sp, ct, origin_filter=orig)
            row = await conn.fetchrow(sql, embedding, model_id)
            if row is None:
                return None
            sim = float(row["cosine_sim"])
            if sim < threshold:
                return None
            return SpeakerMatch(
                speaker=_row_to_speaker(row),
                cosine_similarity=sim,
                origin=row["origin"],
            )

        async with pool.acquire() as conn:
            if origin == "any":
                result = await _query_origin("registered")
                if result is not None:
                    return result
                return await _query_origin("stored")
            return await _query_origin(origin)

    async def save(
        self,
        name: str | None,
        embedding: np.ndarray,
        model_id: str,
    ) -> Speaker:
        """origin=stored 저장. name=None 이면 anon_NNN 자동 생성. spec-02 §4-4."""
        self._validate_dim(embedding)
        if name is None:
            name = f"anon_{self._anon_counter:03d}"
            self._anon_counter += 1

        sp, _ = _table_names(model_id)
        pool = self._pool_or_raise()

        async with pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.fetchrow(
                    f"INSERT INTO {sp} "
                    f"(name, origin, embeddings, embedding_dim, model_id, "
                    f" registered_at, first_seen, last_seen, utterance_count) "
                    f"VALUES ($1, 'stored', ARRAY[$2::vector], $3, $4, "
                    f"        NULL, NOW(), NOW(), 1) "
                    f"RETURNING id",
                    name,
                    embedding,
                    embedding.shape[0],
                    model_id,
                )
                speaker_id = UUID(str(result["id"]))
                centroid = _l2_normalize(embedding.copy())
                await self._upsert_centroid(conn, speaker_id, centroid, model_id)

                speaker_row = await conn.fetchrow(
                    f"SELECT * FROM {sp} WHERE id = $1", speaker_id
                )
                return _row_to_speaker(speaker_row)

    async def list_all(self, model_id: str | None = None) -> AsyncIterator[Speaker]:
        """model_id=None 이면 전체. 지정 시 해당 model_id 만."""
        pool = self._pool_or_raise()

        async with pool.acquire() as conn:
            if model_id is None:
                # 전체 — 알려진 model_id 테이블들 조회
                assert self._model_id is not None
                sp, _ = _table_names(self._model_id)
                rows = await conn.fetch(f"SELECT * FROM {sp}")
            else:
                sp, _ = _table_names(model_id)
                rows = await conn.fetch(
                    f"SELECT * FROM {sp} WHERE model_id = $1", model_id
                )

        for row in rows:
            yield _row_to_speaker(row)

    async def set_alias(self, speaker_id: UUID, name: str) -> Speaker:
        """speaker.name 갱신. UNIQUE(name, model_id) 위반 시 IntegrityError."""
        assert self._model_id is not None
        sp, _ = self._sp_ct
        pool = self._pool_or_raise()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT * FROM {sp} WHERE id = $1", speaker_id)
            if row is None:
                raise ValueError(f"speaker {speaker_id} not found")
            try:
                await conn.execute(
                    f"UPDATE {sp} SET name = $1 WHERE id = $2", name, speaker_id
                )
            except Exception as e:
                if "unique" in str(e).lower() or "uq_name" in str(e).lower():
                    raise IntegrityError(
                        f"UNIQUE(name, model_id) 위반: ({name!r}, {row['model_id']!r})"
                    ) from e
                raise
            updated = await conn.fetchrow(f"SELECT * FROM {sp} WHERE id = $1", speaker_id)
            return _row_to_speaker(updated)

    async def merge(self, source_id: UUID, target_id: UUID) -> Speaker:
        """source → target 합산. source DELETE (CASCADE centroid). target centroid 재계산."""
        assert self._model_id is not None
        sp, _ = self._sp_ct
        pool = self._pool_or_raise()

        async with pool.acquire() as conn:
            async with conn.transaction():
                src_row = await conn.fetchrow(
                    f"SELECT * FROM {sp} WHERE id = $1", source_id
                )
                if src_row is None:
                    raise ValueError(f"source speaker {source_id} not found")
                tgt_row = await conn.fetchrow(
                    f"SELECT * FROM {sp} WHERE id = $1", target_id
                )
                if tgt_row is None:
                    raise ValueError(f"target speaker {target_id} not found")

                # target.embeddings = array_cat(target, source)
                await conn.execute(
                    f"UPDATE {sp} "
                    f"SET embeddings = array_cat(embeddings, "
                    f"    (SELECT embeddings FROM {sp} WHERE id = $1)), "
                    f"    utterance_count = utterance_count + $2, "
                    f"    first_seen = LEAST(first_seen, $3), "
                    f"    last_seen = GREATEST(last_seen, $4) "
                    f"WHERE id = $5",
                    source_id,
                    src_row["utterance_count"],
                    src_row["first_seen"],
                    src_row["last_seen"],
                    target_id,
                )

                # source DELETE (CASCADE → speaker_centroids 자동 삭제)
                await conn.execute(f"DELETE FROM {sp} WHERE id = $1", source_id)

                # target centroid 재계산
                embs = await self._fetch_embeddings(conn, target_id, sp)
                centroid = _compute_centroid(embs)
                await self._upsert_centroid(
                    conn, target_id, centroid, tgt_row["model_id"]
                )

                updated = await conn.fetchrow(
                    f"SELECT * FROM {sp} WHERE id = $1", target_id
                )
                return _row_to_speaker(updated)

    async def delete(self, speaker_id: UUID) -> None:
        """speakers 행 DELETE → CASCADE centroid. 없으면 ValueError. spec-02 §5."""
        assert self._model_id is not None
        sp, _ = self._sp_ct
        pool = self._pool_or_raise()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT id FROM {sp} WHERE id = $1", speaker_id
            )
            if row is None:
                raise ValueError(f"speaker {speaker_id} not found")
            await conn.execute(f"DELETE FROM {sp} WHERE id = $1", speaker_id)


__all__ = ["PgvectorStore", "build_ddl", "build_find_match_sql"]
