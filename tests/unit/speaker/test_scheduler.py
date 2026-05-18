"""AdaptiveReclusterScheduler 단위 테스트 (spec-05 §2-2 unit 카테고리).

외부 의존 0 — numpy + 합성 embedding (seeded random / hand-crafted 직교, spec-05 §4.1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from speaker_engine.speaker.scheduler import AdaptiveReclusterScheduler
from speaker_engine.types import LabelChange


# ---------------------------------------------------------------------------
# 테스트용 utterance entry (UtteranceEntry Protocol 구현체)
# ---------------------------------------------------------------------------

@dataclass
class Utt:
    utterance_id: str
    label: str
    embedding: np.ndarray
    is_locked: bool = False


# ---------------------------------------------------------------------------
# 헬퍼 — 직교 unit vector
# ---------------------------------------------------------------------------

def unit(arr: list[float]) -> np.ndarray:
    """list → L2 정규화 ndarray."""
    v = np.array(arr, dtype=float)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------
# §1 트리거 조건
# ---------------------------------------------------------------------------

class TestShouldTrigger:
    def _sched(self, count: int = 10, secs: float = 30.0) -> AdaptiveReclusterScheduler:
        return AdaptiveReclusterScheduler(
            trigger_utterance_count=count, trigger_seconds=secs
        )

    def test_no_utterances_no_time(self):
        """발화 0건 + 시간 짧음 → 트리거 X."""
        s = self._sched()
        # last_trigger_time 을 "지금"으로 고정한 채 바로 should_trigger 호출
        base = s._last_trigger_time
        assert not s.should_trigger(current_time=base + 0.1)

    def test_utterances_below_threshold_no_time(self):
        """발화 9건 (< 10) + 시간 짧음 → 트리거 X."""
        s = self._sched()
        for _ in range(9):
            s.notify_utterance()
        base = s._last_trigger_time
        assert not s.should_trigger(current_time=base + 1.0)

    def test_utterances_exact_threshold(self):
        """발화 10건 정확 → 트리거 ✓ (count OR 조건)."""
        s = self._sched()
        for _ in range(10):
            s.notify_utterance()
        base = s._last_trigger_time
        assert s.should_trigger(current_time=base + 0.1)

    def test_utterances_over_threshold(self):
        """발화 15건 → 트리거 ✓."""
        s = self._sched()
        for _ in range(15):
            s.notify_utterance()
        base = s._last_trigger_time
        assert s.should_trigger(current_time=base + 0.1)

    def test_time_elapsed_below_utterance_count(self):
        """발화 3건 + 시간 30초 경과 → 트리거 ✓ (time OR 조건)."""
        s = self._sched()
        for _ in range(3):
            s.notify_utterance()
        base = s._last_trigger_time
        assert s.should_trigger(current_time=base + 30.0)

    def test_time_just_before_threshold(self):
        """발화 3건 + 시간 29.9초 → 트리거 X."""
        s = self._sched()
        for _ in range(3):
            s.notify_utterance()
        base = s._last_trigger_time
        assert not s.should_trigger(current_time=base + 29.9)

    def test_custom_count_override(self):
        """trigger_utterance_count=5 override 동작."""
        s = self._sched(count=5)
        for _ in range(5):
            s.notify_utterance()
        base = s._last_trigger_time
        assert s.should_trigger(current_time=base + 0.1)

    def test_custom_seconds_override(self):
        """trigger_seconds=10 override 동작."""
        s = self._sched(secs=10.0)
        base = s._last_trigger_time
        assert s.should_trigger(current_time=base + 10.0)
        assert not s.should_trigger(current_time=base + 9.9)

    def test_reset_after_recluster(self):
        """recluster() 후 카운터와 시각 리셋 — should_trigger 다시 False."""
        s = self._sched()
        for _ in range(10):
            s.notify_utterance()
        base = s._last_trigger_time
        assert s.should_trigger(current_time=base + 0.1)

        reset_time = base + 1.0
        s.recluster([], np.empty((0, 2)), [], current_time=reset_time)

        # 리셋 후: 카운터 0 + 시각 reset_time → 시간도 짧으면 False
        assert not s.should_trigger(current_time=reset_time + 0.1)

    def test_reset_time_then_new_trigger(self):
        """리셋 후 다시 30초 지나면 재트리거."""
        s = self._sched()
        reset_time = s._last_trigger_time + 100.0
        s.recluster([], np.empty((0, 2)), [], current_time=reset_time)
        assert s.should_trigger(current_time=reset_time + 30.0)


# ---------------------------------------------------------------------------
# §2 재라벨 정책
# ---------------------------------------------------------------------------

class TestRecluster:
    """spec-04 §4.4 재라벨 정책 검증."""

    # hand-crafted 직교 2D unit vectors
    V_A = unit([1.0, 0.0])   # center for auto:A direction
    V_B = unit([0.0, 1.0])   # center for auto:B direction
    V_AB = unit([1.0, 1.0])  # between A and B

    def test_empty_utterances(self):
        """빈 utterance buffer → 빈 list, 예외 없음."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([self.V_A])
        result = s.recluster([], centers, ["auto:A"])
        assert result == []

    def test_empty_active_centers(self):
        """active centers 비어있음 → 빈 list."""
        s = AdaptiveReclusterScheduler()
        utts = [Utt("u1", "auto:A", self.V_A)]
        result = s.recluster(utts, np.empty((0, 2)), [])
        assert result == []

    def test_locked_utterances_unchanged(self):
        """is_locked=True 발화는 재라벨 대상 제외."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([self.V_B])
        utts = [
            Utt("u1", "registered:Alice", self.V_B, is_locked=True),
            Utt("u2", "stored:Bob", self.V_B, is_locked=True),
        ]
        result = s.recluster(utts, centers, ["auto:X"])
        assert result == []

    def test_label_change_occurs(self):
        """is_locked=False 발화 + max cosine centroid 매칭 → 라벨 변경."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([self.V_B])  # "auto:B" centroid
        utts = [Utt("u1", "auto:A", self.V_B)]  # 완전히 겹침 → cosine_sim=1.0
        result = s.recluster(utts, centers, ["auto:B"])
        assert len(result) == 1
        assert result[0].old_label == "auto:A"
        assert result[0].new_label == "auto:B"
        assert result[0].affected_utterance_ids == ["u1"]
        assert result[0].reason == "recluster"

    def test_same_label_no_change(self):
        """현재 라벨 == 매칭 라벨 → LabelChange 생성 안 함."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([self.V_A])
        utts = [Utt("u1", "auto:A", self.V_A)]  # 이미 auto:A
        result = s.recluster(utts, centers, ["auto:A"])
        assert result == []

    def test_threshold_guard_rejects_dissimilar(self):
        """threshold guard: delta_new=0.5 → sim_threshold=0.5. 직교 벡터(cosine_sim=0) 변경 거부."""
        s = AdaptiveReclusterScheduler()
        # V_A = [1,0], V_B = [0,1] → cosine_sim = 0.0 < 0.5 → reject
        centers = np.array([self.V_A])
        utts = [Utt("u1", "auto:B", self.V_B)]
        result = s.recluster(utts, centers, ["auto:A"], delta_new=0.5)
        assert result == []

    def test_threshold_guard_passes_similar(self):
        """threshold guard: delta_new=0.5, 유사한 벡터 → 변경 허용."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([self.V_A])
        # V_AB = [1,1]/√2 → cosine_sim with V_A = 1/√2 ≈ 0.707 > 0.5 → pass
        utts = [Utt("u1", "auto:B", self.V_AB)]
        result = s.recluster(utts, centers, ["auto:A"], delta_new=0.5)
        assert len(result) == 1
        assert result[0].old_label == "auto:B"
        assert result[0].new_label == "auto:A"

    def test_delta_new_default_passes_all_positive(self):
        """delta_new=1.0 (default) → sim_threshold=0.0. 양수 cosine_sim 매칭 모두 통과."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([self.V_A])
        utts = [Utt("u1", "auto:B", self.V_AB)]  # cosine_sim=0.707 > 0.0 → pass
        result = s.recluster(utts, centers, ["auto:A"])
        assert len(result) == 1

    def test_grouping_two_events(self):
        """(auto:A → auto:C × 2건) + (auto:B → auto:C × 1건) → LabelChange 2 events."""
        s = AdaptiveReclusterScheduler()
        # centroid 하나 = auto:C 방향 V_A
        centers = np.array([self.V_A])
        utts = [
            Utt("u1", "auto:A", self.V_A),
            Utt("u2", "auto:A", self.V_A),
            Utt("u3", "auto:B", self.V_A),
        ]
        result = s.recluster(utts, centers, ["auto:C"])
        assert len(result) == 2

        result_map = {(r.old_label, r.new_label): r for r in result}
        assert ("auto:A", "auto:C") in result_map
        assert ("auto:B", "auto:C") in result_map
        assert set(result_map[("auto:A", "auto:C")].affected_utterance_ids) == {"u1", "u2"}
        assert result_map[("auto:B", "auto:C")].affected_utterance_ids == ["u3"]

    def test_multiple_centers_best_match(self):
        """두 centroid 중 cosine 최대 centroid 로 매핑."""
        s = AdaptiveReclusterScheduler()
        # V_A=[1,0] → auto:A, V_B=[0,1] → auto:B
        centers = np.array([self.V_A, self.V_B])
        # V_AB = [1,1]/√2 → V_A 와 V_B 유사도 동일(0.707). argmax 는 첫 번째 선택 (np.argmax 정책)
        utts = [
            Utt("u1", "auto:X", self.V_A),  # V_A → auto:A (sim=1.0)
            Utt("u2", "auto:X", self.V_B),  # V_B → auto:B (sim=1.0)
        ]
        result = s.recluster(utts, centers, ["auto:A", "auto:B"])
        result_map = {(r.old_label, r.new_label): r for r in result}
        assert ("auto:X", "auto:A") in result_map
        assert ("auto:X", "auto:B") in result_map

    def test_non_unit_centers_normalized_correctly(self):
        """non-unit centroid (diart 누적 합) 도 내부 정규화로 올바른 cosine 비교."""
        s = AdaptiveReclusterScheduler()
        # V_A 를 3배 scale → unit-norm 아님. 정규화 후 방향은 동일해야 함
        centers = np.array([self.V_A * 3.0])
        utts = [Utt("u1", "auto:B", self.V_A)]  # V_A 방향 → 정규화 후 cosine_sim=1.0
        result = s.recluster(utts, centers, ["auto:A"])
        assert len(result) == 1
        assert result[0].old_label == "auto:B"
        assert result[0].new_label == "auto:A"

    def test_locked_mixed_with_unlocked(self):
        """locked 와 unlocked 혼합 — unlocked 만 변경."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([self.V_B])
        utts = [
            Utt("u1", "registered:Alice", self.V_B, is_locked=True),
            Utt("u2", "auto:A", self.V_B, is_locked=False),
        ]
        result = s.recluster(utts, centers, ["auto:B"])
        assert len(result) == 1
        assert result[0].old_label == "auto:A"
        assert result[0].new_label == "auto:B"
        assert result[0].affected_utterance_ids == ["u2"]

    def test_no_change_when_all_locked(self):
        """모든 발화 locked → 빈 list."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([self.V_B])
        utts = [Utt("u1", "registered:Alice", self.V_B, is_locked=True)]
        result = s.recluster(utts, centers, ["auto:X"])
        assert result == []


# ---------------------------------------------------------------------------
# §3 LabelChange 구조 검증
# ---------------------------------------------------------------------------

class TestLabelChangeStructure:
    def test_reason_is_recluster(self):
        """LabelChange.reason == 'recluster' (spec-04 §4.4)."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([unit([1.0, 0.0])])
        utts = [Utt("u1", "auto:B", unit([1.0, 0.0]))]
        result = s.recluster(utts, centers, ["auto:A"])
        assert result[0].reason == "recluster"

    def test_affected_utterance_ids_correct(self):
        """affected_utterance_ids 정확 — 매핑된 id 만 포함."""
        s = AdaptiveReclusterScheduler()
        v = unit([1.0, 0.0])
        centers = np.array([v])
        utts = [
            Utt("id-alpha", "auto:B", v),
            Utt("id-beta", "auto:B", v),
        ]
        result = s.recluster(utts, centers, ["auto:A"])
        assert len(result) == 1
        assert set(result[0].affected_utterance_ids) == {"id-alpha", "id-beta"}

    def test_old_new_label_correct(self):
        """old_label / new_label 정확."""
        s = AdaptiveReclusterScheduler()
        v = unit([1.0, 0.0])
        centers = np.array([v])
        utts = [Utt("u1", "auto:Z", v)]
        result = s.recluster(utts, centers, ["auto:A"])
        assert result[0].old_label == "auto:Z"
        assert result[0].new_label == "auto:A"


