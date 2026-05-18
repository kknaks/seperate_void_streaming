"""SqliteVecStore — sqlite + sqlite-vec 영속 저장소 (spec-02 §3-3, extras [sqlite])."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import AsyncIterator, Literal
from uuid import UUID, uuid4

import numpy as np

from speaker_engine.exceptions import IntegrityError, StorageError
from speaker_engine.storage.base import SpeakerMatch
from speaker_engine.types import Speaker


# ── 순수 헬퍼 ─────────────────────────────────────────────────────────────────

def _l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    if norm == 0.0:
        raise ValueError("zero vector — L2 정규화 불가")
    return v / norm


def _compute_centroid(embeddings: list[np.ndarray]) -> np.ndarray:
    """mean(embeddings) → L2 normalize — spec-02 §4-3."""
    return _l2_normalize(np.mean(embeddings, axis=0))


def _emb_to_blob(emb: np.ndarray) -> bytes:
    return emb.astype(np.float32).tobytes()


def _blob_to_emb(blob: bytes | memoryview) -> np.ndarray:
    return np.frombuffer(bytes(blob), dtype="<f4").copy()


def _to_speaker(row: sqlite3.Row) -> Speaker:
    return Speaker(
        id=UUID(row["id"]),
        name=row["name"],
        origin=row["origin"],
        embedding_dim=row["embedding_dim"],
        model_id=row["model_id"],
        registered_at=row["registered_at"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        utterance_count=row["utterance_count"],
    )


# ── SqliteVecStore ─────────────────────────────────────────────────────────────

class SqliteVecStore:
    """SQLite + sqlite-vec 영속 저장소.

    spec-02 §3-3 DDL 박제 + speaker_embeddings 보조 테이블(Option A) + speaker_vss_meta.
    sync sqlite3 + asyncio.to_thread wrap. 단일 세션 전제 (lock 없음).
    extras [sqlite] 필요 (sqlite-vec).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._embedding_dim: int | None = None
        self._model_id: str | None = None
        self._anon_counter: int = 1
        self._conn: sqlite3.Connection | None = None

    # ── 연결 / 확장 ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
        """sqlite-vec extension 로드. 미설치 → StorageError."""
        try:
            import sqlite_vec  # type: ignore[import]
        except ImportError as e:
            raise StorageError(
                "sqlite-vec 미설치. pip install 'speaker_engine[sqlite]'"
            ) from e
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except Exception as e:
            conn.close()
            raise StorageError(f"sqlite-vec extension 로드 실패: {e}") from e

    @property
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StorageError("init_schema() 미호출 — DB 연결 없음")
        return self._conn

    def _validate_dim(self, embedding: np.ndarray) -> None:
        if self._embedding_dim is not None and embedding.shape[0] != self._embedding_dim:
            raise ValueError(
                f"embedding dim {embedding.shape[0]} != expected {self._embedding_dim}"
            )

    # ── centroid 헬퍼 (sync) ──────────────────────────────────────────────────

    def _upsert_centroid(
        self, conn: sqlite3.Connection, speaker_id: str, centroid: np.ndarray
    ) -> None:
        """speaker_vss (vec0) + speaker_vss_meta 갱신. rowid 기반 관리."""
        blob = _emb_to_blob(centroid)
        row = conn.execute(
            "SELECT vec_rowid FROM speaker_vss_meta WHERE speaker_id = ?", (speaker_id,)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM speaker_vss WHERE rowid = ?", (row["vec_rowid"],))
        cur = conn.execute(
            "INSERT INTO speaker_vss(speaker_id, centroid) VALUES (?, ?)", (speaker_id, blob)
        )
        conn.execute(
            "INSERT OR REPLACE INTO speaker_vss_meta(speaker_id, vec_rowid) VALUES (?, ?)",
            (speaker_id, cur.lastrowid),
        )

    def _delete_centroid(self, conn: sqlite3.Connection, speaker_id: str) -> None:
        """speaker_vss + speaker_vss_meta 삭제."""
        row = conn.execute(
            "SELECT vec_rowid FROM speaker_vss_meta WHERE speaker_id = ?", (speaker_id,)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM speaker_vss WHERE rowid = ?", (row["vec_rowid"],))
            conn.execute(
                "DELETE FROM speaker_vss_meta WHERE speaker_id = ?", (speaker_id,)
            )

    def _get_centroid(
        self, conn: sqlite3.Connection, speaker_id: str
    ) -> np.ndarray | None:
        """speaker_vss rowid 경유 centroid BLOB → numpy."""
        row = conn.execute(
            "SELECT vec_rowid FROM speaker_vss_meta WHERE speaker_id = ?", (speaker_id,)
        ).fetchone()
        if not row:
            return None
        vec_row = conn.execute(
            "SELECT centroid FROM speaker_vss WHERE rowid = ?", (row["vec_rowid"],)
        ).fetchone()
        if not vec_row:
            return None
        return _blob_to_emb(vec_row["centroid"])

    # ── SpeakerStore Protocol 8 메서드 ────────────────────────────────────────

    async def init_schema(self, embedding_dim: int, model_id: str) -> None:
        """DDL 멱등 실행 + sqlite-vec 로드 + anon 카운터 초기화. spec-02 §6."""
        def _sync() -> None:
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._load_sqlite_vec(conn)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")

            # spec-02 §3-3 DDL 박제 그대로
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speakers (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL,
                    origin          TEXT NOT NULL CHECK (origin IN ('registered','stored')),
                    embedding_dim   INTEGER NOT NULL,
                    model_id        TEXT NOT NULL,
                    registered_at   REAL,
                    first_seen      REAL NOT NULL,
                    last_seen       REAL NOT NULL,
                    utterance_count INTEGER NOT NULL DEFAULT 0,
                    CONSTRAINT uq_name_per_model UNIQUE (name, model_id)
                )
            """)
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS speaker_vss
                    USING vec0 (
                        speaker_id TEXT PARTITION KEY,
                        centroid   FLOAT[{embedding_dim}]
                    )
            """)
            # rowid 추적 보조 테이블 — PARTITION KEY 는 rowid 기반 관리 필요
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speaker_vss_meta (
                    speaker_id TEXT PRIMARY KEY,
                    vec_rowid  INTEGER NOT NULL
                )
            """)
            # 다중 embedding 보존 (Option A) — merge/upsert 정확성, MemoryStore 일관
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speaker_embeddings (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    speaker_id TEXT NOT NULL REFERENCES speakers(id) ON DELETE CASCADE,
                    embedding  BLOB NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_se_sp ON speaker_embeddings(speaker_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sp_om ON speakers(origin, model_id)"
            )
            conn.commit()

            # anon_NNN 카운터 — DB 재시작 시 max 기반 초기화 (spec-02 §4-4)
            row = conn.execute(
                "SELECT MAX(CAST(SUBSTR(name, 6) AS INTEGER)) FROM speakers "
                "WHERE name LIKE 'anon_%'"
            ).fetchone()
            max_anon = row[0] if row and row[0] is not None else 0

            self._conn = conn
            self._embedding_dim = embedding_dim
            self._model_id = model_id
            self._anon_counter = max_anon + 1

        await asyncio.to_thread(_sync)

    async def register(
        self, name: str, embedding: np.ndarray, model_id: str
    ) -> Speaker:
        """origin=registered 저장. 동일 (name, model_id) 존재 시 embedding upsert + centroid 재계산."""
        self._validate_dim(embedding)
        now = time.time()

        def _sync() -> Speaker:
            conn = self._db
            row = conn.execute(
                "SELECT id, utterance_count FROM speakers WHERE name = ? AND model_id = ?",
                (name, model_id),
            ).fetchone()

            if row:
                sid = row["id"]
                new_cnt = row["utterance_count"] + 1
                conn.execute(
                    "UPDATE speakers SET last_seen=?, utterance_count=?, "
                    "registered_at=COALESCE(registered_at,?) WHERE id=?",
                    (now, new_cnt, now, sid),
                )
                conn.execute(
                    "INSERT INTO speaker_embeddings(speaker_id, embedding) VALUES (?,?)",
                    (sid, _emb_to_blob(embedding)),
                )
                blobs = conn.execute(
                    "SELECT embedding FROM speaker_embeddings WHERE speaker_id=?", (sid,)
                ).fetchall()
                embs = [_blob_to_emb(b["embedding"]) for b in blobs]
                self._upsert_centroid(conn, sid, _compute_centroid(embs))
            else:
                sid = str(uuid4())
                conn.execute(
                    "INSERT INTO speakers VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, name, "registered", embedding.shape[0], model_id, now, now, now, 1),
                )
                conn.execute(
                    "INSERT INTO speaker_embeddings(speaker_id, embedding) VALUES (?,?)",
                    (sid, _emb_to_blob(embedding)),
                )
                self._upsert_centroid(conn, sid, _l2_normalize(embedding.copy()))

            conn.commit()
            return _to_speaker(
                conn.execute("SELECT * FROM speakers WHERE id=?", (sid,)).fetchone()
            )

        return await asyncio.to_thread(_sync)

    async def find_match(
        self,
        embedding: np.ndarray,
        model_id: str,
        threshold: float,
        origin: Literal["registered", "stored", "any"] = "any",
    ) -> SpeakerMatch | None:
        """cosine 유사도 1-NN. registered 우선 + model_id 격리. spec-02 §4-1."""
        self._validate_dim(embedding)

        def _sync() -> SpeakerMatch | None:
            conn = self._db

            def _best(orig_filter: str) -> SpeakerMatch | None:
                rows = conn.execute(
                    "SELECT * FROM speakers WHERE model_id=? AND origin=?",
                    (model_id, orig_filter),
                ).fetchall()
                best_sim, best_row = -2.0, None
                for r in rows:
                    c = self._get_centroid(conn, r["id"])
                    if c is None:
                        continue
                    sim = float(np.dot(embedding, c))
                    if sim > best_sim:
                        best_sim, best_row = sim, r
                if best_row is not None and best_sim >= threshold:
                    return SpeakerMatch(_to_speaker(best_row), best_sim, best_row["origin"])
                return None

            if origin == "any":
                result = _best("registered")
                return result if result is not None else _best("stored")
            return _best(origin)

        return await asyncio.to_thread(_sync)

    async def save(
        self, name: str | None, embedding: np.ndarray, model_id: str
    ) -> Speaker:
        """origin=stored 저장. name=None 이면 anon_NNN 자동 생성. spec-02 §4-4."""
        self._validate_dim(embedding)
        now = time.time()

        def _sync() -> Speaker:
            if name is None:
                actual_name = f"anon_{self._anon_counter:03d}"
                self._anon_counter += 1
            else:
                actual_name = name
            sid = str(uuid4())
            conn = self._db
            conn.execute(
                "INSERT INTO speakers VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, actual_name, "stored", embedding.shape[0], model_id, None, now, now, 1),
            )
            conn.execute(
                "INSERT INTO speaker_embeddings(speaker_id, embedding) VALUES (?,?)",
                (sid, _emb_to_blob(embedding)),
            )
            self._upsert_centroid(conn, sid, _l2_normalize(embedding.copy()))
            conn.commit()
            return _to_speaker(
                conn.execute("SELECT * FROM speakers WHERE id=?", (sid,)).fetchone()
            )

        return await asyncio.to_thread(_sync)

    async def list_all(self, model_id: str | None = None) -> AsyncIterator[Speaker]:
        """model_id=None 이면 전체. 지정 시 해당 model_id 만."""
        def _sync() -> list[Speaker]:
            conn = self._db
            if model_id is None:
                rows = conn.execute("SELECT * FROM speakers").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM speakers WHERE model_id=?", (model_id,)
                ).fetchall()
            return [_to_speaker(r) for r in rows]

        for sp in await asyncio.to_thread(_sync):
            yield sp

    async def set_alias(self, speaker_id: UUID, name: str) -> Speaker:
        """speaker.name 갱신. UNIQUE(name, model_id) 위반 시 IntegrityError."""
        sid = str(speaker_id)

        def _sync() -> Speaker:
            conn = self._db
            row = conn.execute("SELECT * FROM speakers WHERE id=?", (sid,)).fetchone()
            if row is None:
                raise ValueError(f"speaker {speaker_id} not found")
            try:
                conn.execute("UPDATE speakers SET name=? WHERE id=?", (name, sid))
                conn.commit()
            except sqlite3.IntegrityError as e:
                conn.rollback()
                raise IntegrityError(
                    f"UNIQUE(name, model_id) 위반: ({name!r}, {row['model_id']!r})"
                ) from e
            return _to_speaker(
                conn.execute("SELECT * FROM speakers WHERE id=?", (sid,)).fetchone()
            )

        return await asyncio.to_thread(_sync)

    async def merge(self, source_id: UUID, target_id: UUID) -> Speaker:
        """source → target 합산. source DELETE. target centroid 재계산. spec-02 §4-3."""
        src, tgt = str(source_id), str(target_id)

        def _sync() -> Speaker:
            conn = self._db
            sr = conn.execute("SELECT * FROM speakers WHERE id=?", (src,)).fetchone()
            if sr is None:
                raise ValueError(f"source speaker {source_id} not found")
            tr = conn.execute("SELECT * FROM speakers WHERE id=?", (tgt,)).fetchone()
            if tr is None:
                raise ValueError(f"target speaker {target_id} not found")

            # source embeddings → target (FK CASCADE 는 DELETE 시 동작)
            conn.execute(
                "UPDATE speaker_embeddings SET speaker_id=? WHERE speaker_id=?", (tgt, src)
            )
            new_cnt = tr["utterance_count"] + sr["utterance_count"]
            first_seen = min(tr["first_seen"], sr["first_seen"])
            last_seen = max(tr["last_seen"], sr["last_seen"])
            conn.execute(
                "UPDATE speakers SET utterance_count=?, first_seen=?, last_seen=? WHERE id=?",
                (new_cnt, first_seen, last_seen, tgt),
            )
            blobs = conn.execute(
                "SELECT embedding FROM speaker_embeddings WHERE speaker_id=?", (tgt,)
            ).fetchall()
            embs = [_blob_to_emb(b["embedding"]) for b in blobs]
            self._upsert_centroid(conn, tgt, _compute_centroid(embs))
            self._delete_centroid(conn, src)
            conn.execute("DELETE FROM speakers WHERE id=?", (src,))
            conn.commit()
            return _to_speaker(
                conn.execute("SELECT * FROM speakers WHERE id=?", (tgt,)).fetchone()
            )

        return await asyncio.to_thread(_sync)

    async def delete(self, speaker_id: UUID) -> None:
        """speaker 행 + centroid 삭제. 없으면 ValueError."""
        sid = str(speaker_id)

        def _sync() -> None:
            conn = self._db
            if not conn.execute("SELECT id FROM speakers WHERE id=?", (sid,)).fetchone():
                raise ValueError(f"speaker {speaker_id} not found")
            self._delete_centroid(conn, sid)
            conn.execute("DELETE FROM speakers WHERE id=?", (sid,))
            conn.commit()

        await asyncio.to_thread(_sync)


__all__ = ["SqliteVecStore"]
