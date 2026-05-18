"""unit tests — speaker_engine.diart_adapter (PLAN-003-T-013, spec-03 §6 T01-T10).

모든 테스트는 실 diart 모델 호출 0 — diart blocks 를 MagicMock 으로 패치.
"""

from __future__ import annotations

import sys
import types
from dataclasses import fields
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# diart / torch 를 sys.modules 에 stub 으로 박아 import guard 를 통과시킨다.
# DiartAdapter 모듈 자체를 re-import 하기 위해 fixture 로 격리.
# ---------------------------------------------------------------------------

WINDOW_SAMPLES = 16_000 * 10
NUM_FRAMES = 293  # segmentation-3.0 이 10s 에서 반환하는 프레임 수 (근사)
EMB_DIM = 256


def _make_diart_stubs():
    """sys.modules 에 주입할 diart stub 패키지들을 반환."""
    # torch stub
    torch_stub = types.ModuleType("torch")
    torch_stub.cuda = MagicMock()
    torch_stub.cuda.is_available = MagicMock(return_value=False)
    torch_stub.device = MagicMock(side_effect=lambda x: x)

    class _FakeTensor:
        def __init__(self, data):
            self._data = np.asarray(data, dtype=np.float32)

        def unsqueeze(self, dim):
            return _FakeTensor(np.expand_dims(self._data, axis=dim))

        def numpy(self):
            return self._data

        def float(self):
            return self

        @property
        def shape(self):
            return self._data.shape

    torch_stub.from_numpy = lambda arr: _FakeTensor(arr)
    torch_stub.Tensor = _FakeTensor

    # diart.models stub
    diart_models = types.ModuleType("diart.models")
    seg_model_cls = MagicMock()
    emb_model_cls = MagicMock()
    seg_model_instance = MagicMock()
    emb_model_instance = MagicMock()
    emb_model_instance.dimension = EMB_DIM
    seg_model_cls.from_pyannote = MagicMock(return_value=seg_model_instance)
    emb_model_cls.from_pyannote = MagicMock(return_value=emb_model_instance)
    diart_models.SegmentationModel = seg_model_cls
    diart_models.EmbeddingModel = emb_model_cls

    # diart.blocks stub
    diart_blocks = types.ModuleType("diart.blocks")

    class _FakeSegmentation:
        def __init__(self, model=None, device=None):
            self.model = model
            self.device = device
            self._call_result = None  # test 에서 설정

        def __call__(self, wav_tensor):
            if self._call_result is not None:
                return self._call_result
            # default: (1, NUM_FRAMES, 3) float32 zeros
            arr = np.zeros((1, NUM_FRAMES, 3), dtype=np.float32)
            return arr

    class _FakeEmbedding:
        def __init__(self, model=None, device=None):
            self.model = model
            self.device = device
            self._call_result = None

        def __call__(self, wav_tensor, segmentation):
            if self._call_result is not None:
                return self._call_result
            # default: (1, 3, EMB_DIM) float32 random unit vectors
            arr = np.random.default_rng(42).standard_normal((1, 3, EMB_DIM)).astype(np.float32)
            # normalize rows
            for i in range(3):
                arr[0, i] /= np.linalg.norm(arr[0, i]) + 1e-9
            return arr

    diart_blocks.SpeakerSegmentation = _FakeSegmentation
    diart_blocks.OverlapAwareSpeakerEmbedding = _FakeEmbedding

    # diart.blocks.clustering stub — OnlineSpeakerClusterer 의 _inner 로 사용됨
    diart_blocks_clustering = types.ModuleType("diart.blocks.clustering")

    class _FakeClustering:
        def __init__(self, tau_active=0.6, rho_update=0.3, delta_new=1.0, metric="cosine", max_speakers=20):
            self.tau_active = tau_active
            self.rho_update = rho_update
            self.delta_new = delta_new
            self.metric = metric
            self.max_speakers = max_speakers
            self.centers = None
            self.active_centers: set = set()
            self._identify_result = None

        def identify(self, segmentation, embeddings):
            if self._identify_result is not None:
                return self._identify_result
            mock_map = MagicMock()
            mock_map.valid_assignments.return_value = (np.array([0]), np.array([0]))
            return mock_map

    diart_blocks_clustering.OnlineSpeakerClustering = _FakeClustering

    # top-level diart package
    diart_pkg = types.ModuleType("diart")
    diart_pkg.models = diart_models
    diart_pkg.blocks = diart_blocks

    # pyannote.core stub — SlidingWindow / SlidingWindowFeature
    pyannote_core = types.ModuleType("pyannote.core")

    class _FakeSlidingWindowFeature:
        def __init__(self, data, sliding_window):
            self.data = data
            self.sliding_window = sliding_window

    class _FakeSlidingWindow:
        def __init__(self, duration=1.0, step=None, start=0.0):
            self.duration = duration
            self.step = step if step is not None else duration
            self.start = start

    pyannote_core.SlidingWindowFeature = _FakeSlidingWindowFeature
    pyannote_core.SlidingWindow = _FakeSlidingWindow
    pyannote_pkg = types.ModuleType("pyannote")
    pyannote_pkg.core = pyannote_core

    return torch_stub, diart_pkg, diart_models, diart_blocks, diart_blocks_clustering, pyannote_pkg, pyannote_core


