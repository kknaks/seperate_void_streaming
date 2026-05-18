"""unit tests — MultiDeviceMerge (H-05, spec-01 §2-3, spec-05 §2-2 unit).

합성 SpeakerSegment / LabelChange + stub engine (실 SpeakerEngine 호출 0).
seeded random embedding (spec-05 §4.1).
"""

from __future__ import annotations

import pytest
import numpy as np

from speaker_engine.multi.merge import MultiDeviceMerge
from speaker_engine.types import LabelChange, SpeakerSegment

_RNG = np.random.default_rng(0)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────


def _emb() -> np.ndarray:
    v = _RNG.standard_normal(16).astype(np.float32)
    return v / np.linalg.norm(v)


def _seg(utt_id: str, label: str, t_start: float, t_end: float | None = None) -> SpeakerSegment:
    return SpeakerSegment(
        utterance_id=utt_id,
        label=label,
        confidence=0.9,
        embedding=_emb(),
        audio=b"",
        t_start=t_start,
        t_end=t_end if t_end is not None else t_start + 1.0,
    )


def _change(old: str, new: str, utt_ids: list[str]) -> LabelChange:
    return LabelChange(
        old_label=old,
        new_label=new,
        affected_utterance_ids=list(utt_ids),
        reason="recluster",
    )


class _StubEngine:
    """SpeakerEngine duck-type stub — stream() 은 pre-defined events 를 yield."""

    def __init__(self, events: list[SpeakerSegment | LabelChange]) -> None:
        self._events = events

    async def stream(self):
        for event in self._events:
            yield event


async def _collect(merger: MultiDeviceMerge) -> list[SpeakerSegment | LabelChange]:
    return [ev async for ev in merger.stream()]


# ── 기본 동작 ─────────────────────────────────────────────────────────────────


class TestBasicMerge:
    async def test_two_engines_six_events(self) -> None:
        """2 engine 각 3건 → 6건 merge."""
        eng0 = _StubEngine([_seg("u1", "auto:A", 0.0), _seg("u2", "auto:A", 5.0), _seg("u3", "auto:A", 10.0)])
        eng1 = _StubEngine([_seg("u4", "auto:B", 2.0), _seg("u5", "auto:B", 3.0), _seg("u6", "auto:B", 8.0)])
        events = await _collect(MultiDeviceMerge([eng0, eng1]))
        assert len(events) == 6

    async def test_label_prefix_on_segment(self) -> None:
        """SpeakerSegment.label 에 dev{i}: prefix 부착."""
        eng0 = _StubEngine([_seg("u1", "auto:A", 0.0)])
        eng1 = _StubEngine([_seg("u2", "auto:B", 1.0)])
        events = await _collect(MultiDeviceMerge([eng0, eng1]))

        seg0 = next(e for e in events if isinstance(e, SpeakerSegment) and "dev0:" in e.label)
        seg1 = next(e for e in events if isinstance(e, SpeakerSegment) and "dev1:" in e.label)
        assert seg0.label == "dev0:auto:A"
        assert seg1.label == "dev1:auto:B"

    async def test_utterance_id_prefix(self) -> None:
        """SpeakerSegment.utterance_id 에 dev{i}: prefix 부착 (옵션 A)."""
        eng0 = _StubEngine([_seg("utt-001", "auto:A", 0.0)])
        eng1 = _StubEngine([_seg("utt-001", "auto:B", 1.0)])  # 동일 ID — prefix 로 분리
        events = await _collect(MultiDeviceMerge([eng0, eng1]))

        segs = [e for e in events if isinstance(e, SpeakerSegment)]
        utt_ids = [s.utterance_id for s in segs]
        assert "dev0:utt-001" in utt_ids
        assert "dev1:utt-001" in utt_ids

    async def test_label_change_prefix(self) -> None:
        """LabelChange.old_label / new_label / affected_utterance_ids 에 prefix 부착."""
        change = _change("auto:A", "stored:이지영", ["utt-001", "utt-002"])
        eng0 = _StubEngine([change])
        events = await _collect(MultiDeviceMerge([eng0, _StubEngine([])]))

        lc = next(e for e in events if isinstance(e, LabelChange))
        assert lc.old_label == "dev0:auto:A"
        assert lc.new_label == "dev0:stored:이지영"
        assert lc.affected_utterance_ids == ["dev0:utt-001", "dev0:utt-002"]

    async def test_registered_label_prefix(self) -> None:
        """registered: / stored: 라벨도 prefix 부착."""
        eng0 = _StubEngine([_seg("u1", "registered:김원장", 0.0)])
        events = await _collect(MultiDeviceMerge([eng0]))
        seg = events[0]
        assert isinstance(seg, SpeakerSegment)
        assert seg.label == "dev0:registered:김원장"


