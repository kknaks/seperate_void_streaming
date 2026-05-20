"""SpeakerEngine 단위 테스트 (spec-05 §2-2 unit 카테고리, PLAN-003-T-015).

외부 의존 제거 전략:
- DiartAdapter / OnlineSpeakerClusterer : engine 모듈 내 이름 patch (diart 미설치 환경)
- WaveformBuffer : stream() 테스트 시 patch 하여 feed/drain_queue 직접 제어
- MemoryStore : 실 in-memory 인스턴스 사용 (외부 의존 0, spec-05 §4.2)
- embedding : seeded random + hand-crafted unit vector (spec-05 §4.1)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import numpy as np
import pytest

from speaker_engine.diart_adapter import RawSpeakerEvent
from speaker_engine.engine import SpeakerEngine, _UtteranceRecord
from speaker_engine.exceptions import StorageError
from speaker_engine.storage.memory import MemoryStore
from speaker_engine.types import (
    LabelChange,
    PersistMapping,
    SpeakerCandidate,
    SpeakerSegment,
)

# ─────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

D = 4  # 테스트용 embedding 차원 (작게)


def unit_vec(*vals: float) -> np.ndarray:
    """hand-crafted unit vector."""
    v = np.array(vals, dtype=float)
    return v / np.linalg.norm(v)


def rng_emb(seed: int = 0) -> np.ndarray:
    """seeded random unit vector (spec-05 §4.1)."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(D)
    return v / np.linalg.norm(v)


def make_raw_event(
    g_spk: int = 0,
    seed: int = 0,
    t_start: float = 0.0,
    t_end: float = 1.0,
    confidence: float = 0.9,
) -> RawSpeakerEvent:
    emb = rng_emb(seed)
    return RawSpeakerEvent(
        local_speaker_id=g_spk,
        embedding=emb,
        audio=b"\x00\x00" * 160,
        t_start=t_start,
        t_end=t_end,
        confidence=confidence,
    )


async def empty_source() -> AsyncIterator[bytes]:
    """바이트를 하나도 yield 하지 않는 source."""
    return
    yield  # noqa: unreachable — make it an async generator


async def pcm_source(n_chunks: int = 1) -> AsyncIterator[bytes]:
    """유효 PCM 청크를 n_chunks 번 yield (1600 bytes = 100ms @ 16kHz 16-bit)."""
    chunk = b"\x00\x00" * 800  # 800 int16 samples = 1600 bytes (짝수, validate_pcm 통과)
    for _ in range(n_chunks):
        yield chunk


# ─────────────────────────────────────────────────────────────────────────────
# 픽스처 — 컴포넌트 mock
# ─────────────────────────────────────────────────────────────────────────────

def make_mock_diart(embedding_dim: int = D) -> MagicMock:
    m = MagicMock()
    m.embedding_dim = embedding_dim
    m.process_window = AsyncMock(return_value=[])
    m.close = AsyncMock()
    return m


def make_mock_clusterer(
    centers: np.ndarray | None = None,
    active_centers: set[int] | None = None,
    delta_new: float = 1.0,
) -> MagicMock:
    m = MagicMock()
    m.centers = centers
    m.active_centers = active_centers if active_centers is not None else set()
    m.delta_new = delta_new
    m._max_speakers = 20
    m.identify = MagicMock(return_value=MagicMock(valid_assignments=MagicMock(return_value=([], []))))
    return m


def make_mock_buffer(events: list[RawSpeakerEvent] | None = None) -> MagicMock:
    """WaveformBuffer 목 — feed() 는 no-op, drain_queue() 는 첫 호출에 events 반환."""
    m = MagicMock()
    m.feed = AsyncMock(return_value=None)
    # 첫 drain_queue 호출에서 events 반환, 이후 빈 list
    first_batch = list(events) if events else []
    m.drain_queue = MagicMock(side_effect=[first_batch] + [[]] * 100)
    m.flush = AsyncMock(return_value=[])
    return m


