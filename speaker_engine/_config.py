"""환경 변수 로딩 — HF_TOKEN / SPEAKER_ENGINE_STORAGE_URL (F-04)."""

import os
import re
from dataclasses import dataclass

HF_TOKEN_ENV = "HF_TOKEN"
STORAGE_URL_ENV = "SPEAKER_ENGINE_STORAGE_URL"

_ALLOWED_SCHEME_RE = re.compile(
    r"^(memory://|sqlite:///|postgresql://|postgres://)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EngineConfig:
    """Resolved runtime config. Produced by load_engine_config()."""
    hf_token: str
    storage_url: str


def load_engine_config(
    storage_url: str | None = None,
    hf_token: str | None = None,
) -> EngineConfig:
    """Resolve hf_token and storage_url from args (priority) or env fallback.

    Raises
    ------
    EnvironmentError
        If a required value is absent from both argument and env
        (empty-string env is treated as absent for hf_token).
    ValueError
        If storage_url scheme is not in the allowed whitelist.
    """
    resolved_token = _resolve(hf_token, HF_TOKEN_ENV, treat_empty_as_missing=True)
    resolved_url = _resolve(storage_url, STORAGE_URL_ENV, treat_empty_as_missing=False)
    _validate_storage_scheme(resolved_url)
    return EngineConfig(hf_token=resolved_token, storage_url=resolved_url)


def _resolve(arg: str | None, env_name: str, *, treat_empty_as_missing: bool) -> str:
    if arg is not None:
        return arg
    value = os.environ.get(env_name)
    if value is None or (treat_empty_as_missing and value == ""):
        raise EnvironmentError(
            f"{env_name!r} is required. "
            f"Provide it as an argument or set the {env_name!r} environment variable."
        )
    return value


def _validate_storage_scheme(url: str) -> None:
    if not _ALLOWED_SCHEME_RE.match(url):
        raise ValueError(
            f"Unsupported storage URL scheme in {url!r}. "
            "Allowed schemes: memory://, sqlite:///, postgresql://, postgres://"
        )
