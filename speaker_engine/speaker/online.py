"""OnlineSpeakerClustering wrapper — diart 래핑 (E-03, spec-04 §4.3)."""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

_LETTERS = "ABCDEFGHIJKLMNOPQRST"  # A~T, 20 letters (spec-04 §2-3)
_MAX_LETTER_IDX = len(_LETTERS) - 1  # 19

try:
    from diart.blocks.clustering import OnlineSpeakerClustering as _DiartOnlineClustering

    _DIART_OK = True
except (ImportError, AttributeError):
    _DIART_OK = False


class OnlineSpeakerClusterer:
    """diart OnlineSpeakerClustering 래퍼 — centroid state 단일 SOT (spec-04 §2-2).

    SpeakerEngine 이 1 instance 생성 후 DiartAdapter / Adaptive / Final / Identifier 와 공유.
    """

    def __init__(
        self,
        tau_active: float = 0.6,
        rho_update: float = 0.3,
        delta_new: float = 1.0,
        max_speakers: int = 20,
        metric: str = "cosine",
    ) -> None:
        if not _DIART_OK:
            raise ImportError("diart / pyannote.audio 를 import 할 수 없습니다.")

        self._max_speakers = max_speakers
        self._delta_new = delta_new
        self._inner = _DiartOnlineClustering(
            tau_active=tau_active,
            rho_update=rho_update,
            delta_new=delta_new,
            metric=metric,
            max_speakers=max_speakers,
        )

    def identify(
        self,
        segmentation: object,
        embeddings: np.ndarray,
    ) -> object:
        """diart identify() 위임.

        segmentation: .data attribute 를 가진 객체 (_SegWrapper 등).
        embeddings: shape (num_local_speakers, D), L2 normalized.
        """
        centers = self.centers
        if (
            centers is not None
            and isinstance(embeddings, np.ndarray)
            and embeddings.ndim == 2
            and embeddings.shape[1] != centers.shape[1]
        ):
            raise ValueError(
                f"embeddings D={embeddings.shape[1]} 와 centroids D={centers.shape[1]} 불일치"
            )

        active = self.active_centers
        if len(active) >= self._max_speakers:
            logger.warning(
                "OnlineSpeakerClusterer: active_centers=%d >= max_speakers=%d — 강제 매핑 발생",
                len(active),
                self._max_speakers,
            )

        return self._inner.identify(segmentation, embeddings)

    @property
    def centers(self) -> np.ndarray | None:
        """active centroid 행렬, shape (max_speakers, D). 초기화 전이면 None."""
        c = getattr(self._inner, "centers", None)
        if c is None:
            return None
        if isinstance(c, np.ndarray) and c.size == 0:
            return None
        return c

    @property
    def active_centers(self) -> set[int]:
        """현재 활성 global centroid id 집합."""
        ac = getattr(self._inner, "active_centers", None)
        if ac is None:
            return set()
        return set(ac)

    @property
    def delta_new(self) -> float:
        """Adaptive scheduler 의 threshold guard 가 사용 (spec-04 §4.4)."""
        return self._delta_new

    @staticmethod
    def idx_to_letter(idx: int) -> str:
        """0 → 'auto:A', 1 → 'auto:B', ..., 19 → 'auto:T'."""
        if not (0 <= idx <= _MAX_LETTER_IDX):
            raise ValueError(f"idx={idx} 는 유효 범위 0~{_MAX_LETTER_IDX} 가 아닙니다.")
        return f"auto:{_LETTERS[idx]}"

    @staticmethod
    def letter_to_idx(letter: str) -> int:
        """'auto:A' → 0. invalid letter → ValueError."""
        if not isinstance(letter, str) or not letter.startswith("auto:") or len(letter) != 6:
            raise ValueError(f"letter={letter!r} 는 'auto:X' 형식이 아닙니다.")
        ch = letter[5]
        idx = _LETTERS.find(ch)
        if idx == -1:
            raise ValueError(f"letter={letter!r} 는 유효 범위 'auto:A'~'auto:T' 가 아닙니다.")
        return idx


__all__ = ["OnlineSpeakerClusterer"]
