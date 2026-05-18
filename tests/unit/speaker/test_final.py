"""Unit tests for FinalReclusterer (spec-04 §4.5 + adr-08)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pytest

from speaker_engine.speaker.final import FinalReclusterer
from speaker_engine.types import SpeakerCandidate


# ---------------------------------------------------------------------------
# Test fixture dataclass (satisfies UtteranceEntry Protocol)
# ---------------------------------------------------------------------------

@dataclass
class Utt:
    utterance_id: str
    label: str
    embedding: np.ndarray
    is_locked: bool
    t_start: float
    t_end: float


def _make_utts(
    base_emb: np.ndarray,
    label: str,
    n: int = 4,
    id_prefix: str = "u",
    duration: float = 1.0,
    scale: float = 0.01,
    rng: np.random.Generator | None = None,
    start_id: int = 0,
) -> list[Utt]:
    if rng is None:
        rng = np.random.default_rng(42)
    utts = []
    for i in range(n):
        emb = base_emb + rng.normal(scale=scale, size=base_emb.shape)
        t = (start_id + i) * duration
        utts.append(
            Utt(
                utterance_id=f"{id_prefix}{start_id + i}",
                label=label,
                embedding=emb,
                is_locked=False,
                t_start=t,
                t_end=t + duration,
            )
        )
    return utts


# ---------------------------------------------------------------------------
# Empty / locked cases
# ---------------------------------------------------------------------------

def test_empty_utterances():
    fr = FinalReclusterer()
    candidates, changes = fr.finalize([], np.zeros((2, 4)), ["auto:A", "auto:B"])
    assert candidates == []
    assert changes == []


def test_all_locked():
    A = np.array([1.0, 0.0, 0.0, 0.0])
    utts = [
        Utt("u0", "registered:Alice", A, True, 0.0, 1.0),
        Utt("u1", "stored:Bob", A, True, 1.0, 2.0),
    ]
    fr = FinalReclusterer()
    candidates, changes = fr.finalize(utts, np.zeros((2, 4)), ["auto:A", "auto:B"])
    assert candidates == []
    assert changes == []


def test_locked_excluded_from_result():
    """registered/stored 발화는 SpeakerCandidate 에 포함되지 않음."""
    rng = np.random.default_rng(42)
    B = np.array([0.0, 1.0, 0.0, 0.0])
    locked = Utt("locked0", "registered:Alice", np.array([1.0, 0.0, 0.0, 0.0]), True, 0.0, 1.0)
    auto_utts = _make_utts(B, "auto:A", n=4, id_prefix="u", rng=rng, start_id=1)

    utts = [locked] + auto_utts
    centers = B.reshape(1, -1)
    fr = FinalReclusterer(min_cluster_size=2)
    candidates, _ = fr.finalize(utts, centers, ["auto:A"])

    all_ids = [uid for c in candidates for uid in c.utterance_ids]
    assert "locked0" not in all_ids
    assert len(candidates) == 1


# ---------------------------------------------------------------------------
# Single speaker — letter preserved
# ---------------------------------------------------------------------------

def test_single_speaker_letter_preserved():
    """1 화자 N 발화 → 1 SpeakerCandidate, online letter 유지."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    utts = _make_utts(A, "auto:A", n=4, rng=rng, scale=0.01)
    centers = A.reshape(1, -1)

    fr = FinalReclusterer(min_cluster_size=2)
    candidates, changes = fr.finalize(utts, centers, ["auto:A"])

    assert len(candidates) == 1
    assert candidates[0].auto_id == "auto:A"
    assert candidates[0].utterance_count == 4
    assert changes == []


