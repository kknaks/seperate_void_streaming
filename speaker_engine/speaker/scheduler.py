"""AdaptiveReclusterScheduler — 10발화 OR 30초 트리거 소급 재라벨 (spec-04 §4.4)."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Protocol

import numpy as np

from speaker_engine.types import LabelChange


class UtteranceEntry(Protocol):
    """utterance buffer 한 항목의 최소 shape (spec-04 §OQ-04-6, 구현 단계 결정).

    SpeakerEngine 이 SOT 를 보유. scheduler / final 은 인자로만 받음 (spec-04 §2-2).
    t_start / t_end 는 FinalReclusterer 의 duration-weighted centroid 계산에 사용 (E-05).
    """

    utterance_id: str
    label: str
    embedding: np.ndarray  # D-dim, L2 normalized utterance mean embedding
    is_locked: bool        # registered:* / stored:* 라벨 → True
    t_start: float         # session-relative start time (seconds)
    t_end: float           # session-relative end time (seconds)


class AdaptiveReclusterScheduler:
    """세션 도중 누적 발화 소급 재라벨 스케줄러 (spec-04 §4.4).

    State: 마지막 트리거 후 누적 발화 수 + 마지막 트리거 시각 (time.monotonic).
    utterance buffer / centroid state 는 자체 보유 X — 인자로만 받음 (spec-04 §2-2).
    순수 numpy 연산, sync (spec-04 §4.6, adr-05 R3).
    """

    def __init__(
        self,
        trigger_utterance_count: int = 10,
        trigger_seconds: float = 30.0,
    ) -> None:
        self._trigger_utterance_count = trigger_utterance_count
        self._trigger_seconds = trigger_seconds
        self._utterances_since_last: int = 0
        self._last_trigger_time: float = time.monotonic()

    # ------------------------------------------------------------------
    # 트리거

    def notify_utterance(self) -> None:
        """SpeakerEngine 이 발화를 utterance buffer 에 append 할 때 호출."""
        self._utterances_since_last += 1

    def should_trigger(self, current_time: float | None = None) -> bool:
        """트리거 조건 (OR) 충족 여부 확인.

        Args:
            current_time: 단조 시각 주입 (테스트용). None 이면 time.monotonic().
        """
        now = current_time if current_time is not None else time.monotonic()
        count_ok = self._utterances_since_last >= self._trigger_utterance_count
        time_ok = (now - self._last_trigger_time) >= self._trigger_seconds
        return count_ok or time_ok

    # ------------------------------------------------------------------
    # 소급 재라벨

    def recluster(
        self,
        utterances: list[UtteranceEntry],
        active_centers: np.ndarray,  # shape (K, D) — 누적 합이므로 unit-norm 아닐 수 있음
        center_labels: list[str],    # length K
        delta_new: float = 1.0,
        current_time: float | None = None,
    ) -> list[LabelChange]:
        """소급 재라벨 수행 + 카운터/시각 리셋 (adr-05 R3 inline).

        Args:
            utterances: SpeakerEngine utterance buffer. is_locked=True 발화는 건드리지 않음.
            active_centers: online clustering 의 active centroid 행렬 (K, D).
                diart 누적 합 정책 — unit-norm 보장 없음. scheduler 내부에서 row 정규화.
            center_labels: 각 centroid 의 라벨 (length == K).
            delta_new: cosine distance 임계값. sim_threshold = 1 - delta_new.
                delta_new=1.0 (default) → 모든 양수 유사도 매칭 통과.
            current_time: 리셋용 단조 시각 주입 (테스트용).

        Returns:
            LabelChange 목록. (old_label, new_label) 쌍별 1 event. 변경 없으면 빈 list.

        Raises:
            ValueError: center_labels 길이 불일치 또는 embedding shape 불일치.
        """
        # 리셋 먼저 (R3 inline — 빈 버퍼 / 빈 centroid 도 동일하게 리셋)
        now = current_time if current_time is not None else time.monotonic()
        self._utterances_since_last = 0
        self._last_trigger_time = now

        # 조기 반환 — 빈 버퍼 또는 active centroid 없음
        if not utterances or len(active_centers) == 0:
            return []

        centers = np.array(active_centers, dtype=float)  # (K, D)
        K = centers.shape[0]

        if len(center_labels) != K:
            raise ValueError(
                f"center_labels length {len(center_labels)} != active_centers rows {K}"
            )

        # row 단위 L2 정규화 (diart 누적 합 → unit-norm 아닐 수 있음, spec-04 §4.3)
        norms = np.linalg.norm(centers, axis=1, keepdims=True)
        zero_mask = (norms == 0).ravel()
        if zero_mask.any():
            # zero centroid 는 삭제 (비활성 화자)
            valid = ~zero_mask
            centers = centers[valid]
            center_labels = [lbl for lbl, ok in zip(center_labels, valid) if ok]
            norms = norms[valid]
            if len(centers) == 0:
                return []
        centers = centers / norms  # (K, D) unit-norm

        sim_threshold = 1.0 - delta_new

        # (old_label, new_label) → utterance_id 목록
        changes: dict[tuple[str, str], list[str]] = defaultdict(list)

        for utt in utterances:
            if utt.is_locked:
                continue

            emb = np.asarray(utt.embedding, dtype=float)
            if emb.shape[0] != centers.shape[1]:
                raise ValueError(
                    f"Embedding dim {emb.shape[0]} != centers dim {centers.shape[1]}"
                )

            # cosine similarity: centers 가 unit-norm 이므로 dot product = cosine sim
            sims = centers @ emb  # (K,)
            best_idx = int(np.argmax(sims))
            best_sim = float(sims[best_idx])

            if best_sim < sim_threshold:
                continue  # threshold guard: 변경 거부, 현재 라벨 유지

            new_label = center_labels[best_idx]
            if new_label == utt.label:
                continue  # 동일 라벨 → LabelChange 생성 안 함

            changes[(utt.label, new_label)].append(utt.utterance_id)

        return [
            LabelChange(
                old_label=old,
                new_label=new,
                affected_utterance_ids=ids,
                reason="recluster",
            )
            for (old, new), ids in changes.items()
        ]