# ---------------------------------------------------------------------------
# §4 예외 케이스
# ---------------------------------------------------------------------------

class TestExceptions:
    def test_center_labels_length_mismatch(self):
        """center_labels 길이 != active_centers 행 수 → ValueError."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([unit([1.0, 0.0]), unit([0.0, 1.0])])  # K=2
        utts = [Utt("u1", "auto:A", unit([1.0, 0.0]))]
        with pytest.raises(ValueError):
            s.recluster(utts, centers, ["auto:A"])  # length=1 != 2

    def test_embedding_dim_mismatch(self):
        """embedding dim != centroid dim → ValueError."""
        s = AdaptiveReclusterScheduler()
        centers = np.array([unit([1.0, 0.0])])  # D=2
        utts = [Utt("u1", "auto:B", unit([1.0, 0.0, 0.0]))]  # D=3
        with pytest.raises(ValueError):
            s.recluster(utts, centers, ["auto:A"])


# ---------------------------------------------------------------------------
# §5 결정론 (seeded random fixture)
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_input_same_output(self):
        """seeded random embedding — 동일 입력 → 동일 출력 (결정론)."""
        rng = np.random.default_rng(seed=42)

        def make_fixture():
            s = AdaptiveReclusterScheduler()
            D = 4
            centers_raw = rng.standard_normal((3, D))  # non-unit-norm intentionally
            labels = ["auto:A", "auto:B", "auto:C"]
            utts = [
                Utt(f"u{i}", f"auto:{chr(ord('X') + i % 3)}", rng.standard_normal(D))
                for i in range(12)
            ]
            return s, centers_raw, labels, utts

        # rng 을 같은 seed 로 두 번 실행 (독립적으로 생성)
        rng = np.random.default_rng(seed=42)
        s1, c1, l1, u1 = make_fixture()
        rng = np.random.default_rng(seed=42)
        s2, c2, l2, u2 = make_fixture()

        r1 = s1.recluster(u1, c1, l1)
        r2 = s2.recluster(u2, c2, l2)

        # 결과 비교 — 동일한 (old, new, ids) 집합
        def to_set(results: list[LabelChange]):
            return {
                (r.old_label, r.new_label, frozenset(r.affected_utterance_ids))
                for r in results
            }

        assert to_set(r1) == to_set(r2)
