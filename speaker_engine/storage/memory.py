"""MemoryStore — in-process dict + numpy 기본 백엔드 (spec-02 §3-4)."""

from __future__ import annotations

import time
from typing import AsyncIterator, Literal
from uuid import UUID, uuid4

import numpy as np

from speaker_engine.exceptions import IntegrityError
from speaker_engine.storage.base import SpeakerMatch
from speaker_engine.types import Speaker


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    if norm == 0.0:
        raise ValueError("zero vector — L2 정규화 불가")
    return v / norm


def _compute_centroid(embeddings: list[np.ndarray]) -> np.ndarray:
    """mean(embeddings) → L2 normalize — spec-02 §4-3."""
    centroid = np.mean(embeddings, axis=0)
    return _l2_normalize(centroid)


class MemoryStore:
    """in-process dict + numpy. 영속화 X — process 종료 시 휘발. spec-02 §3-4."""

    def __init__(self) -> None:
        self._speakers: dict[UUID, Speaker] = {}
        self._embeddings: dict[UUID, list[np.ndarray]] = {}
        self._centroids: dict[UUID, np.ndarray] = {}
        self._anon_counter: int = 1
        self._embedding_dim: int | None = None
        self._model_id: str | None = None

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _validate_dim(self, embedding: np.ndarray) -> None:
        if self._embedding_dim is not None and embedding.shape[0] != self._embedding_dim:
            raise ValueError(
                f"embedding dim {embedding.shape[0]} != expected {self._embedding_dim}"
            )

    def _find_by_name_model(self, name: str, model_id: str) -> UUID | None:
        for sid, sp in self._speakers.items():
            if sp.name == name and sp.model_id == model_id:
                return sid
        return None

    def _best_match(
        self,
        embedding: np.ndarray,
        candidates: list[tuple[UUID, Speaker]],
        threshold: float,
    ) -> SpeakerMatch | None:
        """centroid 1-NN cosine (dot product, L2 normalized 가정). spec-02 §4-1."""
        best_sim = -2.0
        best_sp: Speaker | None = None
        for sid, sp in candidates:
            centroid = self._centroids.get(sid)
            if centroid is None:
                continue
            sim = float(np.dot(embedding, centroid))
            if sim > best_sim:
                best_sim = sim
                best_sp = sp
        if best_sp is not None and best_sim >= threshold:
            return SpeakerMatch(
                speaker=best_sp,
                cosine_similarity=best_sim,
                origin=best_sp.origin,  # type: ignore[arg-type]
            )
        return None

    # ------------------------------------------------------------------
    # SpeakerStore Protocol 8 메서드
    # ------------------------------------------------------------------

    async def init_schema(self, embedding_dim: int, model_id: str) -> None:
        """no-op (in-memory) — embedding_dim / model_id 박제. spec-02 §3-4."""
        self._embedding_dim = embedding_dim
        self._model_id = model_id

    async def register(
        self,
        name: str,
        embedding: np.ndarray,
        model_id: str,
    ) -> Speaker:
        """origin=registered 저장. 동일 (name, model_id) 존재 시 embedding upsert + centroid 재계산."""
        self._validate_dim(embedding)
        now = time.time()
        existing_id = self._find_by_name_model(name, model_id)

        if existing_id is not None:
            self._embeddings[existing_id].append(embedding)
            self._centroids[existing_id] = _compute_centroid(self._embeddings[existing_id])
            old = self._speakers[existing_id]
            updated = Speaker(
                id=old.id,
                name=old.name,
                origin=old.origin,
                embedding_dim=old.embedding_dim,
                model_id=old.model_id,
                registered_at=old.registered_at or now,
                first_seen=old.first_seen,
                last_seen=now,
                utterance_count=old.utterance_count + 1,
            )
            self._speakers[existing_id] = updated
            return updated

        sid = uuid4()
        speaker = Speaker(
            id=sid,
            name=name,
            origin="registered",
            embedding_dim=embedding.shape[0],
            model_id=model_id,
            registered_at=now,
            first_seen=now,
            last_seen=now,
            utterance_count=1,
        )
        self._speakers[sid] = speaker
        self._embeddings[sid] = [embedding.copy()]
        self._centroids[sid] = _l2_normalize(embedding.copy())
        return speaker

    async def find_match(
        self,
        embedding: np.ndarray,
        model_id: str,
        threshold: float,
        origin: Literal["registered", "stored", "any"] = "any",
    ) -> SpeakerMatch | None:
        """cosine 유사도 1-NN. origin 우선순위 + model_id 격리. spec-02 §4-1."""
        self._validate_dim(embedding)

        registered = [
            (sid, sp)
            for sid, sp in self._speakers.items()
            if sp.model_id == model_id and sp.origin == "registered"
        ]
        stored = [
            (sid, sp)
            for sid, sp in self._speakers.items()
            if sp.model_id == model_id and sp.origin == "stored"
        ]

        if origin == "any":
            result = self._best_match(embedding, registered, threshold)
            if result is not None:
                return result
            return self._best_match(embedding, stored, threshold)
        elif origin == "registered":
            return self._best_match(embedding, registered, threshold)
        else:  # "stored"
            return self._best_match(embedding, stored, threshold)

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
        now = time.time()
        sid = uuid4()
        speaker = Speaker(
            id=sid,
            name=name,
            origin="stored",
            embedding_dim=embedding.shape[0],
            model_id=model_id,
            registered_at=None,
            first_seen=now,
            last_seen=now,
            utterance_count=1,
        )
        self._speakers[sid] = speaker
        self._embeddings[sid] = [embedding.copy()]
        self._centroids[sid] = _l2_normalize(embedding.copy())
        return speaker

    async def list_all(self, model_id: str | None = None) -> AsyncIterator[Speaker]:
        """model_id=None 이면 전체. 지정 시 해당 model_id 만."""
        for sp in list(self._speakers.values()):
            if model_id is None or sp.model_id == model_id:
                yield sp

    async def set_alias(self, speaker_id: UUID, name: str) -> Speaker:
        """speaker.name 갱신. UNIQUE(name, model_id) 위반 시 IntegrityError."""
        if speaker_id not in self._speakers:
            raise ValueError(f"speaker {speaker_id} not found")
        sp = self._speakers[speaker_id]
        for sid, other in self._speakers.items():
            if sid != speaker_id and other.name == name and other.model_id == sp.model_id:
                raise IntegrityError(
                    f"UNIQUE(name, model_id) 위반: ({name!r}, {sp.model_id!r}) 이미 존재"
                )
        updated = Speaker(
            id=sp.id,
            name=name,
            origin=sp.origin,
            embedding_dim=sp.embedding_dim,
            model_id=sp.model_id,
            registered_at=sp.registered_at,
            first_seen=sp.first_seen,
            last_seen=sp.last_seen,
            utterance_count=sp.utterance_count,
        )
        self._speakers[speaker_id] = updated
        return updated

    async def merge(self, source_id: UUID, target_id: UUID) -> Speaker:
        """source → target 합산. source DELETE. target centroid 재계산. spec-02 §4-3."""
        if source_id not in self._speakers:
            raise ValueError(f"source speaker {source_id} not found")
        source = self._speakers[source_id]
        target = self._speakers[target_id]

        self._embeddings[target_id] = (
            self._embeddings[target_id] + self._embeddings[source_id]
        )
        self._centroids[target_id] = _compute_centroid(self._embeddings[target_id])

        updated_target = Speaker(
            id=target.id,
            name=target.name,
            origin=target.origin,
            embedding_dim=target.embedding_dim,
            model_id=target.model_id,
            registered_at=target.registered_at,
            first_seen=min(target.first_seen, source.first_seen),
            last_seen=max(target.last_seen, source.last_seen),
            utterance_count=target.utterance_count + source.utterance_count,
        )
        self._speakers[target_id] = updated_target

        del self._speakers[source_id]
        del self._embeddings[source_id]
        del self._centroids[source_id]

        return updated_target

    async def delete(self, speaker_id: UUID) -> None:
        """speaker 행 + centroid 삭제. 없으면 ValueError. spec-02 §5."""
        if speaker_id not in self._speakers:
            raise ValueError(f"speaker {speaker_id} not found")
        del self._speakers[speaker_id]
        del self._embeddings[speaker_id]
        del self._centroids[speaker_id]


__all__ = ["MemoryStore"]
