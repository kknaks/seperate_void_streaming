"""unit tests — speaker_engine._config (F-04)."""

import pytest

from speaker_engine._config import (
    HF_TOKEN_ENV,
    STORAGE_URL_ENV,
    EngineConfig,
    load_engine_config,
)

_VALID_MEMORY = "memory://"
_VALID_SQLITE = "sqlite:///path/to/db.sqlite"
_VALID_PG = "postgresql://user:pw@host/db"
_VALID_PG_ALIAS = "postgres://user:pw@host/db"
_FAKE_TOKEN = "hf_test_token"


# ── 환경 격리 픽스처 ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """각 테스트 전 대상 env 변수 제거 — 격리 보장."""
    monkeypatch.delenv(HF_TOKEN_ENV, raising=False)
    monkeypatch.delenv(STORAGE_URL_ENV, raising=False)


# ── 인자 vs env 우선순위 (hf_token) ────────────────────────────────────────


class TestHfTokenResolution:
    def test_arg_used_when_env_absent(self, monkeypatch):
        monkeypatch.setenv(STORAGE_URL_ENV, _VALID_MEMORY)
        cfg = load_engine_config(storage_url=_VALID_MEMORY, hf_token=_FAKE_TOKEN)
        assert cfg.hf_token == _FAKE_TOKEN

    def test_env_used_when_arg_none(self, monkeypatch):
        monkeypatch.setenv(HF_TOKEN_ENV, _FAKE_TOKEN)
        monkeypatch.setenv(STORAGE_URL_ENV, _VALID_MEMORY)
        cfg = load_engine_config(storage_url=_VALID_MEMORY, hf_token=None)
        assert cfg.hf_token == _FAKE_TOKEN

    def test_arg_wins_over_env(self, monkeypatch):
        monkeypatch.setenv(HF_TOKEN_ENV, "env_token")
        monkeypatch.setenv(STORAGE_URL_ENV, _VALID_MEMORY)
        cfg = load_engine_config(storage_url=_VALID_MEMORY, hf_token="arg_token")
        assert cfg.hf_token == "arg_token"

    def test_raises_when_both_absent(self):
        with pytest.raises(EnvironmentError, match=HF_TOKEN_ENV):
            load_engine_config(storage_url=_VALID_MEMORY, hf_token=None)

    def test_empty_string_env_treated_as_missing(self, monkeypatch):
        monkeypatch.setenv(HF_TOKEN_ENV, "")
        with pytest.raises(EnvironmentError, match=HF_TOKEN_ENV):
            load_engine_config(storage_url=_VALID_MEMORY, hf_token=None)


# ── 인자 vs env 우선순위 (storage_url) ─────────────────────────────────────


class TestStorageUrlResolution:
    def test_arg_used_when_env_absent(self):
        cfg = load_engine_config(storage_url=_VALID_MEMORY, hf_token=_FAKE_TOKEN)
        assert cfg.storage_url == _VALID_MEMORY

    def test_env_used_when_arg_none(self, monkeypatch):
        monkeypatch.setenv(STORAGE_URL_ENV, _VALID_MEMORY)
        cfg = load_engine_config(storage_url=None, hf_token=_FAKE_TOKEN)
        assert cfg.storage_url == _VALID_MEMORY

    def test_arg_wins_over_env(self, monkeypatch):
        monkeypatch.setenv(STORAGE_URL_ENV, "memory://env")
        cfg = load_engine_config(storage_url=_VALID_SQLITE, hf_token=_FAKE_TOKEN)
        assert cfg.storage_url == _VALID_SQLITE

    def test_raises_when_both_absent(self):
        with pytest.raises(EnvironmentError, match=STORAGE_URL_ENV):
            load_engine_config(storage_url=None, hf_token=_FAKE_TOKEN)


# ── URL 스킴 화이트리스트 ───────────────────────────────────────────────────


class TestStorageUrlSchemeValidation:
    @pytest.mark.parametrize("url", [
        _VALID_MEMORY,
        _VALID_SQLITE,
        _VALID_PG,
        _VALID_PG_ALIAS,
        "sqlite:///relative/path.db",
        "postgresql://localhost/mydb",
        "postgres://localhost/mydb",
    ])
    def test_allowed_schemes_pass(self, url):
        cfg = load_engine_config(storage_url=url, hf_token=_FAKE_TOKEN)
        assert cfg.storage_url == url

    @pytest.mark.parametrize("url", [
        "file:///path/to/db",
        "mysql://user:pw@host/db",
        "redis://localhost",
        "http://example.com",
        "sqlite://path",   # sqlite:// 는 허용 목록에 없음 (sqlite:/// 이어야 함)
        "",
        "not_a_url",
    ])
    def test_disallowed_schemes_raise_value_error(self, url):
        with pytest.raises(ValueError, match="Unsupported storage URL scheme"):
            load_engine_config(storage_url=url, hf_token=_FAKE_TOKEN)


# ── EngineConfig 반환 타입 ──────────────────────────────────────────────────


class TestEngineConfigDataclass:
    def test_returns_engine_config(self):
        cfg = load_engine_config(storage_url=_VALID_MEMORY, hf_token=_FAKE_TOKEN)
        assert isinstance(cfg, EngineConfig)

    def test_config_is_frozen(self):
        from dataclasses import FrozenInstanceError

        cfg = load_engine_config(storage_url=_VALID_MEMORY, hf_token=_FAKE_TOKEN)
        with pytest.raises(FrozenInstanceError):
            cfg.hf_token = "other"  # type: ignore[misc]

    def test_fields_accessible(self):
        cfg = load_engine_config(storage_url=_VALID_SQLITE, hf_token=_FAKE_TOKEN)
        assert cfg.hf_token == _FAKE_TOKEN
        assert cfg.storage_url == _VALID_SQLITE