# ── 시간 정렬 ─────────────────────────────────────────────────────────────────


class TestTimeOrdering:
    async def test_interleaved_time_order(self) -> None:
        """engine 0 (t=0,5,10) + engine 1 (t=2,3,8) → 0/2/3/5/8/10."""
        eng0 = _StubEngine([
            _seg("u1", "auto:A", 0.0),
            _seg("u2", "auto:A", 5.0),
            _seg("u3", "auto:A", 10.0),
        ])
        eng1 = _StubEngine([
            _seg("u4", "auto:B", 2.0),
            _seg("u5", "auto:B", 3.0),
            _seg("u6", "auto:B", 8.0),
        ])
        events = await _collect(MultiDeviceMerge([eng0, eng1]))
        segs = [e for e in events if isinstance(e, SpeakerSegment)]
        t_starts = [s.t_start for s in segs]
        assert t_starts == sorted(t_starts), f"Not sorted: {t_starts}"
        assert t_starts == [0.0, 2.0, 3.0, 5.0, 8.0, 10.0]

    async def test_tiebreaker_engine_idx(self) -> None:
        """동시 t_start 시 engine index 오름차순 tiebreaker."""
        eng0 = _StubEngine([_seg("u0", "auto:A", 5.0)])
        eng1 = _StubEngine([_seg("u1", "auto:B", 5.0)])
        events = await _collect(MultiDeviceMerge([eng0, eng1]))
        segs = [e for e in events if isinstance(e, SpeakerSegment)]
        assert segs[0].label == "dev0:auto:A"
        assert segs[1].label == "dev1:auto:B"

    async def test_label_change_after_segments(self) -> None:
        """LabelChange (t_start 없음) → SpeakerSegment 뒤에 yield."""
        eng0 = _StubEngine([
            _seg("u1", "auto:A", 1.0),
            _change("auto:A", "stored:박○○", ["u1"]),
        ])
        eng1 = _StubEngine([_seg("u2", "auto:B", 0.5)])
        events = await _collect(MultiDeviceMerge([eng0, eng1]))
        # SpeakerSegment(t=0.5) 와 SpeakerSegment(t=1.0) 가 LabelChange 보다 앞
        segs = [e for e in events if isinstance(e, SpeakerSegment)]
        lcs = [e for e in events if isinstance(e, LabelChange)]
        assert len(segs) == 2
        assert len(lcs) == 1
        # 마지막 이벤트가 LabelChange 여야 함
        assert isinstance(events[-1], LabelChange)