def test_single_speaker_candidate_fields():
    """SpeakerCandidate 필드 값 검증."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    utts = _make_utts(A, "auto:A", n=4, rng=rng, scale=0.01, duration=2.0)
    centers = A.reshape(1, -1)

    fr = FinalReclusterer(min_cluster_size=2)
    candidates, _ = fr.finalize(utts, centers, ["auto:A"])

    c = candidates[0]
    assert c.utterance_count == 4
    assert len(c.utterance_ids) == 4
    assert c.total_duration == pytest.approx(8.0, abs=1e-9)
    assert abs(float(np.linalg.norm(c.representative_embedding)) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Two speakers — Hungarian matching
# ---------------------------------------------------------------------------

def test_two_speakers_letters_preserved():
    """2 화자 → 2 SpeakerCandidates, Hungarian 매칭으로 online letter 보존."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    B = np.array([0.0, 1.0, 0.0, 0.0])

    utts_a = _make_utts(A, "auto:A", n=4, id_prefix="a", rng=rng, scale=0.01)
    utts_b = _make_utts(B, "auto:B", n=4, id_prefix="b", rng=rng, scale=0.01, start_id=4)

    centers = np.array([A, B])
    fr = FinalReclusterer(min_cluster_size=2)
    candidates, changes = fr.finalize(utts_a + utts_b, centers, ["auto:A", "auto:B"])

    assert len(candidates) == 2
    assert {c.auto_id for c in candidates} == {"auto:A", "auto:B"}
    assert changes == []


def test_hdbscan_splits_two_speakers_one_online_center():
    """HDBSCAN 이 2 cluster 로 분리 + 1 online center → 1 matched, 1 new letter."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    B = np.array([0.0, 1.0, 0.0, 0.0])

    utts_a = _make_utts(A, "auto:A", n=4, id_prefix="a", rng=rng, scale=0.01)
    utts_b = _make_utts(B, "auto:A", n=4, id_prefix="b", rng=rng, scale=0.01, start_id=4)

    # midpoint online center
    mid = np.array([1.0, 1.0, 0.0, 0.0])
    mid /= np.linalg.norm(mid)
    centers = mid.reshape(1, -1)

    fr = FinalReclusterer(min_cluster_size=2)
    candidates, _ = fr.finalize(utts_a + utts_b, centers, ["auto:A"])

    assert len(candidates) == 2
    labels = {c.auto_id for c in candidates}
    assert "auto:A" in labels  # one cluster matched to online


# ---------------------------------------------------------------------------
# HDBSCAN merges same-speaker drift
# ---------------------------------------------------------------------------

def test_hdbscan_merges_same_speaker_drift():
    """online drift: 동일 화자가 2 online cluster → HDBSCAN 이 1 cluster 로 묶음 + LabelChange."""
    A = np.array([1.0, 0.0, 0.0, 0.0])

    # All 8 utterances use EXACT same embedding (distance=0 → guaranteed 1 cluster)
    utts_a = [
        Utt(f"a{i}", "auto:A", A.copy(), False, float(i), float(i + 1))
        for i in range(4)
    ]
    utts_b = [
        Utt(f"b{i}", "auto:B", A.copy(), False, float(i + 4), float(i + 5))
        for i in range(4)
    ]

    B = np.array([0.0, 1.0, 0.0, 0.0])
    centers = np.array([A, B])

    fr = FinalReclusterer(min_cluster_size=2)
    candidates, changes = fr.finalize(utts_a + utts_b, centers, ["auto:A", "auto:B"])

    # HDBSCAN merges all 8 identical-direction points → 1 cluster
    assert len(candidates) == 1
    # "auto:B" utterances get relabeled
    assert any(ch.old_label == "auto:B" for ch in changes)
    assert all(ch.reason == "recluster" for ch in changes)


# ---------------------------------------------------------------------------
# Noise absorption
# ---------------------------------------------------------------------------

def test_noise_absorption_no_auto_noise_label():
    """noise(-1) 발화를 nearest cluster 로 흡수. 'auto:noise' label 없음."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    B = np.array([0.0, 1.0, 0.0, 0.0])
    C = np.array([0.0, 0.0, 1.0, 0.0])  # single → noise with min_cluster_size=2

    utts_a = _make_utts(A, "auto:A", n=4, id_prefix="a", rng=rng, scale=0.01)
    utts_b = _make_utts(B, "auto:B", n=4, id_prefix="b", rng=rng, scale=0.01, start_id=4)
    utt_c = Utt("c0", "auto:C", C.copy(), False, 8.0, 9.0)

    centers = np.array([A, B])
    fr = FinalReclusterer(min_cluster_size=2)
    candidates, _ = fr.finalize(utts_a + utts_b + [utt_c], centers, ["auto:A", "auto:B"])

    assert len(candidates) == 2
    assert all("noise" not in c.auto_id for c in candidates)
    all_ids = [uid for c in candidates for uid in c.utterance_ids]
    assert "c0" in all_ids  # absorbed into one cluster


