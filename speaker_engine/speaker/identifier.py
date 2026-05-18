"""Identifier — 3-tier 매칭 + L2 정규화 강제 (spec-04 §4.2 + §4.6)."""

from __future__ import annotations

import logging

import numpy as np

from speaker_engine.storage.base import SpeakerStore
from speaker_engine.types import Speaker

logger = logging.getLogger(__name__)


class Identifier:
    """3-tier 화자 매칭 + L2 정규화 강제 (spec-04 §4.2, planning-02 §41).

    Tier 1: registered dict (in-memory, cosine ≥ registered_threshold=0.70)
    Tier 2: SpeakerStore.find_match(origin="stored", cosine ≥ stored_threshold=0.75)
    Tier 3: fallback → ("", None) — 호출처가 auto letter 부여 책임

    state: registered_embeddings dict (init 시점 normalize + 보관, immutable).
    Storage 닿는 호출만 async (spec-04 §4.6).
    """

    def __init__(
        self,
        store: SpeakerStore,
        model_id: str,
        registered_speakers: dict[str, np.ndarray] | None = None,
        registered_threshold: float = 0.70,
        stored_threshold: float = 0.75,
    ) -> None:
        self._store = store
        self._model_id = model_id
        self._registered_threshold = registered_threshold
        self._stored_threshold = stored_threshold

        # init 시점 1회 normalize + 보관 (매 호출 재정규화 회피, spec-04 §4.2)
        if registered_speakers:
            self._registered: dict[str, np.ndarray] = {
                name: self.normalize(emb)
                for name, emb in registered_speakers.items()
            }
        else:
            self._registered = {}

    # ------------------------------------------------------------------
    # L2 정규화 (static, sync)
    # ------------------------------------------------------------------

    @staticmethod
    def normalize(embedding: np.ndarray) -> np.ndarray:
        """L2 normalize. zero vector → ValueError. NaN → ValueError.

        Args:
            embedding: 1-d ndarray shape (D,).

        Returns:
            L2 normalized ndarray, same shape.
        """
        if not isinstance(embedding, np.ndarray) or embedding.ndim != 1:
            raise ValueError(
                f"embedding must be 1-d ndarray, got shape {getattr(embedding, 'shape', '?')}"
            )
        if np.isnan(embedding).any():
            raise ValueError("embedding contains NaN — 입력 오류")
        norm = float(np.linalg.norm(embedding))
        if norm == 0.0:
            raise ValueError("zero vector — L2 정규화 불가 (spec-04 §4.2)")
        return embedding / norm

    # ------------------------------------------------------------------
    # 3-tier 매칭 (async — Storage I/O 포함, spec-04 §4.6)
    # ------------------------------------------------------------------

    async def match(
        self,
        embedding: np.ndarray,  # D-dim, 이미 L2 normalized (호출처 책임)
    ) -> tuple[str, Speaker | None]:
        """3-tier 화자 매칭 (spec-04 §4.2, planning-02 §41).

        Args:
            embedding: L2 normalized utterance mean embedding (D-dim 1-d ndarray).
                호출처(SpeakerEngine)가 normalize() 후 전달하는 것이 권장 정책.
                shape 불일치 또는 dim 불일치 시 ValueError.

        Returns:
            (label, Speaker | None).
            - Tier 1 hit: ("registered:<name>", Speaker 없음 → None)
            - Tier 2 hit: ("stored:<name>", Speaker)
            - Tier 3 fallback: ("", None)

        Raises:
            ValueError: shape 불일치 (1-d 아님 / registered dict dim 불일치).
            SpeakerStore 예외는 wrap 없이 그대로 전파.
        """
        if not isinstance(embedding, np.ndarray) or embedding.ndim != 1:
            raise ValueError(
                f"embedding must be 1-d ndarray, got shape {getattr(embedding, 'shape', '?')}"
            )

        # Tier 1 — registered dict (in-memory, sync path)
        if self._registered:
            label, speaker = self._match_registered(embedding)
            if label:
                return label, speaker

        # Tier 2 — SpeakerStore stored 검색 (async I/O)
        match = await self._store.find_match(
            embedding=embedding,
            model_id=self._model_id,
            threshold=self._stored_threshold,
            origin="stored",
        )
        if match is not None:
            return f"stored:{match.speaker.name}", match.speaker

        # Tier 3 — auto fallback
        return "", None

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _match_registered(
        self, embedding: np.ndarray
    ) -> tuple[str, None]:
        """registered dict brute-force cosine 최대 매칭.

        Returns:
            ("registered:<name>", None) if hit, ("", None) if miss.

        Raises:
            ValueError: embedding dim 불일치.
        """
        best_sim = -2.0
        best_name: str | None = None

        for name, reg_emb in self._registered.items():
            if reg_emb.shape[0] != embedding.shape[0]:
                raise ValueError(
                    f"embedding dim {embedding.shape[0]} != "
                    f"registered '{name}' dim {reg_emb.shape[0]}"
                )
            sim = float(np.dot(reg_emb, embedding))
            if sim > best_sim:
                best_sim = sim
                best_name = name

        if best_name is not None and best_sim >= self._registered_threshold:
            return f"registered:{best_name}", None
        return "", None


__all__ = ["Identifier"]