@pytest.fixture(autouse=True)
def _patch_diart(monkeypatch):
    """모든 테스트 전에 diart/pyannote 를 sys.modules 에 stub 으로 교체."""
    torch_stub, diart_pkg, diart_models, diart_blocks, diart_blocks_clustering, pyannote_pkg, pyannote_core = _make_diart_stubs()

    monkeypatch.setitem(sys.modules, "torch", torch_stub)
    monkeypatch.setitem(sys.modules, "diart", diart_pkg)
    monkeypatch.setitem(sys.modules, "diart.models", diart_models)
    monkeypatch.setitem(sys.modules, "diart.blocks", diart_blocks)
    monkeypatch.setitem(sys.modules, "diart.blocks.clustering", diart_blocks_clustering)
    monkeypatch.setitem(sys.modules, "pyannote", pyannote_pkg)
    monkeypatch.setitem(sys.modules, "pyannote.core", pyannote_core)

    # online.py 와 diart_adapter 모두 강제 재로드해서 _DIART_OK=True 로 만든다
    sys.modules.pop("speaker_engine.speaker.online", None)
    if "speaker_engine.diart_adapter" in sys.modules:
        del sys.modules["speaker_engine.diart_adapter"]
    import speaker_engine.diart_adapter  # noqa: F401  re-import

    yield

    # 정리
    sys.modules.pop("speaker_engine.diart_adapter", None)
    sys.modules.pop("speaker_engine.speaker.online", None)


def _make_clusterer(max_speakers: int = 20):
    from speaker_engine.speaker.online import OnlineSpeakerClusterer

    return OnlineSpeakerClusterer(max_speakers=max_speakers)


def _make_adapter(**kwargs) -> Any:
    from speaker_engine.diart_adapter import DiartAdapter

    max_speakers = kwargs.pop("max_speakers", 20)
    clusterer = kwargs.pop("clusterer", _make_clusterer(max_speakers=max_speakers))
    defaults = dict(hf_token="tok-test", clusterer=clusterer)
    defaults.update(kwargs)
    return DiartAdapter(**defaults)


def _flat_waveform(value: float = 0.1) -> np.ndarray:
    return np.full(WINDOW_SAMPLES, value, dtype=np.float32)


# ── __init__ ───────────────────────────────────────────────────────────────