def test_noise_absorbed_into_nearest():
    """noise 발화가 cosine 최근접 cluster 로 흡수됨."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    B = np.array([0.0, 1.0, 0.0, 0.0])
    # C is closer to A (small angle from A)
    C = np.array([0.99, 0.14, 0.0, 0.0])
    C /= np.linalg.norm(C)

    utts_a = _make_utts(A, "auto:A", n=4, id_prefix="a", rng=rng, scale=0.01)
    utts_b = _make_utts(B, "auto:B", n=4, id_prefix="b", rng=rng, scale=0.01, start_id=4)
    utt_c = Utt("c0", "auto:A", C.copy(), False, 8.0, 9.0)

    centers = np.array([A, B])
    fr = FinalReclusterer(min_cluster_size=2)
    candidates, _ = fr.finalize(utts_a + utts_b + [utt_c], centers, ["auto:A", "auto:B"])

    # c0 should be absorbed into the A cluster (closer)
    a_cand = next(c for c in candidates if c.auto_id == "auto:A")
    assert "c0" in a_cand.utterance_ids


# ---------------------------------------------------------------------------
# All-noise fallback
# ---------------------------------------------------------------------------

def test_all_noise_fallback_single_cluster(caplog):
    """전부 noise → 단일 cluster + WARN 로그 (spec-04 §4.5)."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    utts = _make_utts(A, "auto:A", n=5, rng=rng, scale=0.01)
    centers = A.reshape(1, -1)

    fr = FinalReclusterer(min_cluster_size=100)  # forces all-noise
    with caplog.at_level(logging.WARNING, logger="speaker_engine.speaker.final"):
        candidates, changes = fr.finalize(utts, centers, ["auto:A"])

    assert len(candidates) == 1
    assert candidates[0].utterance_count == 5
    assert any("noise" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Hungarian threshold
# ---------------------------------------------------------------------------

def test_hungarian_threshold_rejected_new_letter():
    """cost > threshold (0.5) → 매칭 거부, 새 letter 발급."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    B = np.array([0.0, 1.0, 0.0, 0.0])

    # Utterances all in direction A, but online center is B (perpendicular)
    # cost = 1 - cosine_sim(A_centroid, B_center) = 1 - 0 = 1.0 > 0.5 → rejected
    utts = _make_utts(A, "auto:C", n=4, rng=rng, scale=0.01)
    centers = B.reshape(1, -1)

    fr = FinalReclusterer(min_cluster_size=2, hungarian_threshold=0.5)
    candidates, _ = fr.finalize(utts, centers, ["auto:B"])

    assert len(candidates) == 1
    assert candidates[0].auto_id != "auto:B"  # rejected → new letter
    assert candidates[0].auto_id.startswith("auto:")


def test_hungarian_threshold_accepted_letter_preserved():
    """cost ≤ threshold (0.5) → 매칭 성공, online letter 보존."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])

    utts = _make_utts(A, "auto:A", n=4, rng=rng, scale=0.01)
    centers = A.reshape(1, -1)

    fr = FinalReclusterer(min_cluster_size=2, hungarian_threshold=0.5)
    candidates, _ = fr.finalize(utts, centers, ["auto:A"])

    assert len(candidates) == 1
    assert candidates[0].auto_id == "auto:A"


# ---------------------------------------------------------------------------
# representative_embedding — duration-weighted mean + L2 normalize
# ---------------------------------------------------------------------------

def test_representative_embedding_duration_weighted():
    """긴 발화 방향으로 centroid 가 치우침.

    min_cluster_size=100 with 4 utterances → all-noise fallback → single cluster.
    Verifies duration-weighted mean: long-duration utterances dominate the centroid direction.
    """
    A = np.array([1.0, 0.0, 0.0, 0.0])
    B_raw = np.array([0.99, 0.14, 0.0, 0.0])
    B = B_raw / np.linalg.norm(B_raw)

    utts = [
        Utt("u0", "auto:A", A.copy(), False, 0.0, 0.1),   # short, direction A
        Utt("u1", "auto:A", A.copy(), False, 0.1, 0.2),   # short, direction A
        Utt("u2", "auto:A", B.copy(), False, 1.0, 11.0),  # long,  direction B
        Utt("u3", "auto:A", B.copy(), False, 11.0, 21.0), # long,  direction B
    ]

    # min_cluster_size=100 > 4 points → all-noise → single cluster (forced)
    centers = A.reshape(1, -1)
    fr = FinalReclusterer(min_cluster_size=100)
    candidates, _ = fr.finalize(utts, centers, ["auto:A"])

    assert len(candidates) == 1
    rep = candidates[0].representative_embedding

    # expected: w_A = 0.1+0.1 = 0.2, w_B = 10.0+10.0 = 20.0
    expected_raw = 0.2 * A + 20.0 * B
    expected = expected_raw / np.linalg.norm(expected_raw)
    np.testing.assert_allclose(rep, expected, atol=1e-6)


def test_representative_embedding_unit_norm():
    """representative_embedding 은 L2 unit norm."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    B = np.array([0.0, 1.0, 0.0, 0.0])

    utts_a = _make_utts(A, "auto:A", n=4, id_prefix="a", rng=rng, scale=0.01)
    utts_b = _make_utts(B, "auto:B", n=4, id_prefix="b", rng=rng, scale=0.01, start_id=4)
    centers = np.array([A, B])

    fr = FinalReclusterer(min_cluster_size=2)
    candidates, _ = fr.finalize(utts_a + utts_b, centers, ["auto:A", "auto:B"])

    for c in candidates:
        norm = float(np.linalg.norm(c.representative_embedding))
        assert abs(norm - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# LabelChange grouping
# ---------------------------------------------------------------------------

def test_label_change_per_pair():
    """(old_label, new_label) 쌍별 1 LabelChange 이벤트."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    B = np.array([0.0, 1.0, 0.0, 0.0])

    # All labeled "auto:C" but clustering → 2 groups
    utts_a = _make_utts(A, "auto:C", n=4, id_prefix="a", rng=rng, scale=0.01)
    utts_b = _make_utts(B, "auto:C", n=4, id_prefix="b", rng=rng, scale=0.01, start_id=4)
    centers = np.array([A, B])

    fr = FinalReclusterer(min_cluster_size=2)
    candidates, changes = fr.finalize(utts_a + utts_b, centers, ["auto:A", "auto:B"])

    assert len(candidates) == 2
    # 2 pairs: (auto:C → auto:A) and (auto:C → auto:B)
    assert len(changes) == 2
    for ch in changes:
        assert ch.old_label == "auto:C"
        assert ch.reason == "recluster"
        assert len(ch.affected_utterance_ids) == 4


def test_label_change_reason_recluster():
    """LabelChange.reason == 'recluster'."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    B = np.array([0.0, 1.0, 0.0, 0.0])

    utts_a = _make_utts(A, "auto:A", n=4, id_prefix="a", rng=rng, scale=0.01)
    utts_b = _make_utts(B, "auto:A", n=4, id_prefix="b", rng=rng, scale=0.01, start_id=4)
    centers = np.array([A, B])

    fr = FinalReclusterer(min_cluster_size=2)
    _, changes = fr.finalize(utts_a + utts_b, centers, ["auto:A", "auto:B"])

    assert all(ch.reason == "recluster" for ch in changes)


def test_no_label_change_when_already_correct():
    """이미 올바른 라벨 → LabelChange 없음."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    utts = _make_utts(A, "auto:A", n=4, rng=rng, scale=0.01)
    centers = A.reshape(1, -1)

    fr = FinalReclusterer(min_cluster_size=2)
    _, changes = fr.finalize(utts, centers, ["auto:A"])
    assert changes == []


# ---------------------------------------------------------------------------
# max_letters exceeded
# ---------------------------------------------------------------------------

def test_max_letters_exceeded():
    """21 clusters > max_letters=20 → RuntimeError."""
    rng = np.random.default_rng(42)
    D = 32
    Q, _ = np.linalg.qr(rng.standard_normal((D, 21)))
    directions = Q.T  # (21, D) orthonormal rows

    utts = []
    for i in range(21):
        for j in range(2):
            emb = directions[i] + rng.normal(scale=1e-6, size=D)
            utts.append(
                Utt(
                    utterance_id=f"u{i}_{j}",
                    label=f"auto:{chr(ord('A') + (i % 20))}",
                    embedding=emb,
                    is_locked=False,
                    t_start=float(i * 2 + j),
                    t_end=float(i * 2 + j + 1),
                )
            )

    centers = directions[:20]
    center_labels = [f"auto:{chr(ord('A') + i)}" for i in range(20)]

    fr = FinalReclusterer(min_cluster_size=2)
    with pytest.raises(RuntimeError, match="max_letters"):
        fr.finalize(utts, centers, center_labels, max_letters=20)


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_center_labels_length_mismatch():
    """center_labels 길이 불일치 → ValueError."""
    fr = FinalReclusterer()
    centers = np.eye(4)  # K=4
    with pytest.raises(ValueError, match="center_labels"):
        fr.finalize([], centers, ["auto:A", "auto:B"])  # len=2 != K=4


def test_embedding_dim_mismatch():
    """embedding dim 불일치 → ValueError."""
    utts = [
        Utt("u0", "auto:A", np.array([1.0, 0.0, 0.0, 0.0]), False, 0.0, 1.0),
        Utt("u1", "auto:A", np.array([1.0, 0.0]), False, 1.0, 2.0),  # wrong dim
    ]
    fr = FinalReclusterer()
    with pytest.raises(ValueError):
        fr.finalize(utts, np.zeros((1, 4)), ["auto:A"])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_determinism():
    """같은 입력 → 같은 출력."""
    rng_a = np.random.default_rng(42)
    rng_b = np.random.default_rng(43)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    B = np.array([0.0, 1.0, 0.0, 0.0])

    utts_a = _make_utts(A, "auto:A", n=4, id_prefix="a", rng=rng_a, scale=0.01)
    utts_b = _make_utts(B, "auto:B", n=4, id_prefix="b", rng=rng_b, scale=0.01, start_id=4)
    utts = utts_a + utts_b
    centers = np.array([A, B])

    fr = FinalReclusterer(min_cluster_size=2)
    c1, ch1 = fr.finalize(utts, centers, ["auto:A", "auto:B"])
    c2, ch2 = fr.finalize(utts, centers, ["auto:A", "auto:B"])

    assert {c.auto_id for c in c1} == {c.auto_id for c in c2}
    assert len(ch1) == len(ch2)


# ---------------------------------------------------------------------------
# No online centers (K=0)
# ---------------------------------------------------------------------------

def test_no_online_centers_all_new_letters():
    """K=0 online centers → 매칭 없음, 새 letter 발급."""
    rng = np.random.default_rng(42)
    A = np.array([1.0, 0.0, 0.0, 0.0])
    utts = _make_utts(A, "auto:Z", n=4, rng=rng, scale=0.01)

    centers = np.zeros((0, 4))
    fr = FinalReclusterer(min_cluster_size=2)
    candidates, _ = fr.finalize(utts, centers, [])

    assert len(candidates) == 1
    assert candidates[0].auto_id.startswith("auto:")


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------

def test_import():
    from speaker_engine.speaker import FinalReclusterer as FR
    assert FR is FinalReclusterer
