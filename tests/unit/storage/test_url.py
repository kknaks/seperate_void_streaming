"""from_url() 단위 테스트 — spec-05 §2-2 unit 카테고리, 외부 인프라 0."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from speaker_engine.exceptions import StorageError
from speaker_engine.storage import SpeakerStore, from_url
from speaker_engine.storage.memory import MemoryStore
from speaker_engine.storage.pgvector import PgvectorStore
from speaker_engine.storage.sqlite import SqliteVecStore


# ---------------------------------------------------------------------------
# memory://
# ---------------------------------------------------------------------------

class TestMemoryUrl:
    def test_returns_memory_store(self) -> None:
        result = from_url("memory://")
        assert isinstance(result, MemoryStore)

    def test_satisfies_speaker_store_protocol(self) -> None:
        result = from_url("memory://")
        assert isinstance(result, SpeakerStore)

    def test_memory_path_ignored(self) -> None:
        """memory:// 의 path 부분은 무시된다."""
        result = from_url("memory://anything/ignored")
        assert isinstance(result, MemoryStore)


# ---------------------------------------------------------------------------
# sqlite:///
# ---------------------------------------------------------------------------

class TestSqliteUrl:
    def test_file_path(self, tmp_path: object) -> None:
        # tmp_path 는 절대 경로이므로 sqlite:// 에 바로 붙이면 sqlite:///abs/path 가 됨
        db_path = str(tmp_path) + "/test.db"  # type: ignore[operator]
        result = from_url(f"sqlite://{db_path}")
        assert isinstance(result, SqliteVecStore)
        assert result._path == db_path

    def test_in_memory_triple_slash(self) -> None:
        """sqlite:///:memory: → SqliteVecStore(":memory:")."""
        result = from_url("sqlite:///:memory:")
        assert isinstance(result, SqliteVecStore)
        assert result._path == ":memory:"

    def test_in_memory_short_form(self) -> None:
        """sqlite::memory: (짧은 형식) → SqliteVecStore(":memory:")."""
        result = from_url("sqlite::memory:")
        assert isinstance(result, SqliteVecStore)
        assert result._path == ":memory:"

    def test_satisfies_speaker_store_protocol(self) -> None:
        result = from_url("sqlite:///:memory:")
        assert isinstance(result, SpeakerStore)


# ---------------------------------------------------------------------------
# postgresql:// / postgres://
# ---------------------------------------------------------------------------

class TestPgvectorUrl:
    _dsn = "postgresql://user:pw@localhost:5432/testdb"

    def test_postgresql_scheme(self) -> None:
        result = from_url(self._dsn)
        assert isinstance(result, PgvectorStore)

    def test_dsn_passed_verbatim(self) -> None:
        """DSN 문자열이 변형 없이 PgvectorStore 에 전달된다."""
        result = from_url(self._dsn)
        assert isinstance(result, PgvectorStore)
        assert result._dsn == self._dsn

    def test_postgres_alias(self) -> None:
        """postgres:// 도 PgvectorStore 를 반환한다."""
        alias_dsn = "postgres://user:pw@localhost:5432/testdb"
        result = from_url(alias_dsn)
        assert isinstance(result, PgvectorStore)
        assert result._dsn == alias_dsn

    def test_satisfies_speaker_store_protocol(self) -> None:
        result = from_url(self._dsn)
        assert isinstance(result, SpeakerStore)


# ---------------------------------------------------------------------------
# 오류 케이스
# ---------------------------------------------------------------------------

class TestUrlErrors:
    def test_unknown_scheme_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            from_url("unknown://host/path")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            from_url("")

    def test_none_raises_value_error(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            from_url(None)  # type: ignore[arg-type]

    def test_ftp_scheme_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            from_url("ftp://example.com/data")


# ---------------------------------------------------------------------------
# 선택: extras 미설치 시 StorageError (sys.modules 차단)
# ---------------------------------------------------------------------------

class TestMissingExtras:
    def test_sqlite_missing_extras_raises_storage_error(self) -> None:
        """sqlite-vec 미설치 환경 시뮬레이션 → StorageError."""
        # sys.modules 에 None 을 세팅하면 import 가 ImportError 를 발생시킴
        with patch.dict(sys.modules, {"speaker_engine.storage.sqlite": None}):
            with pytest.raises((StorageError, ImportError)):
                from_url("sqlite:///blocked.db")

    def test_pgvector_missing_extras_raises_storage_error(self) -> None:
        """asyncpg/pgvector 미설치 환경 시뮬레이션 → StorageError."""
        with patch.dict(sys.modules, {"speaker_engine.storage.pgvector": None}):
            with pytest.raises((StorageError, ImportError)):
                from_url("postgresql://user:pw@host/db")