# ── Edge case ─────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_engines_raises(self) -> None:
        """빈 list → ValueError."""
        with pytest.raises(ValueError):
            MultiDeviceMerge([])

    async def test_single_engine_prefix_dev0(self) -> None:
        """단일 engine → prefix dev0: 만 부착."""
        eng = _StubEngine([_seg("u1", "auto:A", 0.0), _seg("u2", "auto:A", 1.0)])
        events = await _collect(MultiDeviceMerge([eng]))
        for e in events:
            assert isinstance(e, SpeakerSegment)
            assert e.label.startswith("dev0:")
            assert e.utterance_id.startswith("dev0:")

    async def test_one_empty_engine_other_yields(self) -> None:
        """한 engine 이 빈 stream → 다른 engine 만 yield."""
        eng0 = _StubEngine([])
        eng1 = _StubEngine([_seg("u1", "auto:B", 0.0), _seg("u2", "auto:B", 1.0)])
        events = await _collect(MultiDeviceMerge([eng0, eng1]))
        assert len(events) == 2
        for e in events:
            assert isinstance(e, SpeakerSegment)
            assert e.label.startswith("dev1:")

    async def test_all_empty_engines_yields_nothing(self) -> None:
        """모든 engine 빈 stream → 이벤트 없음."""
        events = await _collect(MultiDeviceMerge([_StubEngine([]), _StubEngine([])]))
        assert events == []

    async def test_stream_twice_raises_runtime_error(self) -> None:
        """stream() 2회 진입 → RuntimeError (R2)."""
        merger = MultiDeviceMerge([_StubEngine([_seg("u1", "auto:A", 0.0)])])

        gen1 = merger.stream()
        await gen1.__anext__()  # _streaming = True

        with pytest.raises(RuntimeError):
            gen2 = merger.stream()
            await gen2.__anext__()

        await gen1.aclose()

    async def test_engine_exception_propagates(self) -> None:
        """engine 예외 → 전파."""

        class _FailEngine:
            async def stream(self):
                yield _seg("u1", "auto:A", 0.0)
                raise RuntimeError("engine internal failure")

        merger = MultiDeviceMerge([_FailEngine()])
        with pytest.raises(RuntimeError, match="engine internal failure"):
            await _collect(merger)

    async def test_three_engines_merge(self) -> None:
        """3 engine merge + prefix dev0/dev1/dev2."""
        eng0 = _StubEngine([_seg("u1", "auto:A", 0.0)])
        eng1 = _StubEngine([_seg("u2", "auto:B", 1.0)])
        eng2 = _StubEngine([_seg("u3", "auto:C", 0.5)])
        events = await _collect(MultiDeviceMerge([eng0, eng1, eng2]))
        segs = [e for e in events if isinstance(e, SpeakerSegment)]
        assert len(segs) == 3
        labels = [s.label for s in segs]
        assert "dev0:auto:A" in labels
        assert "dev1:auto:B" in labels
        assert "dev2:auto:C" in labels
        t_starts = [s.t_start for s in segs]
        assert t_starts == sorted(t_starts)

    async def test_mixed_segments_and_label_changes(self) -> None:
        """SpeakerSegment + LabelChange 혼합 merge."""
        eng0 = _StubEngine([
            _seg("u1", "auto:A", 0.0),
            _change("auto:A", "stored:홍길동", ["u1"]),
            _seg("u3", "stored:홍길동", 5.0),
        ])
        eng1 = _StubEngine([
            _seg("u2", "auto:B", 2.0),
        ])
        events = await _collect(MultiDeviceMerge([eng0, eng1]))
        assert len(events) == 4
        segs = [e for e in events if isinstance(e, SpeakerSegment)]
        lcs = [e for e in events if isinstance(e, LabelChange)]
        assert len(segs) == 3
        assert len(lcs) == 1
        assert lcs[0].old_label == "dev0:auto:A"
        assert lcs[0].new_label == "dev0:stored:홍길동"

    async def test_original_events_unchanged(self) -> None:
        """원본 SpeakerSegment 변경 없음 (복사본에만 prefix)."""
        original = _seg("utt-001", "auto:A", 0.0)
        eng = _StubEngine([original])
        await _collect(MultiDeviceMerge([eng]))
        # 원본 변경 없어야 함
        assert original.label == "auto:A"
        assert original.utterance_id == "utt-001"