class TestDiartAdapterInit:
    def test_blocks_instantiated(self):
        from speaker_engine.diart_adapter import DiartAdapter

        clusterer = _make_clusterer()
        adapter = DiartAdapter(hf_token="tok", clusterer=clusterer)
        assert adapter._segmentation is not None
        assert adapter._embedding is not None
        assert adapter._clusterer is not None

    def test_model_load_error_on_seg_failure(self, monkeypatch):
        import diart.models as dm
        from speaker_engine.exceptions import ModelLoadError

        dm.SegmentationModel.from_pyannote.side_effect = RuntimeError("HF down")
        with pytest.raises(ModelLoadError):
            _make_adapter()

    def test_model_load_error_on_emb_failure(self, monkeypatch):
        import diart.models as dm
        from speaker_engine.exceptions import ModelLoadError

        dm.EmbeddingModel.from_pyannote.side_effect = RuntimeError("HF down")
        with pytest.raises(ModelLoadError):
            _make_adapter()

    def test_cuda_not_available_raises(self):
        with pytest.raises(RuntimeError, match="CUDA"):
            _make_adapter(device="cuda")

    def test_default_max_speakers(self):
        adapter = _make_adapter()
        assert adapter._max_speakers == 20

    def test_custom_max_speakers(self):
        adapter = _make_adapter(max_speakers=5)
        assert adapter._max_speakers == 5

    def test_deprecated_max_speakers_warns(self):
        """DiartAdapter 에 직접 max_speakers 전달 시 DeprecationWarning."""
        from speaker_engine.diart_adapter import DiartAdapter

        clusterer = _make_clusterer()
        with pytest.warns(DeprecationWarning, match="deprecated"):
            DiartAdapter(hf_token="tok", clusterer=clusterer, max_speakers=10)


# ── embedding_dim ──────────────────────────────────────────────────────────


class TestEmbeddingDim:
    def test_returns_model_dimension(self):
        adapter = _make_adapter()
        # _FakeEmbedding 의 model.dimension = EMB_DIM (256) 이지만
        # 실제 property 는 _embedding.model.dimension 접근
        # FakeEmbedding 은 model 속성이 EmbeddingModel mock 이므로 확인
        dim = adapter.embedding_dim
        assert isinstance(dim, int)
        assert dim > 0


# ── process_window ─────────────────────────────────────────────────────────