def make_engine(
    mock_diart: MagicMock | None = None,
    mock_clusterer: MagicMock | None = None,
    store: MemoryStore | None = None,
    registered_speakers: dict[str, np.ndarray] | None = None,
) -> tuple[SpeakerEngine, MagicMock, MagicMock]:
    """SpeakerEngine 을 mocked 컴포넌트로 생성 (diart / clusterer patch 사용)."""
    diart = mock_diart or make_mock_diart()
    clusterer = mock_clusterer or make_mock_clusterer()
    mem_store = store or MemoryStore()

    with (
        patch("speaker_engine.engine.DiartAdapter", return_value=diart),
        patch("speaker_engine.engine.OnlineSpeakerClusterer", return_value=clusterer),
        patch("speaker_engine.engine.from_url", return_value=mem_store),
    ):
        engine = SpeakerEngine(
            storage_url="memory://",
            hf_token="fake-token",
            registered_speakers=registered_speakers,
        )

    # 내부 컴포넌트를 mocked 버전으로 교체 (already done via patch)
    return engine, diart, clusterer


# ─────────────────────────────────────────────────────────────────────────────
# __init__ 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestInit:
    def test_missing_hf_token_raises_environment_error(self):
        """env HF_TOKEN 없음 + 인자 없음 → EnvironmentError (spec-01 §5)."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(EnvironmentError, match="HF_TOKEN"):
                SpeakerEngine(storage_url="memory://")

    def test_missing_storage_url_raises_environment_error(self):
        """env SPEAKER_ENGINE_STORAGE_URL 없음 + 인자 없음 → EnvironmentError."""
        with patch.dict("os.environ", {"HF_TOKEN": "tok"}, clear=True):
            with (
                patch("speaker_engine.engine.OnlineSpeakerClusterer"),
                patch("speaker_engine.engine.DiartAdapter"),
                pytest.raises(EnvironmentError, match="SPEAKER_ENGINE_STORAGE_URL"),
            ):
                SpeakerEngine(hf_token="tok")

    def test_cuda_unavailable_raises_runtime_error(self):
        """device='cuda' + CUDA 없음 → RuntimeError (DiartAdapter 에서 전파)."""
        with (
            patch("speaker_engine.engine.OnlineSpeakerClusterer"),
            patch(
                "speaker_engine.engine.DiartAdapter",
                side_effect=RuntimeError("CUDA unavailable"),
            ),
            patch("speaker_engine.engine.from_url", return_value=MemoryStore()),
            pytest.raises(RuntimeError, match="CUDA"),
        ):
            SpeakerEngine(storage_url="memory://", hf_token="tok", device="cuda")

    def test_five_components_created(self):
        """5 컴포넌트 인스턴스 생성 + storage 연결 검증."""
        engine, diart, clusterer = make_engine()
        assert engine._diart is diart
        assert engine._clusterer is clusterer
        assert engine._identifier is not None
        assert engine._scheduler is not None
        assert engine._finalizer is not None
        assert engine._store is not None

    def test_utterance_id_initially_zero(self):
        """세션 시작 전 counter 는 0."""
        engine, _, _ = make_engine()
        assert engine._utterance_counter == 0

    def test_stream_active_initially_false(self):
        engine, _, _ = make_engine()
        assert engine._stream_active is False

    def test_finalized_initially_false(self):
        engine, _, _ = make_engine()
        assert engine._finalized is False


# ─────────────────────────────────────────────────────────────────────────────
# async with 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestAsyncWith:
    async def test_aenter_calls_init_schema(self):
        """__aenter__ → store.init_schema 호출 확인."""
        engine, diart, _ = make_engine()
        engine._store = MagicMock()
        engine._store.init_schema = AsyncMock()
        engine._store.register = AsyncMock()

        await engine.__aenter__()
        engine._store.init_schema.assert_called_once_with(
            embedding_dim=diart.embedding_dim,
            model_id=engine._embedding_model,
        )

    async def test_aenter_registers_registered_speakers(self):
        """registered_speakers 있으면 __aenter__ 시 store.register 호출."""
        emb = rng_emb(42)
        engine, _, _ = make_engine(registered_speakers={"이지영": emb})
        engine._store = MagicMock()
        engine._store.init_schema = AsyncMock()
        engine._store.register = AsyncMock()

        await engine.__aenter__()
        assert engine._store.register.call_count == 1
        call_args = engine._store.register.call_args
        assert call_args[0][0] == "이지영"

    async def test_aexit_calls_finalize(self):
        """__aexit__ → finalize() 자동 호출."""
        engine, _, _ = make_engine()
        engine.finalize = AsyncMock(return_value=[])

        await engine.__aexit__(None, None, None)
        engine.finalize.assert_called_once()

    async def test_aexit_skips_finalize_if_already_finalized(self):
        """이미 finalize 됐으면 __aexit__ 가 중복 호출 안 함."""
        engine, _, _ = make_engine()
        engine._finalized = True
        engine.finalize = AsyncMock(return_value=[])

        await engine.__aexit__(None, None, None)
        engine.finalize.assert_not_called()

    async def test_context_manager_flow(self):
        """async with engine: → __aenter__ + __aexit__ 자동."""
        engine, diart, _ = make_engine()
        engine._store = MagicMock()
        engine._store.init_schema = AsyncMock()
        engine._store.register = AsyncMock()
        engine.finalize = AsyncMock(return_value=[])

        async with engine:
            pass

        engine._store.init_schema.assert_called_once()
        engine.finalize.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# stream() 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestStream:
    async def _collect(
        self,
        engine: SpeakerEngine,
        mock_buf: MagicMock,
        n_chunks: int = 1,
    ) -> list[SpeakerSegment | LabelChange]:
        """stream() 이벤트 수집 헬퍼. WaveformBuffer 를 mock_buf 로 교체."""
        events = []
        with patch("speaker_engine.engine.WaveformBuffer", return_value=mock_buf):
            async for ev in engine.stream(pcm_source(n_chunks)):
                events.append(ev)
        return events

    async def test_speaker_segment_yielded(self):
        """mock RawSpeakerEvent → SpeakerSegment yield."""
        engine, _, _ = make_engine()
        raw = make_raw_event(g_spk=0, seed=1)
        mock_buf = make_mock_buffer(events=[raw])

        events = await self._collect(engine, mock_buf)

        assert len(events) == 1
        seg = events[0]
        assert isinstance(seg, SpeakerSegment)
        assert seg.label == "auto:A"
        assert seg.utterance_id == "utt-001"

    async def test_utterance_id_monotonically_increasing(self):
        """utterance_id 는 utt-001, utt-002 ... 단조 증가 (spec-01 §3)."""
        engine, _, _ = make_engine()
        raw1 = make_raw_event(g_spk=0, seed=1)
        raw2 = make_raw_event(g_spk=1, seed=2)
        mock_buf = make_mock_buffer(events=[raw1, raw2])

        events = await self._collect(engine, mock_buf)

        ids = [e.utterance_id for e in events if isinstance(e, SpeakerSegment)]
        assert ids == ["utt-001", "utt-002"]

    async def test_registered_hit_label(self):
        """registered match → 'registered:이지영' 라벨 SpeakerSegment."""
        engine, _, _ = make_engine()
        raw = make_raw_event(g_spk=0, seed=1)
        mock_buf = make_mock_buffer(events=[raw])

        engine._identifier.match = AsyncMock(return_value=("registered:이지영", None))

        events = await self._collect(engine, mock_buf)

        assert len(events) == 1
        assert events[0].label == "registered:이지영"

    async def test_auto_fallback_label(self):
        """3-tier 모두 miss → 'auto:A' 라벨."""
        engine, _, _ = make_engine()
        raw = make_raw_event(g_spk=0, seed=1)
        mock_buf = make_mock_buffer(events=[raw])
        engine._identifier.match = AsyncMock(return_value=("", None))

        events = await self._collect(engine, mock_buf)

        assert events[0].label == "auto:A"

    async def test_stored_match_yields_label_change_for_prior_auto(self):
        """stored match 최초 성립 → prior auto:A utterance LabelChange yield (spec-01 §4-1 step 7).

        첫 청크: raw1 → auto:A
        두번째 청크: raw2 → stored:박○○ + LabelChange(old=auto:A, new=stored:박○○)
        """
        engine, _, _ = make_engine()

        raw1 = make_raw_event(g_spk=0, seed=1)
        raw2 = make_raw_event(g_spk=0, seed=2)

        engine._identifier.match = AsyncMock(
            side_effect=[("", None), ("stored:박○○", MagicMock())]
        )
        # 첫번째 청크: raw1, 두번째 청크: raw2
        mock_buf = make_mock_buffer()
        mock_buf.drain_queue = MagicMock(side_effect=[[raw1], [raw2]] + [[]] * 100)

        events = await self._collect(engine, mock_buf, n_chunks=2)

        segments = [e for e in events if isinstance(e, SpeakerSegment)]
        changes = [e for e in events if isinstance(e, LabelChange)]

        assert segments[0].label == "auto:A"
        assert segments[1].label == "stored:박○○"
        assert len(changes) == 1
        assert changes[0].reason == "stored_match"
        assert changes[0].old_label == "auto:A"
        assert changes[0].new_label == "stored:박○○"
        assert "utt-001" in changes[0].affected_utterance_ids

    async def test_stored_match_reuses_cache_for_same_letter(self):
        """첫 utterance 가 이미 stored 라벨 → 두번째는 캐시, LabelChange 없음."""
        engine, _, _ = make_engine()

        raw1 = make_raw_event(g_spk=0, seed=1)
        raw2 = make_raw_event(g_spk=0, seed=2)

        # 두 이벤트 모두 stored hit
        engine._identifier.match = AsyncMock(
            side_effect=[("stored:박○○", MagicMock()), ("stored:박○○", MagicMock())]
        )
        mock_buf = make_mock_buffer(events=[raw1, raw2])

        events = await self._collect(engine, mock_buf)

        changes = [e for e in events if isinstance(e, LabelChange)]
        # raw1 이 첫 stored match: prior auto:A utterance 없으므로 LabelChange 없음
        # raw2 는 캐시로 처리 → LabelChange 없음
        assert len(changes) == 0

    async def test_stream_twice_raises_runtime_error(self):
        """동일 인스턴스에 stream() 2회 진입 → RuntimeError (R2)."""
        engine, _, _ = make_engine()
        engine._stream_active = True  # 직접 플래그 세팅으로 R2 시뮬레이션

        with pytest.raises(RuntimeError, match="2회"):
            async for _ in engine.stream(empty_source()):
                pass

    async def test_stream_resets_active_flag_on_completion(self):
        """stream() 완료 후 _stream_active 는 False 로 리셋."""
        engine, _, _ = make_engine()
        mock_buf = make_mock_buffer()

        with patch("speaker_engine.engine.WaveformBuffer", return_value=mock_buf):
            async for _ in engine.stream(empty_source()):
                pass

        assert engine._stream_active is False

    async def test_adaptive_scheduler_trigger_yields_label_change(self):
        """AdaptiveReclusterScheduler 트리거 → LabelChange(reason='recluster') yield (R3)."""
        engine, _, mock_clusterer = make_engine()

        centers_arr = np.stack([rng_emb(0), rng_emb(1)])
        mock_clusterer.centers = centers_arr
        mock_clusterer.active_centers = {0, 1}
        mock_clusterer.delta_new = 1.0

        raw1 = make_raw_event(g_spk=0, seed=1)
        engine._identifier.match = AsyncMock(return_value=("", None))
        mock_buf = make_mock_buffer(events=[raw1])

        engine._scheduler.should_trigger = MagicMock(return_value=True)
        engine._scheduler.recluster = MagicMock(
            return_value=[
                LabelChange(
                    old_label="auto:A",
                    new_label="auto:B",
                    affected_utterance_ids=["utt-001"],
                    reason="recluster",
                )
            ]
        )

        events = await self._collect(engine, mock_buf)

        changes = [e for e in events if isinstance(e, LabelChange)]
        assert len(changes) == 1
        assert changes[0].reason == "recluster"

    async def test_pcm_validation_error_propagates(self):
        """PCM 포맷 위반 → ValueError (spec-01 §5)."""
        engine, _, _ = make_engine()
        bad_chunk = b"\x00" * 3  # 홀수 바이트

        async def bad_source():
            yield bad_chunk

        mock_buf = make_mock_buffer()

        with (
            patch("speaker_engine.engine.WaveformBuffer", return_value=mock_buf),
            pytest.raises(ValueError),
        ):
            async for _ in engine.stream(bad_source()):
                pass


# ─────────────────────────────────────────────────────────────────────────────
# finalize() 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestFinalize:
    async def test_finalize_returns_speaker_candidates(self):
        """finalize() → list[SpeakerCandidate] 반환."""
        engine, _, _ = make_engine()
        # 발화 없는 세션 → 빈 candidates
        candidates = await engine.finalize()
        assert isinstance(candidates, list)
        assert candidates == []

    async def test_finalize_idempotent(self):
        """finalize() 2회 → 동일 결과 반환 (멱등)."""
        engine, _, _ = make_engine()
        c1 = await engine.finalize()
        c2 = await engine.finalize()
        assert c1 == c2

    async def test_finalize_sets_finalized_flag(self):
        """finalize() 후 _finalized = True."""
        engine, _, _ = make_engine()
        await engine.finalize()
        assert engine._finalized is True

    async def test_finalize_drain_timeout(self):
        """finalize() drain timeout → TimeoutError (R4)."""
        engine, _, _ = make_engine()
        # _buffer 를 timeout 걸리는 mock 으로 설정
        slow_buf = MagicMock()
        slow_buf.flush = AsyncMock(side_effect=asyncio.TimeoutError())
        engine._buffer = slow_buf

        # asyncio.wait_for 가 TimeoutError 를 발생시키도록 patch
        with (
            patch("speaker_engine.engine.asyncio.wait_for", side_effect=asyncio.TimeoutError()),
            pytest.raises(TimeoutError, match="drain 시간 초과"),
        ):
            await engine.finalize(timeout=0.001)

    async def test_aexit_auto_finalize(self):
        """async with → __aexit__ 자동 finalize."""
        engine, diart, _ = make_engine()
        engine._store = MagicMock()
        engine._store.init_schema = AsyncMock()
        engine._store.register = AsyncMock()

        async with engine:
            pass

        assert engine._finalized is True

    async def test_finalize_runs_final_reclusterer(self):
        """finalize() 가 FinalReclusterer.finalize 호출."""
        engine, _, _ = make_engine()

        # 발화 1개 추가
        emb = rng_emb(0)
        engine._utterances.append(
            _UtteranceRecord("utt-001", "auto:A", emb, False, 0.0, 1.0)
        )
        engine._finalizer.finalize = MagicMock(return_value=([], []))

        await engine.finalize()

        engine._finalizer.finalize.assert_called_once()

    async def test_finalize_no_raise_when_reclusterer_raises(self):
        """FinalReclusterer.finalize 가 RuntimeError 던져도 finalize() 는 정상 반환 (Bug C fix).

        35 clusters > max_letters=20 케이스를 시뮬레이션.
        """
        from unittest.mock import patch

        engine, _, _ = make_engine()
        emb = rng_emb(0)
        for i in range(5):
            engine._utterances.append(
                _UtteranceRecord(f"utt-{i:03d}", "auto:A", emb, False, float(i), float(i + 1))
            )

        with patch("speaker_engine.engine.FinalReclusterer") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.finalize = MagicMock(
                side_effect=RuntimeError("FinalReclusterer: 35 clusters exceed max_letters=20")
            )
            mock_cls.return_value = mock_instance

            result = await engine.finalize()

        # RuntimeError 가 전파되지 않고 빈 list 반환
        assert isinstance(result, list)
        assert engine._finalized is True

    async def test_t_start_session_relative_not_monotonic(self):
        """stream() SpeakerSegment.t_start 는 session-relative (Bug B fix).

        _session_start = time.monotonic() (~1e6) 을 raw_event.t_start 에 더하지 않는지 확인.
        raw_event.t_start = 2.5 → segment.t_start = 2.5, not 1729414 + 2.5
        """
        engine, _, _ = make_engine()
        engine._session_start = 1_729_414.0  # 큰 monotonic 값 강제 설정

        raw = make_raw_event(g_spk=0, seed=1, t_start=2.5, t_end=5.0)
        mock_buf = make_mock_buffer(events=[raw])

        events = []
        with patch("speaker_engine.engine.WaveformBuffer", return_value=mock_buf):
            async for ev in engine.stream(pcm_source(1)):
                events.append(ev)

        segments = [e for e in events if isinstance(e, SpeakerSegment)]
        assert len(segments) >= 1
        seg = segments[0]
        # session-relative: 2.5, not 1729416.5
        assert seg.t_start == pytest.approx(2.5)
        assert seg.t_end == pytest.approx(5.0)


# ─────────────────────────────────────────────────────────────────────────────
# persist() 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestPersist:
    async def test_persist_before_finalize_raises(self):
        """finalize() 전 persist() → RuntimeError."""
        engine, _, _ = make_engine()
        with pytest.raises(RuntimeError, match="finalize"):
            await engine.persist([PersistMapping("auto:A", "이지영")])

    async def test_persist_invalid_auto_id_raises(self):
        """존재하지 않는 auto_id → ValueError."""
        engine, _, _ = make_engine()
        engine._finalized = True
        engine._candidates = []

        with pytest.raises(ValueError, match="auto_id"):
            await engine.persist([PersistMapping("auto:Z", "없음")])

    async def test_persist_returns_speakers(self):
        """유효 매핑 → SpeakerStore.save 호출 + Speaker 반환."""
        from speaker_engine.types import Speaker

        engine, diart, _ = make_engine()
        emb = rng_emb(0)
        engine._finalized = True
        engine._candidates = [
            SpeakerCandidate(
                auto_id="auto:A",
                utterance_ids=["utt-001"],
                representative_embedding=emb,
                total_duration=1.0,
                utterance_count=1,
            )
        ]

        fake_speaker = Speaker(
            id=uuid4(),
            name="이지영",
            origin="stored",
            embedding_dim=D,
            model_id="pyannote/embedding",
            registered_at=None,
            first_seen=0.0,
            last_seen=0.0,
            utterance_count=1,
        )
        engine._store.save = AsyncMock(return_value=fake_speaker)

        speakers = await engine.persist([PersistMapping("auto:A", "이지영")])

        engine._store.save.assert_called_once()
        assert len(speakers) == 1
        assert speakers[0].name == "이지영"

    async def test_persist_name_none_passes_none_to_store(self):
        """name=None → store.save(name=None, ...) 호출 (anon 자동 부여는 Store 책임)."""
        from speaker_engine.types import Speaker

        engine, _, _ = make_engine()
        emb = rng_emb(0)
        engine._finalized = True
        engine._candidates = [
            SpeakerCandidate("auto:A", ["utt-001"], emb, 1.0, 1)
        ]

        fake_speaker = Speaker(uuid4(), "anon_001", "stored", D, "pyannote/embedding", None, 0.0, 0.0, 1)
        engine._store.save = AsyncMock(return_value=fake_speaker)

        await engine.persist([PersistMapping("auto:A", None)])

        engine._store.save.assert_called_once_with(None, emb, engine._embedding_model)


# ─────────────────────────────────────────────────────────────────────────────
# 위임 메서드 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestDelegation:
    async def test_set_alias_delegates_to_store(self):
        engine, _, _ = make_engine()
        sid = uuid4()
        engine._store.set_alias = AsyncMock()

        await engine.set_alias(sid, "새이름")
        engine._store.set_alias.assert_called_once_with(sid, "새이름")

    async def test_merge_speakers_delegates_to_store(self):
        engine, _, _ = make_engine()
        src = uuid4()
        tgt = uuid4()
        engine._store.merge = AsyncMock()

        await engine.merge_speakers(src, tgt)
        engine._store.merge.assert_called_once_with(src, tgt)

    async def test_delete_speaker_delegates_to_store(self):
        engine, _, _ = make_engine()
        sid = uuid4()
        engine._store.delete = AsyncMock()

        await engine.delete_speaker(sid)
        engine._store.delete.assert_called_once_with(sid)


# ─────────────────────────────────────────────────────────────────────────────
# StorageError backoff 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestStorageRetry:
    async def test_temporary_failure_then_success(self):
        """StorageError 1회 후 성공 → 재시도 후 반환."""
        engine, _, _ = make_engine()
        result_val = object()
        call_count = 0

        async def flaky(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise StorageError("임시 단절")
            return result_val

        with patch("speaker_engine.engine.asyncio.sleep", new_callable=AsyncMock):
            result = await engine._with_storage_retry(flaky)

        assert result is result_val
        assert call_count == 2

    async def test_three_failures_raise_storage_error(self):
        """3회 모두 실패 → StorageError raise."""
        engine, _, _ = make_engine()

        async def always_fail(*args, **kwargs):
            raise StorageError("영구 단절")

        with (
            patch("speaker_engine.engine.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(StorageError),
        ):
            await engine._with_storage_retry(always_fail)


# ─────────────────────────────────────────────────────────────────────────────
# utterance_id 단조 증가 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestUtteranceId:
    def test_gen_utterance_id_monotonic(self):
        """_gen_utterance_id 는 utt-001, utt-002, utt-003 순서 (spec-01 §3)."""
        engine, _, _ = make_engine()
        ids = [engine._gen_utterance_id() for _ in range(5)]
        assert ids == ["utt-001", "utt-002", "utt-003", "utt-004", "utt-005"]


# ─────────────────────────────────────────────────────────────────────────────
# WS Race R1-R5 정책 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestWSRace:
    async def test_r2_reentry_raises_immediately(self):
        """R2: stream() 2회 진입 → RuntimeError (adr-05)."""
        engine, _, _ = make_engine()
        engine._stream_active = True

        with pytest.raises(RuntimeError, match="2회"):
            async for _ in engine.stream(empty_source()):
                pass

    async def test_r4_drain_timeout_raises_timeout_error(self):
        """R4: finalize() drain timeout → TimeoutError."""
        engine, _, _ = make_engine()
        slow_buf = MagicMock()
        slow_buf.flush = AsyncMock(side_effect=asyncio.TimeoutError())
        engine._buffer = slow_buf

        with (
            patch("speaker_engine.engine.asyncio.wait_for", side_effect=asyncio.TimeoutError()),
            pytest.raises(TimeoutError),
        ):
            await engine.finalize(timeout=0.001)

    async def test_r5_event_order_preserved(self):
        """R5: SpeakerSegment yield 순서 == 발생 순서 (단일 출력 큐 — async generator 보장)."""
        engine, _, _ = make_engine()
        engine._identifier.match = AsyncMock(return_value=("", None))

        raw1 = make_raw_event(g_spk=0, seed=1, t_start=0.0, t_end=1.0)
        raw2 = make_raw_event(g_spk=1, seed=2, t_start=1.0, t_end=2.0)
        mock_buf = make_mock_buffer(events=[raw1, raw2])

        events = []
        with patch("speaker_engine.engine.WaveformBuffer", return_value=mock_buf):
            async for ev in engine.stream(pcm_source(1)):
                events.append(ev)

        segs = [e for e in events if isinstance(e, SpeakerSegment)]
        assert len(segs) == 2
        assert segs[0].t_start <= segs[1].t_start


# ─────────────────────────────────────────────────────────────────────────────
# import 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestPublicImport:
    def test_speaker_engine_importable_from_package(self):
        """speaker_engine 패키지에서 SpeakerEngine import 가능."""
        from speaker_engine import SpeakerEngine as SE  # noqa: F401
        assert SE is SpeakerEngine

    def test_from_url_importable(self):
        from speaker_engine import from_url  # noqa: F401
        assert callable(from_url)

    def test_all_public_types_importable(self):
        from speaker_engine import (  # noqa: F401
            LabelChange,
            PersistMapping,
            Speaker,
            SpeakerCandidate,
            SpeakerSegment,
        )
