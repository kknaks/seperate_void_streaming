"""URL parser — SPEAKER_ENGINE_STORAGE_URL → backend instance factory (S-05, adr-03)."""

from __future__ import annotations

from urllib.parse import urlparse

from speaker_engine.exceptions import StorageError
from speaker_engine.storage.base import SpeakerStore
from speaker_engine.storage.memory import MemoryStore


def from_url(url: str) -> SpeakerStore:
    """Parse a storage URL and return the matching SpeakerStore instance.

    URL 스킴 → backend 매핑 (adr-03):
      memory://        → MemoryStore()
      sqlite:///path   → SqliteVecStore(path)
      sqlite:///:memory: → SqliteVecStore(":memory:")
      postgresql://... → PgvectorStore(dsn=url)
      postgres://...   → PgvectorStore(dsn=url)

    backend 인스턴스만 생성 — init_schema 는 SpeakerEngine 책임 (spec-02 §6).

    Raises
    ------
    ValueError
        빈/None URL 또는 알 수 없는 스킴.
    StorageError
        필요한 extras 패키지 미설치.
    """
    if not url:
        raise ValueError("storage URL must not be empty")

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme == "memory":
        return MemoryStore()

    if scheme == "sqlite":
        return _make_sqlite(parsed.path)

    if scheme in ("postgresql", "postgres"):
        return _make_pgvector(url)

    raise ValueError(
        f"Unsupported storage URL scheme {scheme!r} in {url!r}. "
        "Allowed: memory://, sqlite:///, postgresql://, postgres://"
    )


def _make_sqlite(path: str) -> SpeakerStore:
    try:
        from speaker_engine.storage.sqlite import SqliteVecStore  # lazy — extras guard
    except ImportError as exc:
        raise StorageError(
            f"sqlite-vec 패키지가 설치되어 있지 않습니다. "
            f'pip install "speaker_engine[sqlite]" ({exc})'
        ) from exc

    # sqlite:///:memory: → parsed.path "/:memory:", sqlite::memory: → ":memory:"
    if path in ("/:memory:", ":memory:"):
        return SqliteVecStore(":memory:")
    return SqliteVecStore(path)


def _make_pgvector(url: str) -> SpeakerStore:
    try:
        from speaker_engine.storage.pgvector import PgvectorStore  # lazy — extras guard
    except ImportError as exc:
        raise StorageError(
            f"asyncpg/pgvector 패키지가 설치되어 있지 않습니다. "
            f'pip install "speaker_engine[pgvector]" ({exc})'
        ) from exc

    return PgvectorStore(dsn=url)


__all__ = ["from_url"]