class TestProcessWindow:
    async def test_wrong_shape_raises_value_error(self):
        adapter = _make_adapter()
        bad = np.zeros(1000, dtype=np.float32)
        with pytest.raises(ValueError, match="shape"):
            await adapter.process_window(bad)

    async def test_2d_array_raises_value_error(self):
        adapter = _make_adapter()
        bad = np.zeros((WINDOW_SAMPLES, 1), dtype=np.float32)
        with pytest.raises(ValueError):
            await adapter.process_window(bad)

    async def test_all_silence_returns_empty(self):
        """multilabel 전부 0 → 빈 list."""
        adapter = _make_adapter()
        # segmentation → zeros (no speech)
        adapter._segmentation._call_result = np.zeros((1, NUM_FRAMES, 3), dtype=np.float32)
        # clustering 이 빈 assignment 반환
        mock_map = MagicMock()
        mock_map.valid_assignments.return_value = (np.array([], dtype=int), np.array([], dtype=int))
        adapter._clusterer._inner._identify_result = mock_map

        result = await adapter.process_window(_flat_waveform())
        assert result == []

    async def test_one_speaker_returns_one_event(self):
        """화자 1명 활성 → 1 RawSpeakerEvent."""
        from speaker_engine.diart_adapter import RawSpeakerEvent

        adapter = _make_adapter()

        # segmentation: speaker 0 만 활성
        seg = np.zeros((1, NUM_FRAMES, 3), dtype=np.float32)
        seg[0, :, 0] = 1.0  # 모든 프레임에 spk0 활성
        adapter._segmentation._call_result = seg

        mock_map = MagicMock()
        mock_map.valid_assignments.return_value = (np.array([0]), np.array([0]))
        adapter._clusterer._inner._identify_result = mock_map

        result = await adapter.process_window(_flat_waveform())
        assert len(result) == 1
        assert isinstance(result[0], RawSpeakerEvent)

    async def test_two_speakers_returns_two_events(self):
        """화자 2명 활성 → 2 RawSpeakerEvent."""
        adapter = _make_adapter()

        seg = np.zeros((1, NUM_FRAMES, 3), dtype=np.float32)
        seg[0, :, 0] = 1.0  # spk0
        seg[0, :, 1] = 1.0  # spk1
        adapter._segmentation._call_result = seg

        mock_map = MagicMock()
        mock_map.valid_assignments.return_value = (np.array([0, 1]), np.array([0, 1]))
        adapter._clusterer._inner._identify_result = mock_map

        result = await adapter.process_window(_flat_waveform())
        assert len(result) == 2

    async def test_embedding_l2_normalized(self):
        """반환 embedding 의 L2 norm ≈ 1.0 (spec-03 §4-5)."""
        from speaker_engine.diart_adapter import RawSpeakerEvent

        adapter = _make_adapter()

        seg = np.zeros((1, NUM_FRAMES, 3), dtype=np.float32)
        seg[0, :, 0] = 1.0
        adapter._segmentation._call_result = seg

        emb = np.random.default_rng(7).standard_normal((1, 3, EMB_DIM)).astype(np.float32)
        adapter._embedding._call_result = emb

        mock_map = MagicMock()
        mock_map.valid_assignments.return_value = (np.array([0]), np.array([0]))
        adapter._clusterer._inner._identify_result = mock_map

        result = await adapter.process_window(_flat_waveform())
        assert len(result) == 1
        norm = float(np.linalg.norm(result[0].embedding))
        assert norm == pytest.approx(1.0, abs=1e-5)

    async def test_event_fields_valid(self):
        """RawSpeakerEvent 필드 타입·범위 검증."""
        adapter = _make_adapter()

        seg = np.zeros((1, NUM_FRAMES, 3), dtype=np.float32)
        seg[0, 10:50, 0] = 1.0  # frames 10~49 활성
        adapter._segmentation._call_result = seg

        mock_map = MagicMock()
        mock_map.valid_assignments.return_value = (np.array([0]), np.array([3]))
        adapter._clusterer._inner._identify_result = mock_map

        result = await adapter.process_window(_flat_waveform())
        assert len(result) == 1
        ev = result[0]
        assert isinstance(ev.local_speaker_id, int)
        assert 0 <= ev.local_speaker_id < 20
        assert isinstance(ev.audio, bytes)
        assert ev.t_start < ev.t_end
        assert 0.0 <= ev.confidence <= 1.0
        assert isinstance(ev.embedding, np.ndarray)

    async def test_audio_is_bytes(self):
        adapter = _make_adapter()
        seg = np.zeros((1, NUM_FRAMES, 3), dtype=np.float32)
        seg[0, :, 0] = 1.0
        adapter._segmentation._call_result = seg
        mock_map = MagicMock()
        mock_map.valid_assignments.return_value = (np.array([0]), np.array([0]))
        adapter._clusterer._inner._identify_result = mock_map
        result = await adapter.process_window(_flat_waveform())
        assert isinstance(result[0].audio, bytes)
        assert len(result[0].audio) > 0

    async def test_single_chunk_failure_retries_and_skips(self, monkeypatch):
        """process_window 두 번 모두 실패 → skip + WARN (spec-03 §5-b)."""
        adapter = _make_adapter()

        call_count = 0

        def _always_fail(waveform):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("model exploded")

        monkeypatch.setattr(adapter, "_process_window_sync", _always_fail)
        result = await adapter.process_window(_flat_waveform())
        assert result == []
        assert call_count == 2  # 1회 retry → 2회 시도


# ── RxPY isolation ─────────────────────────────────────────────────────────


