"""unit tests — speaker_engine.types (F-02)."""

from dataclasses import FrozenInstanceError
from uuid import uuid4

import numpy as np
import pytest

from speaker_engine.types import (
    BeamformingConfig,
    LabelChange,
    MicrophoneGeometry,
    PersistMapping,
    Speaker,
    SpeakerCandidate,
    SpeakerSegment,
)

_RNG = np.random.default_rng(42)


def _embedding(dim: int = 192) -> np.ndarray:
    v = _RNG.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


# ── SpeakerSegment ──────────────────────────────────────────────────────────


class TestSpeakerSegment:
    def test_create_and_fields(self):
        emb = _embedding()
        audio = b"\x00" * 320
        seg = SpeakerSegment(
            utterance_id="utt-001",
            label="auto:A",
            confidence=0.9,
            embedding=emb,
            audio=audio,
            t_start=0.0,
            t_end=1.5,
        )
        assert seg.utterance_id == "utt-001"
        assert seg.label == "auto:A"
        assert seg.confidence == pytest.approx(0.9)
        assert isinstance(seg.embedding, np.ndarray)
        assert seg.audio is audio
        assert seg.t_start == pytest.approx(0.0)
        assert seg.t_end == pytest.approx(1.5)

    def test_embedding_is_1d_ndarray(self):
        emb = _embedding(256)
        seg = SpeakerSegment("utt-002", "auto:B", 0.8, emb, b"", 0.0, 1.0)
        assert isinstance(seg.embedding, np.ndarray)
        assert seg.embedding.ndim == 1
        assert seg.embedding.shape == (256,)

    def test_label_formats(self):
        for label in ("auto:A", "registered:김원장", "stored:박○○", "stored:anon_001"):
            seg = SpeakerSegment("utt-x", label, 0.5, _embedding(), b"", 0.0, 0.5)
            assert seg.label == label


# ── LabelChange ────────────────────────────────────────────────────────────


class TestLabelChange:
    def test_create_and_fields(self):
        lc = LabelChange(
            old_label="auto:A",
            new_label="stored:박○○",
            affected_utterance_ids=["utt-001", "utt-002"],
            reason="stored_match",
        )
        assert lc.old_label == "auto:A"
        assert lc.new_label == "stored:박○○"
        assert lc.affected_utterance_ids == ["utt-001", "utt-002"]
        assert lc.reason == "stored_match"

    def test_all_reason_values(self):
        for reason in ("recluster", "stored_match", "persist"):
            lc = LabelChange("old", "new", [], reason)
            assert lc.reason == reason

    def test_affected_ids_empty(self):
        lc = LabelChange("auto:A", "auto:B", [], "recluster")
        assert lc.affected_utterance_ids == []


# ── SpeakerCandidate ───────────────────────────────────────────────────────


class TestSpeakerCandidate:
    def test_create_and_fields(self):
        emb = _embedding()
        cand = SpeakerCandidate(
            auto_id="auto:A",
            utterance_ids=["utt-001", "utt-002"],
            representative_embedding=emb,
            total_duration=3.0,
            utterance_count=2,
        )
        assert cand.auto_id == "auto:A"
        assert cand.utterance_ids == ["utt-001", "utt-002"]
        assert isinstance(cand.representative_embedding, np.ndarray)
        assert cand.total_duration == pytest.approx(3.0)
        assert cand.utterance_count == 2

    def test_representative_embedding_shape(self):
        emb = _embedding(512)
        cand = SpeakerCandidate("auto:B", [], emb, 0.0, 0)
        assert cand.representative_embedding.shape == (512,)

    def test_utterance_ids_mutable(self):
        cand = SpeakerCandidate("auto:C", ["utt-001"], _embedding(), 1.0, 1)
        cand.utterance_ids.append("utt-002")
        assert len(cand.utterance_ids) == 2


# ── Speaker ────────────────────────────────────────────────────────────────


class TestSpeaker:
    def _make(self, **overrides) -> Speaker:
        defaults: dict = dict(
            id=uuid4(),
            name="박○○",
            origin="stored",
            embedding_dim=192,
            model_id="pyannote/embedding",
            registered_at=None,
            first_seen=1_700_000_000.0,
            last_seen=1_700_000_001.0,
            utterance_count=3,
        )
        defaults.update(overrides)
        return Speaker(**defaults)

    def test_create_and_fields(self):
        uid = uuid4()
        spk = self._make(id=uid, name="김원장", origin="registered", registered_at=1_700_000_000.0)
        assert spk.id == uid
        assert spk.name == "김원장"
        assert spk.origin == "registered"
        assert spk.embedding_dim == 192
        assert spk.model_id == "pyannote/embedding"
        assert spk.registered_at == pytest.approx(1_700_000_000.0)
        assert spk.utterance_count == 3

    def test_frozen_prevents_mutation(self):
        spk = self._make()
        with pytest.raises(FrozenInstanceError):
            spk.name = "새이름"  # type: ignore[misc]

    def test_stored_registered_at_none(self):
        spk = self._make(origin="stored", registered_at=None)
        assert spk.registered_at is None

    def test_origin_values(self):
        for origin in ("registered", "stored"):
            spk = self._make(origin=origin)
            assert spk.origin == origin


# ── PersistMapping ─────────────────────────────────────────────────────────


class TestPersistMapping:
    def test_with_name(self):
        pm = PersistMapping(auto_id="auto:A", name="박○○")
        assert pm.auto_id == "auto:A"
        assert pm.name == "박○○"

    def test_name_defaults_none(self):
        pm = PersistMapping(auto_id="auto:B")
        assert pm.name is None

    def test_frozen_prevents_mutation(self):
        pm = PersistMapping("auto:A", "이름")
        with pytest.raises(FrozenInstanceError):
            pm.name = "다른이름"  # type: ignore[misc]


# ── MicrophoneGeometry ─────────────────────────────────────────────────────


class TestMicrophoneGeometry:
    def test_create_and_defaults(self):
        positions = np.zeros((2, 3), dtype=np.float64)
        positions[1, 0] = 0.1
        geo = MicrophoneGeometry(positions=positions)
        assert geo.reference_channel == 0
        np.testing.assert_array_equal(geo.positions, positions)

    def test_reference_channel_custom(self):
        positions = np.zeros((4, 3))
        geo = MicrophoneGeometry(positions=positions, reference_channel=2)
        assert geo.reference_channel == 2


# ── BeamformingConfig ──────────────────────────────────────────────────────


class TestBeamformingConfig:
    def test_defaults(self):
        cfg = BeamformingConfig()
        assert cfg.method == "mvdr"
        assert cfg.sample_rate == 16000
        assert cfg.n_fft == 512

    def test_custom_values(self):
        cfg = BeamformingConfig(method="ds", sample_rate=8000, n_fft=256)
        assert cfg.method == "ds"
        assert cfg.sample_rate == 8000
        assert cfg.n_fft == 256
