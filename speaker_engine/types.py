"""공개 데이터 타입 정의 — SpeakerSegment / LabelChange / Speaker 등."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import numpy as np

# 라벨 변경 이유. LabelChange.reason 에서 사용.
LabelReason = Literal["recluster", "stored_match", "persist"]


@dataclass
class SpeakerSegment:
    """발화 단위 라벨 확정 이벤트. overlap 시 시간 겹쳐 여러 개 yield."""

    utterance_id: str
    label: str
    confidence: float        # segmentation activity probability (0.0~1.0)
    embedding: np.ndarray    # D-dim L2 normalized
    audio: bytes             # 화자별 overlap-aware mask 가중 audio (PCM 16kHz mono)
    t_start: float           # 세션 내 절대 시작 시간 (초)
    t_end: float             # 세션 내 절대 종료 시간 (초)


@dataclass
class LabelChange:
    """클러스터 재계산 또는 persist 후 라벨 소급 변경 이벤트."""

    old_label: str
    new_label: str
    affected_utterance_ids: list[str]
    reason: LabelReason


@dataclass
class SpeakerCandidate:
    """finalize() 반환 — 세션 내 auto:* 화자 후보."""

    auto_id: str
    utterance_ids: list[str]
    representative_embedding: np.ndarray  # D-dim centroid (L2 normalized)
    total_duration: float                 # 총 발화 시간 (초)
    utterance_count: int


@dataclass(frozen=True)
class Speaker:
    """SpeakerStore 영속 화자 레코드. persist() / set_alias() 반환."""

    id: UUID
    name: str                              # alias 또는 등록명. 미부여 시 anon_NNN
    origin: Literal["registered", "stored"]
    embedding_dim: int                     # D
    model_id: str                          # e.g. "pyannote/embedding"
    registered_at: float | None            # epoch seconds. stored=None, registered=NOT NULL
    first_seen: float                      # epoch seconds
    last_seen: float                       # epoch seconds
    utterance_count: int


@dataclass(frozen=True)
class PersistMapping:
    """persist() 호출 시 auto:* → name 매핑 단위."""

    auto_id: str
    name: str | None = None  # None 이면 anon_NNN 자동 부여


@dataclass
class MicrophoneGeometry:
    """마이크 어레이 물리 배치. pyroomacoustics geometry 포맷."""

    positions: np.ndarray
    # shape: (channels, 3) — 각 마이크의 (x, y, z) 좌표 (미터 단위)
    reference_channel: int = 0


@dataclass
class BeamformingConfig:
    """beamforming 알고리즘 설정."""

    method: str = "mvdr"     # "mvdr" | "ds"
    sample_rate: int = 16000
    n_fft: int = 512


__all__ = [
    "LabelReason",
    "SpeakerSegment",
    "LabelChange",
    "SpeakerCandidate",
    "Speaker",
    "PersistMapping",
    "MicrophoneGeometry",
    "BeamformingConfig",
]