class TestRxPYIsolation:
    def test_no_rxpy_in_public_attributes(self):
        """공개 속성에 RxPY Subject/Observable 없음 (spec-03 §6 T10)."""
        adapter = _make_adapter()
        for attr_name in dir(adapter):
            if attr_name.startswith("_"):
                continue
            val = getattr(adapter, attr_name, None)
            type_name = type(val).__name__
            assert "Subject" not in type_name, f"{attr_name} 에 Subject 노출"
            assert "Observable" not in type_name, f"{attr_name} 에 Observable 노출"


# ── close ──────────────────────────────────────────────────────────────────


class TestClose:
    async def test_process_window_after_close_raises(self):
        adapter = _make_adapter()
        await adapter.close()
        with pytest.raises(RuntimeError, match="닫혔습니다"):
            await adapter.process_window(_flat_waveform())

    async def test_close_clears_model_refs(self):
        adapter = _make_adapter()
        await adapter.close()
        assert adapter._segmentation is None
        assert adapter._embedding is None
        assert adapter._clusterer is None


# ── RawSpeakerEvent dataclass ──────────────────────────────────────────────


class TestRawSpeakerEvent:
    def test_dataclass_fields(self):
        from speaker_engine.diart_adapter import RawSpeakerEvent

        field_names = {f.name for f in fields(RawSpeakerEvent)}
        expected = {"local_speaker_id", "embedding", "audio", "t_start", "t_end", "confidence"}
        assert expected == field_names

    def test_construction(self):
        from speaker_engine.diart_adapter import RawSpeakerEvent

        ev = RawSpeakerEvent(
            local_speaker_id=2,
            embedding=np.ones(256, dtype=np.float32),
            audio=b"\x00\x01",
            t_start=1.0,
            t_end=3.5,
            confidence=0.9,
        )
        assert ev.local_speaker_id == 2
        assert ev.t_start < ev.t_end


# ── powerset decoder ───────────────────────────────────────────────────────


class TestPowersetDecoder:
    def test_silence_class(self):
        from speaker_engine.diart_adapter import _powerset_to_multilabel

        scores = np.zeros((10, 7), dtype=np.float32)
        scores[:, 0] = 1.0  # all silence
        out = _powerset_to_multilabel(scores)
        assert out.shape == (10, 3)
        assert out.sum() == pytest.approx(0.0)

    def test_single_speaker(self):
        from speaker_engine.diart_adapter import _powerset_to_multilabel

        scores = np.zeros((5, 7), dtype=np.float32)
        scores[:, 1] = 1.0  # class 1 → speaker 0 only
        out = _powerset_to_multilabel(scores)
        assert np.all(out[:, 0] == 1.0)
        assert np.all(out[:, 1] == 0.0)
        assert np.all(out[:, 2] == 0.0)

    def test_two_speakers_overlap(self):
        from speaker_engine.diart_adapter import _powerset_to_multilabel

        scores = np.zeros((5, 7), dtype=np.float32)
        scores[:, 4] = 1.0  # class 4 → spk0 + spk1
        out = _powerset_to_multilabel(scores)
        assert np.all(out[:, 0] == 1.0)
        assert np.all(out[:, 1] == 1.0)
        assert np.all(out[:, 2] == 0.0)


# ── l2_normalize ───────────────────────────────────────────────────────────


class TestL2Normalize:
    def test_unit_vector_unchanged(self):
        from speaker_engine.diart_adapter import _l2_normalize

        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        out = _l2_normalize(v)
        assert float(np.linalg.norm(out)) == pytest.approx(1.0, abs=1e-6)

    def test_arbitrary_vector_normalized(self):
        from speaker_engine.diart_adapter import _l2_normalize

        v = np.array([3.0, 4.0], dtype=np.float32)
        out = _l2_normalize(v)
        assert float(np.linalg.norm(out)) == pytest.approx(1.0, abs=1e-6)

    def test_zero_vector_safe(self):
        from speaker_engine.diart_adapter import _l2_normalize

        v = np.zeros(4, dtype=np.float32)
        out = _l2_normalize(v)
        assert not np.isnan(out).any()
