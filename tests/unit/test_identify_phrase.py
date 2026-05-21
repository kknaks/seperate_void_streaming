"""identify_phrase 단위 테스트 (PLAN-006-T-002, spec-04 §9, spec-05 §2-2).

외부 의존 제거 전략:
- DiartAdapter.embed_pcm : AsyncMock 으로 hand-crafted embedding 반환
- DiartAdapter / OnlineSpeakerClusterer : engine 모듈 내 이름 patch
- MemoryStore : 실 in-memory 인스턴스 사용 (spec-05 §4.2)
- embedding : seeded random + hand-crafted unit vector (spec-05 §4.1)

시나리오:
  (a) 등록 직원 PCM → registered:<name>
  (b) 신규 화자 → auto:A
  (c) 동일 신규 화자 재호출 → auto:A (라벨 유지)
  (d) 다른 신규 화자 → auto:B
  (e) 짧은 phrase + 직전 라벨 있음 → 직전 라벨 반환 (Option A)
  (f) stream auto:A 와 identify_phrase auto:A 동일 (clusterer centroid 공유 검증)
"""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from speaker_engine.engine import SpeakerEngine
from speaker_engine.storage.memory import MemoryStore

# ─────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

D = 16  # 테스트용 embedding 차원


def unit_vec(*vals: float) -> np.ndarray:
    v = np.array(vals, dtype=np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


def rng_emb(seed: int, dim: int = D) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def make_pcm(duration_s: float = 2.0) -> bytes:
    """16kHz mono 16-bit PCM bytes (silent)."""
    n_samples = int(16000 * duration_s)
    return b"\x00\x00" * n_samples


def make_mock_clusterer(
    centers: np.ndarray | None = None,
    active_centers: set[int] | None = None,
) -> MagicMock:
    m = MagicMock()
    m.centers = centers
    m.active_centers = active_centers if active_centers is not None else set()
    m.delta_new = 1.0
    m._max_speakers = 20
    m.identify = MagicMock(
        return_value=MagicMock(valid_assignments=MagicMock(return_value=([], [])))
    )
    return m


def make_engine(
    registered_speakers: dict[str, np.ndarray] | None = None,
    mock_clusterer: MagicMock | None = None,
    store: MemoryStore | None = None,
) -> tuple[SpeakerEngine, MagicMock, MagicMock]:
    """SpeakerEngine 을 mocked diart / clusterer 로 생성."""
    mock_diart = MagicMock()
    mock_diart.embedding_dim = D
    mock_diart.embed_pcm = AsyncMock(return_value=rng_emb(0))  # default; override per test
    mock_diart.process_window = AsyncMock(return_value=[])
    mock_diart.close = AsyncMock()

    clusterer = mock_clusterer or make_mock_clusterer()
    mem_store = store or MemoryStore()

    with (
        patch("speaker_engine.engine.DiartAdapter", return_value=mock_diart),
        patch("speaker_engine.engine.OnlineSpeakerClusterer", return_value=clusterer),
        patch("speaker_engine.engine.from_url", return_value=mem_store),
    ):
        engine = SpeakerEngine(
            storage_url="memory://",
            hf_token="fake-token",
            registered_speakers=registered_speakers,
        )

    return engine, mock_diart, clusterer


# ─────────────────────────────────────────────────────────────────────────────
# (a) 등록 직원 PCM → "registered:<name>"
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentifyPhraseRegistered:
    async def test_registered_speaker_returns_registered_label(self):
        """등록 직원과 유사한 embedding → 'registered:이름' 반환."""
        reg_emb = rng_emb(42)
        engine, mock_diart, _ = make_engine(registered_speakers={"Alice": reg_emb})
        # embed_pcm 이 등록 직원과 동일한 L2-normalized embedding 반환
        mock_diart.embed_pcm = AsyncMock(return_value=reg_emb.copy())

        # __aenter__: init_schema + register 필요
        engine._store = MagicMock()
        engine._store.init_schema = AsyncMock()
        engine._store.register = AsyncMock()
        engine._store.find_match = AsyncMock(return_value=None)  # stored miss

        label = await engine.identify_phrase(make_pcm(2.0))

        assert label == "registered:Alice"


# ─────────────────────────────────────────────────────────────────────────────
# (b) 신규 화자 → "auto:A"
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentifyPhraseNewSpeaker:
    async def test_new_speaker_returns_auto_a(self):
        """등록/저장 히트 없는 신규 화자 → 'auto:A'."""
        engine, mock_diart, _ = make_engine()
        mock_diart.embed_pcm = AsyncMock(return_value=rng_emb(1))
        engine._store.find_match = AsyncMock(return_value=None)

        label = await engine.identify_phrase(make_pcm(2.0))

        assert label == "auto:A"

    async def test_new_speaker_added_to_phrase_centroids(self):
        """신규 화자 발견 시 _phrase_centroids 에 등록됨."""
        engine, mock_diart, _ = make_engine()
        emb = rng_emb(10)
        mock_diart.embed_pcm = AsyncMock(return_value=emb)
        engine._store.find_match = AsyncMock(return_value=None)

        await engine.identify_phrase(make_pcm(2.0))

        assert len(engine._phrase_centroids) == 1
        assert engine._phrase_centroids[0][1] == "auto:A"


# ─────────────────────────────────────────────────────────────────────────────
# (c) 같은 신규 화자 두 번째 호출 → "auto:A" (동일 라벨)
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentifyPhraseConsistency:
    async def test_same_speaker_returns_same_label(self):
        """동일 화자 embedding 재호출 → 동일 'auto:A' 반환."""
        engine, mock_diart, _ = make_engine()
        emb = rng_emb(5)
        mock_diart.embed_pcm = AsyncMock(return_value=emb.copy())
        engine._store.find_match = AsyncMock(return_value=None)

        label1 = await engine.identify_phrase(make_pcm(2.0))
        label2 = await engine.identify_phrase(make_pcm(2.0))

        assert label1 == "auto:A"
        assert label2 == "auto:A"


# ─────────────────────────────────────────────────────────────────────────────
# (d) 다른 신규 화자 → "auto:B"
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentifyPhraseDifferentSpeaker:
    async def test_two_different_speakers_get_different_labels(self):
        """두 화자가 서로 직교하는 embedding → auto:A, auto:B."""
        engine, mock_diart, _ = make_engine()
        # Orthogonal embeddings → cosine similarity = 0 < 0.5 threshold
        emb_a = np.zeros(D, dtype=np.float32)
        emb_a[0] = 1.0
        emb_b = np.zeros(D, dtype=np.float32)
        emb_b[1] = 1.0

        engine._store.find_match = AsyncMock(return_value=None)

        mock_diart.embed_pcm = AsyncMock(return_value=emb_a)
        label_a = await engine.identify_phrase(make_pcm(2.0))

        mock_diart.embed_pcm = AsyncMock(return_value=emb_b)
        label_b = await engine.identify_phrase(make_pcm(2.0))

        assert label_a == "auto:A"
        assert label_b == "auto:B"


# ─────────────────────────────────────────────────────────────────────────────
# (e) 짧은 phrase → 직전 라벨 반환 (Option A)
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentifyPhraseShortPhrase:
    async def test_short_phrase_returns_previous_label(self):
        """짧은 phrase (< 1.5s) + 직전 라벨 있음 → 직전 라벨 반환, embed_pcm 호출 없음."""
        engine, mock_diart, _ = make_engine()
        emb = rng_emb(3)
        mock_diart.embed_pcm = AsyncMock(return_value=emb)
        engine._store.find_match = AsyncMock(return_value=None)

        # 먼저 충분히 긴 phrase 로 라벨 결정 (auto:A)
        label1 = await engine.identify_phrase(make_pcm(2.0))
        assert label1 == "auto:A"

        embed_call_count_before = mock_diart.embed_pcm.call_count

        # 짧은 phrase (~0.5초) → 직전 라벨 반환
        short_pcm = make_pcm(0.5)
        label2 = await engine.identify_phrase(short_pcm)

        assert label2 == "auto:A"
        # embed_pcm 은 추가 호출되지 않아야 함 (단축 경로)
        assert mock_diart.embed_pcm.call_count == embed_call_count_before

    async def test_short_phrase_without_prior_still_identifies(self):
        """직전 라벨 없는 첫 호출은 짧은 phrase 라도 정식 identify 수행."""
        engine, mock_diart, _ = make_engine()
        emb = rng_emb(7)
        mock_diart.embed_pcm = AsyncMock(return_value=emb)
        engine._store.find_match = AsyncMock(return_value=None)

        label = await engine.identify_phrase(make_pcm(0.5))

        assert label.startswith("auto:")
        mock_diart.embed_pcm.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# (f) stream auto:A 와 identify_phrase auto:A 동일 (clusterer centroid 공유)
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentifyPhraseRunningAverage:
    async def test_running_average_updates_centroid(self):
        """같은 화자 emb 2회 호출 → 동일 라벨 + centroid 가 두 emb 의 가중 평균에 근접."""
        engine, mock_diart, _ = make_engine()
        emb1 = np.zeros(D, dtype=np.float32)
        emb1[0] = 1.0  # L2 normalized unit vector

        emb2_raw = np.zeros(D, dtype=np.float32)
        emb2_raw[0] = 0.9
        emb2_raw[1] = 0.1
        emb2 = (emb2_raw / np.linalg.norm(emb2_raw)).astype(np.float32)

        engine._store.find_match = AsyncMock(return_value=None)

        mock_diart.embed_pcm = AsyncMock(return_value=emb1.copy())
        label1 = await engine.identify_phrase(make_pcm(2.0))
        assert label1 == "auto:A"

        mock_diart.embed_pcm = AsyncMock(return_value=emb2.copy())
        label2 = await engine.identify_phrase(make_pcm(2.0))
        assert label2 == "auto:A"

        expected_raw = 0.7 * emb1 + 0.3 * emb2
        expected = expected_raw / np.linalg.norm(expected_raw)
        np.testing.assert_allclose(
            engine._phrase_centroids[0][0], expected, atol=1e-5,
            err_msg="centroid 가 running average (0.7*old + 0.3*new, L2 정규화) 여야 함",
        )

    async def test_running_average_weight_old_dominant(self):
        """weight 0.7 old: 갱신 후 centroid 는 새 emb 보다 기존 emb 에 더 가까워야 함."""
        engine, mock_diart, _ = make_engine()
        emb1 = np.zeros(D, dtype=np.float32)
        emb1[0] = 1.0

        engine._store.find_match = AsyncMock(return_value=None)

        mock_diart.embed_pcm = AsyncMock(return_value=emb1.copy())
        await engine.identify_phrase(make_pcm(2.0))

        emb2_raw = np.zeros(D, dtype=np.float32)
        emb2_raw[0] = 0.9
        emb2_raw[1] = 0.1
        emb2 = (emb2_raw / np.linalg.norm(emb2_raw)).astype(np.float32)

        mock_diart.embed_pcm = AsyncMock(return_value=emb2.copy())
        await engine.identify_phrase(make_pcm(2.0))

        centroid = engine._phrase_centroids[0][0]
        dist_to_old = float(np.linalg.norm(centroid - emb1))
        dist_to_new = float(np.linalg.norm(centroid - emb2))
        assert dist_to_old < dist_to_new, (
            f"centroid 이 old emb 에 더 가까워야 함 (weight 0.7): "
            f"dist_old={dist_to_old:.4f}, dist_new={dist_to_new:.4f}"
        )

    async def test_threshold_0_35_default(self):
        """SpeakerEngine() 기본 phrase_auto_threshold == 0.35."""
        engine, _, _ = make_engine()
        assert engine._phrase_auto_threshold == pytest.approx(0.35)


class TestIdentifyPhraseStreamSharing:
    async def test_phrase_reuses_stream_auto_label_via_centroid(self):
        """stream 이 centroid[0] 에 auto:A 를 등록한 이후 identify_phrase 도 auto:A 반환.

        clusterer.centers + active_centers 를 통해 stream 경로의 centroid 를 공유.
        """
        emb_alice = rng_emb(99)

        # clusterer 가 centroid[0]=emb_alice 를 이미 보유 (stream 이 등록했다고 가정)
        centers = np.zeros((20, D), dtype=np.float32)
        centers[0] = emb_alice
        mock_clusterer = make_mock_clusterer(
            centers=centers,
            active_centers={0},
        )

        engine, mock_diart, _ = make_engine(mock_clusterer=mock_clusterer)
        # embed_pcm 이 alice 와 유사한 embedding 반환 (cosine ~ 1.0)
        mock_diart.embed_pcm = AsyncMock(return_value=emb_alice.copy())
        engine._store.find_match = AsyncMock(return_value=None)

        label = await engine.identify_phrase(make_pcm(2.0))

        assert label == "auto:A", (
            f"stream 이 'auto:A' 로 등록한 centroid 와 동일 화자 → 'auto:A' 기대, 실제: {label!r}"
        )
