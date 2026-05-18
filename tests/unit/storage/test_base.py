"""SpeakerMatch + SpeakerStore Protocol 단위 테스트 — spec-05 §2-2."""

from __future__ import annotations

import uuid
from typing import AsyncIterator, Literal
from uuid import UUID

import numpy as np
import pytest

from speaker_engine.storage import SpeakerMatch, SpeakerStore
from speaker_engine.types import Speaker


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_speaker(origin: Literal["registered", "stored"] = "stored") -> Speaker:
    return Speaker(
        id=uuid.uuid4(),
        name="alice",
        origin=origin,
        embedding_dim=4,
        model_id="pyannote/embedding",
        registered_at=None,
        first_seen=0.0,
        last_seen=1.0,
        utterance_count=1,
    )


# ---------------------------------------------------------------------------
# SpeakerMatch 테스트
# ---------------------------------------------------------------------------

class TestSpeakerMatch:
    def test_create_and_field_access(self) -> None:
        sp = _make_speaker("registered")
        m = SpeakerMatch(speaker=sp, cosine_similarity=0.85, origin="registered")
        assert m.speaker is sp
        assert m.cosine_similarity == 0.85
        assert m.origin == "registered"

    def test_frozen_raises_on_mutation(self) -> None:
        m = SpeakerMatch(speaker=_make_speaker(), cosine_similarity=0.7, origin="stored")
        with pytest.raises((AttributeError, TypeError)):
            m.cosine_similarity = 0.9  # type: ignore[misc]

    def test_origin_registered(self) -> None:
        m = SpeakerMatch(speaker=_make_speaker("registered"), cosine_similarity=0.9, origin="registered")
        assert m.origin == "registered"

    def test_origin_stored(self) -> None:
        m = SpeakerMatch(speaker=_make_speaker("stored"), cosine_similarity=0.8, origin="stored")
        assert m.origin == "stored"

    def test_equality(self) -> None:
        sp = _make_speaker()
        m1 = SpeakerMatch(speaker=sp, cosine_similarity=0.75, origin="stored")
        m2 = SpeakerMatch(speaker=sp, cosine_similarity=0.75, origin="stored")
        assert m1 == m2


# ---------------------------------------------------------------------------
# SpeakerStore Protocol — mock 구현체
# ---------------------------------------------------------------------------

class _FullImpl:
    """8 메서드 모두 구현 — Protocol 준수 mock."""

    async def init_schema(self, embedding_dim: int, model_id: str) -> None:
        ...

    async def register(self, name: str, embedding: np.ndarray, model_id: str) -> Speaker:
        return _make_speaker("registered")

    async def find_match(
        self,
        embedding: np.ndarray,
        model_id: str,
        threshold: float,
        origin: Literal["registered", "stored", "any"] = "any",
    ) -> SpeakerMatch | None:
        return None

    async def save(self, name: str | None, embedding: np.ndarray, model_id: str) -> Speaker:
        return _make_speaker("stored")

    async def list_all(self, model_id: str | None = None) -> AsyncIterator[Speaker]:
        async def _empty() -> AsyncIterator[Speaker]:
            return
            yield  # type: ignore[misc]  # makes function an async generator
        return _empty()

    async def set_alias(self, speaker_id: UUID, name: str) -> Speaker:
        return _make_speaker()

    async def merge(self, source_id: UUID, target_id: UUID) -> Speaker:
        return _make_speaker()

    async def delete(self, speaker_id: UUID) -> None:
        ...


class _MissingDeleteImpl:
    """delete 메서드 없음 — Protocol 위반 mock."""

    async def init_schema(self, embedding_dim: int, model_id: str) -> None: ...
    async def register(self, name: str, embedding: np.ndarray, model_id: str) -> Speaker: ...  # type: ignore[return]
    async def find_match(self, embedding: np.ndarray, model_id: str, threshold: float, origin: Literal["registered", "stored", "any"] = "any") -> SpeakerMatch | None: ...
    async def save(self, name: str | None, embedding: np.ndarray, model_id: str) -> Speaker: ...  # type: ignore[return]
    async def list_all(self, model_id: str | None = None) -> AsyncIterator[Speaker]: ...  # type: ignore[return]
    async def set_alias(self, speaker_id: UUID, name: str) -> Speaker: ...  # type: ignore[return]
    async def merge(self, source_id: UUID, target_id: UUID) -> Speaker: ...  # type: ignore[return]
    # delete 없음 — Protocol 위반


# ---------------------------------------------------------------------------
# SpeakerStore Protocol 테스트
# ---------------------------------------------------------------------------

class TestSpeakerStoreProtocol:
    def test_full_impl_isinstance(self) -> None:
        assert isinstance(_FullImpl(), SpeakerStore)

    def test_missing_method_not_isinstance(self) -> None:
        assert not isinstance(_MissingDeleteImpl(), SpeakerStore)

    def test_all_8_methods_present(self) -> None:
        expected = {
            "init_schema", "register", "find_match", "save",
            "list_all", "set_alias", "merge", "delete",
        }
        actual = {name for name in dir(SpeakerStore) if not name.startswith("_")}
        assert expected <= actual

    def test_find_match_default_origin_any(self) -> None:
        import inspect
        sig = inspect.signature(_FullImpl.find_match)
        assert sig.parameters["origin"].default == "any"
