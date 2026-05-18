"""unit tests — speaker_engine.speaker.online (PLAN-003-T-014, spec-04 §4.3).

diart 는 sys.modules stub 으로 교체 — 실 모델 호출 0.
"""

from __future__ import annotations

import logging
import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# diart.blocks.clustering stub
# ---------------------------------------------------------------------------

NUM_FRAMES = 50
EMB_DIM = 256


class _FakeClustering:
    def __init__(
        self,
        tau_active: float = 0.6,
        rho_update: float = 0.3,
        delta_new: float = 1.0,
        metric: str = "cosine",
        max_speakers: int = 20,
    ):
        self.tau_active = tau_active
        self.rho_update = rho_update
        self.delta_new = delta_new
        self.metric = metric
        self.max_speakers = max_speakers
        self.centers = None
        self.active_centers: set[int] = set()
        self._identify_result = None

    def identify(self, segmentation, embeddings):
        if self._identify_result is not None:
            return self._identify_result
        mock_map = MagicMock()
        mock_map.valid_assignments.return_value = (np.array([0]), np.array([0]))
        return mock_map


def _make_clustering_stub() -> types.ModuleType:
    mod = types.ModuleType("diart.blocks.clustering")
    mod.OnlineSpeakerClustering = _FakeClustering
    return mod


@pytest.fixture(autouse=True)
def _patch_diart_clustering(monkeypatch):
    """diart.blocks.clustering 을 stub 으로 교체하고 online.py 를 재로드."""
    clustering_stub = _make_clustering_stub()
    monkeypatch.setitem(sys.modules, "diart.blocks.clustering", clustering_stub)

    # online.py 강제 재로드
    sys.modules.pop("speaker_engine.speaker.online", None)
    import speaker_engine.speaker.online  # noqa: F401

    yield

    sys.modules.pop("speaker_engine.speaker.online", None)


def _make_clusterer(**kwargs):
    from speaker_engine.speaker.online import OnlineSpeakerClusterer

    return OnlineSpeakerClusterer(**kwargs)


def _seg(num_frames: int = NUM_FRAMES, num_speakers: int = 3) -> MagicMock:
    """segmentation wrapper stub."""
    wrapper = MagicMock()
    wrapper.data = np.zeros((num_frames, num_speakers), dtype=np.float32)
    return wrapper


def _emb(num_speakers: int = 1, dim: int = EMB_DIM) -> np.ndarray:
    rng = np.random.default_rng(42)
    arr = rng.standard_normal((num_speakers, dim)).astype(np.float32)
    for i in range(num_speakers):
        arr[i] /= np.linalg.norm(arr[i]) + 1e-9
    return arr


# ── 초기화 ──────────────────────────────────────────────────────────────────


class TestOnlineSpeakerClustererInit:
    def test_default_params_passed_to_inner(self):
        c = _make_clusterer()
        assert c._inner.tau_active == pytest.approx(0.6)
        assert c._inner.rho_update == pytest.approx(0.3)
        assert c._inner.delta_new == pytest.approx(1.0)
        assert c._inner.max_speakers == 20
        assert c._inner.metric == "cosine"

    def test_override_params(self):
        c = _make_clusterer(tau_active=0.5, rho_update=0.2, delta_new=0.8, max_speakers=5, metric="cosine")
        assert c._inner.tau_active == pytest.approx(0.5)
        assert c._inner.rho_update == pytest.approx(0.2)
        assert c._inner.delta_new == pytest.approx(0.8)
        assert c._inner.max_speakers == 5

    def test_centers_initially_none(self):
        c = _make_clusterer()
        assert c.centers is None

    def test_active_centers_initially_empty(self):
        c = _make_clusterer()
        assert c.active_centers == set()

    def test_max_speakers_stored(self):
        c = _make_clusterer(max_speakers=10)
        assert c._max_speakers == 10

    def test_delta_new_stored(self):
        c = _make_clusterer(delta_new=0.5)
        assert c.delta_new == pytest.approx(0.5)


# ── delta_new property ──────────────────────────────────────────────────────


class TestDeltaNewProperty:
    def test_default_delta_new(self):
        assert _make_clusterer().delta_new == pytest.approx(1.0)

    def test_custom_delta_new(self):
        assert _make_clusterer(delta_new=0.42).delta_new == pytest.approx(0.42)


# ── centers property ────────────────────────────────────────────────────────


class TestCentersProperty:
    def test_none_when_inner_centers_none(self):
        c = _make_clusterer()
        c._inner.centers = None
        assert c.centers is None

    def test_returns_array_after_set(self):
        c = _make_clusterer()
        arr = np.zeros((20, EMB_DIM), dtype=np.float32)
        c._inner.centers = arr
        result = c.centers
        assert result is not None
        assert result.shape == (20, EMB_DIM)

    def test_returns_none_for_empty_array(self):
        c = _make_clusterer()
        c._inner.centers = np.zeros((0, EMB_DIM), dtype=np.float32)
        assert c.centers is None


