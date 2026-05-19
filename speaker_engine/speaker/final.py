"""FinalReclusterer — HDBSCAN + Hungarian assignment (adr-08 + spec-04 §4.5)."""

from __future__ import annotations

import logging
from collections import defaultdict

import hdbscan
import numpy as np
from scipy.optimize import linear_sum_assignment

from speaker_engine.speaker.scheduler import UtteranceEntry
from speaker_engine.types import LabelChange, SpeakerCandidate

_LOG = logging.getLogger(__name__)
_LETTERS = [chr(ord("A") + i) for i in range(20)]  # A~T


class FinalReclusterer:
    """세션 종료 1회 HDBSCAN 정밀 재라벨 + Hungarian online letter 보존 (spec-04 §4.5 + adr-08).

    stateless — 호출당 1회 실행. utterance buffer + online cluster state 를 인자로만 받음 (spec-04 §2-2).
    순수 numpy + hdbscan + scipy 연산, sync (spec-04 §4.6).
    """

    def __init__(
        self,
        min_cluster_size: int = 2,
        min_samples: int = 1,
        metric: str = "cosine",
        cluster_selection_epsilon: float = 0.3,
        cluster_selection_method: str = "eom",
        hungarian_threshold: float = 0.5,
    ) -> None:
        self._min_cluster_size = min_cluster_size
        self._min_samples = min_samples
        self._metric = metric
        self._cluster_selection_epsilon = cluster_selection_epsilon
        self._cluster_selection_method = cluster_selection_method
        self._hungarian_threshold = hungarian_threshold

    # ------------------------------------------------------------------
    # HDBSCAN via precomputed cosine distance (sklearn BallTree cosine 우회)

    def _run_hdbscan(self, X: np.ndarray) -> np.ndarray:
        """HDBSCAN on L2-normalized X using precomputed cosine distance matrix.

        Args:
            X: (N, D) L2-normalized embeddings.

        Returns:
            labels: (N,) int array, -1 = noise.
        """
        sim = X @ X.T  # (N, N) cosine similarity (X is unit-norm)
        dist = np.clip(1.0 - sim, 0.0, None)
        np.fill_diagonal(dist, 0.0)
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self._min_cluster_size,
            min_samples=self._min_samples,
            metric="precomputed",
            cluster_selection_epsilon=self._cluster_selection_epsilon,
            cluster_selection_method=self._cluster_selection_method,
        )
        return clusterer.fit_predict(dist).astype(int)

    # ------------------------------------------------------------------
    # finalize

    def finalize(
        self,
        utterances: list[UtteranceEntry],
        online_centers: np.ndarray,  # (K, D) active centroid
        center_labels: list[str],    # length K, e.g. ["auto:A", "auto:B"]
        max_letters: int = 20,
    ) -> tuple[list[SpeakerCandidate], list[LabelChange]]:
        """세션 종료 1회 HDBSCAN 재라벨 + Hungarian letter 보존 (spec-04 §4.5 + adr-08).

        Args:
            utterances: SpeakerEngine utterance buffer. is_locked=True 발화 제외.
            online_centers: (K, D) active centroid. unit-norm 보장 없음 (diart 누적 합 정책).
            center_labels: 각 centroid 라벨 (length == K).
            max_letters: 최대 화자 수 (default 20 = A~T, planning-02 §582).

        Returns:
            (list[SpeakerCandidate], list[LabelChange]).

        Raises:
            ValueError: center_labels 길이 불일치 또는 embedding shape 불일치.
            RuntimeError: final cluster 수 > max_letters.
        """
        # --- 입력 검증 ---
        centers_arr = np.array(online_centers, dtype=float)
        if centers_arr.ndim == 1:
            centers_arr = (
                centers_arr.reshape(1, -1) if centers_arr.size > 0 else np.empty((0, 1))
            )
        K = centers_arr.shape[0]
        if len(center_labels) != K:
            raise ValueError(
                f"center_labels length {len(center_labels)} != online_centers rows {K}"
            )

        # --- auto:* 발화만 대상 (is_locked=False) ---
        auto_utts = [u for u in utterances if not u.is_locked]
        if not auto_utts:
            return [], []

        N = len(auto_utts)

        # --- embedding matrix (N, D), L2 normalize ---
        first_emb = np.asarray(auto_utts[0].embedding, dtype=float)
        D = first_emb.shape[0]
        X = np.zeros((N, D), dtype=float)
        for i, u in enumerate(auto_utts):
            emb = np.asarray(u.embedding, dtype=float)
            if emb.shape[0] != D:
                raise ValueError(
                    f"Utterance {u.utterance_id} embedding dim {emb.shape[0]} != {D}"
                )
            n = float(np.linalg.norm(emb))
            X[i] = emb / n if n > 0.0 else emb

        # --- HDBSCAN ---
        labels = self._run_hdbscan(X)  # (N,) int

        # --- 전부 noise (-1) → 단일 cluster + WARN (spec-04 §4.5) ---
        if np.all(labels == -1):
            _LOG.warning(
                "FinalReclusterer: all %d utterances classified as HDBSCAN noise — "
                "grouping into single cluster (spec-04 §4.5)",
                N,
            )
            labels = np.zeros(N, dtype=int)

        cluster_ids = sorted(set(labels.tolist()) - {-1})

        # --- noise 흡수: -1 → nearest cluster centroid (adr-08) ---
        noise_mask = labels == -1
        if noise_mask.any():
            pre_centroids = np.zeros((len(cluster_ids), D), dtype=float)
            for ci, cid in enumerate(cluster_ids):
                pts = X[labels == cid]
                c = pts.mean(axis=0)
                cn = float(np.linalg.norm(c))
                pre_centroids[ci] = c / cn if cn > 0.0 else c

            for idx in np.where(noise_mask)[0]:
                sims = pre_centroids @ X[idx]  # (len(cluster_ids),)
                labels[idx] = cluster_ids[int(np.argmax(sims))]

            cluster_ids = sorted(set(labels.tolist()))

        M = len(cluster_ids)

        # --- max_letters 초과 체크 ---
        if M > max_letters:
            raise RuntimeError(
                f"FinalReclusterer: {M} final clusters exceed max_letters={max_letters} "
                f"(planning-02 §582)"
            )

        # --- cluster별 utterance/duration 수집 ---
        cluster_utt_ids: dict[int, list[str]] = defaultdict(list)
        cluster_durations: dict[int, float] = defaultdict(float)
        for i, u in enumerate(auto_utts):
            cid = int(labels[i])
            duration = max(0.0, float(u.t_end) - float(u.t_start))
            cluster_utt_ids[cid].append(u.utterance_id)
            cluster_durations[cid] += duration

        # --- representative_embedding: duration-weighted mean + L2 normalize (adr-08 OQ-08-2) ---
        rep_embeddings: dict[int, np.ndarray] = {}
        for cid in cluster_ids:
            weighted_sum = np.zeros(D, dtype=float)
            total_w = 0.0
            for i, u in enumerate(auto_utts):
                if int(labels[i]) != cid:
                    continue
                duration = max(0.0, float(u.t_end) - float(u.t_start))
                w = duration if duration > 0.0 else 1.0  # zero-duration → uniform weight
                weighted_sum += w * X[i]
                total_w += w
            centroid = weighted_sum / total_w if total_w > 0.0 else weighted_sum
            cn = float(np.linalg.norm(centroid))
            rep_embeddings[cid] = centroid / cn if cn > 0.0 else centroid

        # --- Hungarian matching (M × K cost matrix) ---
        matched: dict[int, int] = {}  # cluster_ids index → online index
        if K > 0 and M > 0:
            online_arr = centers_arr.copy()
            on_norms = np.linalg.norm(online_arr, axis=1, keepdims=True)
            on_norms[on_norms == 0.0] = 1.0
            online_arr /= on_norms  # (K, D) unit-norm

            final_mats = np.array(
                [rep_embeddings[cid] for cid in cluster_ids], dtype=float
            )  # (M, D)
            cost_matrix = 1.0 - (final_mats @ online_arr.T)  # (M, K)
            row_ind, col_ind = linear_sum_assignment(cost_matrix)
            for r, c in zip(row_ind.tolist(), col_ind.tolist()):
                if cost_matrix[r, c] <= self._hungarian_threshold:
                    matched[r] = c
            if matched:
                _matched_costs = [cost_matrix[r, matched[r]] for r in matched]
                _LOG.debug(
                    "FinalReclusterer Hungarian: M=%d K=%d matched=%d "
                    "cost_min=%.4f cost_max=%.4f cost_mean=%.4f threshold=%.2f",
                    M, K, len(matched),
                    min(_matched_costs), max(_matched_costs),
                    sum(_matched_costs) / len(_matched_costs),
                    self._hungarian_threshold,
                )
            else:
                _LOG.debug(
                    "FinalReclusterer Hungarian: M=%d K=%d matched=0 (all rejected by threshold=%.2f)",
                    M, K, self._hungarian_threshold,
                )

        # --- letter 발급 ---
        used_letters: set[str] = set()
        for ci, o_idx in matched.items():
            lbl = center_labels[o_idx]
            letter = lbl.split(":")[-1] if ":" in lbl else lbl
            used_letters.add(letter)

        cluster_label: dict[int, str] = {}
        # 1st pass: matched → online letter
        for ci, cid in enumerate(cluster_ids):
            if ci in matched:
                lbl = center_labels[matched[ci]]
                letter = lbl.split(":")[-1] if ":" in lbl else lbl
                cluster_label[cid] = f"auto:{letter}"

        # 2nd pass: unmatched → new letter (ascending cid order)
        letter_pool = [ltr for ltr in _LETTERS if ltr not in used_letters]
        lp_idx = 0
        for ci, cid in enumerate(cluster_ids):
            if cid not in cluster_label:
                if lp_idx >= len(letter_pool):
                    raise RuntimeError(
                        f"FinalReclusterer: letter pool exhausted at cluster {cid}"
                    )
                cluster_label[cid] = f"auto:{letter_pool[lp_idx]}"
                lp_idx += 1

        # --- SpeakerCandidate list ---
        candidates: list[SpeakerCandidate] = [
            SpeakerCandidate(
                auto_id=cluster_label[cid],
                utterance_ids=cluster_utt_ids[cid],
                representative_embedding=rep_embeddings[cid],
                total_duration=cluster_durations[cid],
                utterance_count=len(cluster_utt_ids[cid]),
            )
            for cid in cluster_ids
        ]

        # --- LabelChange list: group by (old_label, new_label) ---
        change_map: dict[tuple[str, str], list[str]] = defaultdict(list)
        for i, u in enumerate(auto_utts):
            cid = int(labels[i])
            new_label = cluster_label[cid]
            if new_label != u.label:
                change_map[(u.label, new_label)].append(u.utterance_id)

        label_changes: list[LabelChange] = [
            LabelChange(
                old_label=old,
                new_label=new,
                affected_utterance_ids=ids,
                reason="recluster",
            )
            for (old, new), ids in change_map.items()
        ]

        return candidates, label_changes
