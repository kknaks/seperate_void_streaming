"""SpeakerStore Protocol + SpeakerMatch 반환 타입 — spec-02 §2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal, Protocol, runtime_checkable
from uuid import UUID

import numpy as np

from speaker_engine.types import Speaker


@dataclass(frozen=True)
class SpeakerMatch:
    """find_match 반환 타입. cosine 유사도 + 매칭된 speaker."""

    speaker: Speaker
    cosine_similarity: float
    origin: Literal["registered", "stored"]


@runtime_checkable
class SpeakerStore(Protocol):
    """SpeakerStore 추상 인터페이스 — spec-02 §2. 8 async 메서드."""

    async def init_schema(
        self,
        embedding_dim: int,
        model_id: str,
    ) -> None:
        """DDL 실행 + 마이그레이션 v1 적용. 세션 시작 전 1회."""
        ...

    async def register(
        self,
        name: str,
        embedding: np.ndarray,   # D-dim, L2 normalized
        model_id: str,
    ) -> Speaker:
        """origin=registered 로 저장. 동일 (name, model_id) 존재 시 embedding upsert + centroid 재계산."""
        ...

    async def find_match(
        self,
        embedding: np.ndarray,   # D-dim, L2 normalized
        model_id: str,
        threshold: float,
        origin: Literal["registered", "stored", "any"] = "any",
    ) -> SpeakerMatch | None:
        """cosine 유사도 기준 가장 유사한 speaker 반환. threshold 미만이면 None."""
        ...

    async def save(
        self,
        name: str | None,        # None 이면 anon_NNN 자동 생성
        embedding: np.ndarray,   # D-dim, L2 normalized
        model_id: str,
    ) -> Speaker:
        """origin=stored 로 저장. name=None 이면 anon_NNN 자동 생성. centroid 재계산."""
        ...

    async def list_all(
        self,
        model_id: str | None = None,
    ) -> AsyncIterator[Speaker]:
        """model_id=None 이면 전체. 지정 시 해당 model_id 만."""
        ...

    async def set_alias(
        self,
        speaker_id: UUID,
        name: str,
    ) -> Speaker:
        """speaker.name 갱신. 동일 (name, model_id) 이미 존재 시 IntegrityError."""
        ...

    async def merge(
        self,
        source_id: UUID,
        target_id: UUID,
    ) -> Speaker:
        """source → target 합산. source DELETE. target centroid 재계산."""
        ...

    async def delete(
        self,
        speaker_id: UUID,
    ) -> None:
        """speakers 행 + speaker_centroids 행 삭제."""
        ...


__all__ = ["SpeakerMatch", "SpeakerStore"]