# ── active_centers property ─────────────────────────────────────────────────


class TestActiveCentersProperty:
    def test_empty_when_inner_none(self):
        c = _make_clusterer()
        c._inner.active_centers = None  # type: ignore[assignment]
        assert c.active_centers == set()

    def test_returns_set(self):
        c = _make_clusterer()
        c._inner.active_centers = {0, 1, 2}
        assert c.active_centers == {0, 1, 2}

    def test_returns_copy_as_set(self):
        c = _make_clusterer()
        c._inner.active_centers = {3, 7}
        result = c.active_centers
        assert isinstance(result, set)
        assert result == {3, 7}


# ── identify ────────────────────────────────────────────────────────────────


class TestIdentify:
    def test_delegates_to_inner(self):
        c = _make_clusterer()
        mock_result = MagicMock()
        c._inner._identify_result = mock_result
        result = c.identify(_seg(), _emb())
        assert result is mock_result

    def test_returns_inner_default_map(self):
        c = _make_clusterer()
        result = c.identify(_seg(), _emb())
        local_spks, global_spks = result.valid_assignments()
        assert len(local_spks) == 1

    def test_dim_mismatch_raises(self):
        c = _make_clusterer()
        c._inner.centers = np.zeros((20, EMB_DIM), dtype=np.float32)
        bad_emb = np.ones((1, 128), dtype=np.float32)  # D=128 vs centers D=256
        with pytest.raises(ValueError, match="불일치"):
            c.identify(_seg(), bad_emb)

    def test_no_error_when_centers_none(self):
        """centers 가 None 이면 D 검사 스킵."""
        c = _make_clusterer()
        c._inner.centers = None
        emb = _emb(1, 128)
        result = c.identify(_seg(), emb)
        assert result is not None

    def test_warn_on_max_speakers_exceeded(self, caplog):
        c = _make_clusterer(max_speakers=2)
        c._inner.active_centers = {0, 1}  # len=2 >= max_speakers=2
        with caplog.at_level(logging.WARNING, logger="speaker_engine.speaker.online"):
            c.identify(_seg(), _emb())
        assert "강제 매핑" in caplog.text

    def test_no_warn_below_max_speakers(self, caplog):
        c = _make_clusterer(max_speakers=5)
        c._inner.active_centers = {0, 1}  # len=2 < 5
        with caplog.at_level(logging.WARNING, logger="speaker_engine.speaker.online"):
            c.identify(_seg(), _emb())
        assert "강제 매핑" not in caplog.text


# ── letter 매핑 ─────────────────────────────────────────────────────────────


class TestLetterMapping:
    def test_idx_to_letter_first(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        assert OnlineSpeakerClusterer.idx_to_letter(0) == "auto:A"

    def test_idx_to_letter_last(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        assert OnlineSpeakerClusterer.idx_to_letter(19) == "auto:T"

    def test_idx_to_letter_all(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        letters = "ABCDEFGHIJKLMNOPQRST"
        for i, ch in enumerate(letters):
            assert OnlineSpeakerClusterer.idx_to_letter(i) == f"auto:{ch}"

    def test_idx_to_letter_out_of_range_high(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        with pytest.raises(ValueError):
            OnlineSpeakerClusterer.idx_to_letter(20)

    def test_idx_to_letter_out_of_range_negative(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        with pytest.raises(ValueError):
            OnlineSpeakerClusterer.idx_to_letter(-1)

    def test_letter_to_idx_first(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        assert OnlineSpeakerClusterer.letter_to_idx("auto:A") == 0

    def test_letter_to_idx_last(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        assert OnlineSpeakerClusterer.letter_to_idx("auto:T") == 19

    def test_letter_to_idx_out_of_range(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        with pytest.raises(ValueError):
            OnlineSpeakerClusterer.letter_to_idx("auto:U")

    def test_letter_to_idx_invalid_format(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        with pytest.raises(ValueError):
            OnlineSpeakerClusterer.letter_to_idx("invalid")

    def test_letter_to_idx_wrong_prefix(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        with pytest.raises(ValueError):
            OnlineSpeakerClusterer.letter_to_idx("spk:A")

    def test_round_trip(self):
        from speaker_engine.speaker.online import OnlineSpeakerClusterer

        for i in range(20):
            assert OnlineSpeakerClusterer.letter_to_idx(OnlineSpeakerClusterer.idx_to_letter(i)) == i
