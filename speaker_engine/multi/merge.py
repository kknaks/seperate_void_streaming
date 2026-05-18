"""MultiDeviceMerge — N engine 출력 시간 기준 merge (H-05, spec-01 §2-3)."""

from __future__ import annotations

import dataclasses
import heapq
from typing import TYPE_CHECKING, AsyncIterator

from speaker_engine.types import LabelChange, SpeakerSegment

if TYPE_CHECKING:
    from speaker_engine.engine import SpeakerEngine

# LabelChange 는 t_start 없음 → heap 정렬 시 맨 뒤로 (SpeakerSegment 보다 후순위)
_LABEL_CHANGE_T: float = float("inf")


def _prefix_event(
    idx: int,
    event: SpeakerSegment | LabelChange,
) -> SpeakerSegment | LabelChange:
    """dev{idx}: prefix를 label/utterance_id에 부착한 복사본 반환."""
    p = f"dev{idx}:"
    if isinstance(event, SpeakerSegment):
        return dataclasses.replace(
            event,
            label=p + event.label,
            utterance_id=p + event.utterance_id,
        )
    # LabelChange
    return dataclasses.replace(
        event,
        old_label=p + event.old_label,
        new_label=p + event.new_label,
        affected_utterance_ids=[p + uid for uid in event.affected_utterance_ids],
    )


class MultiDeviceMerge:
    """
    N 개의 독립 SpeakerEngine 인스턴스 출력을 시간 기준으로 merge.

    각 engine 의 SpeakerSegment.label / utterance_id 에 디바이스 prefix 를 붙여
    namespace 충돌을 방지한다.
    (예: engine 0 의 "auto:A" → "dev0:auto:A", "utt-001" → "dev0:utt-001")

    Parameters
    ----------
    engines : list[SpeakerEngine]
        각각 독립 실행 가능한 SpeakerEngine 인스턴스 목록. 비어 있으면 ValueError.
        SpeakerStore 공유는 사용처 책임.
    """

    def __init__(self, engines: list[SpeakerEngine]) -> None:
        if not engines:
            raise ValueError("engines must be a non-empty list")
        self._engines: list[SpeakerEngine] = list(engines)
        self._streaming: bool = False

    async def stream(self) -> AsyncIterator[SpeakerSegment | LabelChange]:
        """
        모든 engine 의 이벤트를 t_start 오름차순으로 merge yield.
        동시 t_start 는 engine index 오름차순 tiebreaker.
        한 인스턴스에 2회 진입 시 RuntimeError (R2).
        """
        if self._streaming:
            raise RuntimeError(
                "MultiDeviceMerge.stream() is already active on this instance (R2). "
                "Create a new instance for a new session."
            )
        self._streaming = True

        # heap entry: (t_start, engine_idx, insert_counter, event)
        # - t_start: SpeakerSegment.t_start 또는 _LABEL_CHANGE_T (LabelChange)
        # - engine_idx: 동시 t_start 시 tiebreaker (오름차순)
        # - insert_counter: 동일 engine 내 삽입 순서 (tuple 비교 시 event 자체 비교 방지)
        heap: list[tuple[float, int, int, SpeakerSegment | LabelChange]] = []
        gens: list[AsyncIterator[SpeakerSegment | LabelChange]] = []
        counter = 0

        try:
            gens = [engine.stream() for engine in self._engines]  # type: ignore[attr-defined]
            active: set[int] = set(range(len(gens)))

            # 각 engine 에서 첫 이벤트 fetch → heap 에 초기 적재
            for i, gen in enumerate(gens):
                try:
                    event = await gen.__anext__()
                    t = event.t_start if isinstance(event, SpeakerSegment) else _LABEL_CHANGE_T
                    heapq.heappush(heap, (t, i, counter, event))
                    counter += 1
                except StopAsyncIteration:
                    active.discard(i)

            while heap:
                t, i, _, event = heapq.heappop(heap)
                yield _prefix_event(i, event)

                # 해당 engine 의 다음 이벤트 fetch
                if i in active:
                    try:
                        next_event = await gens[i].__anext__()
                        t_next = (
                            next_event.t_start
                            if isinstance(next_event, SpeakerSegment)
                            else _LABEL_CHANGE_T
                        )
                        heapq.heappush(heap, (t_next, i, counter, next_event))
                        counter += 1
                    except StopAsyncIteration:
                        active.discard(i)

        finally:
            # 활성 generator 정리 (engine 예외 / 조기 종료 시에도 aclose 보장)
            for gen in gens:
                try:
                    await gen.aclose()
                except Exception:
                    pass
            self._streaming = False

    async def __aenter__(self) -> MultiDeviceMerge:
        for engine in self._engines:
            if hasattr(engine, "__aenter__"):
                await engine.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        for engine in self._engines:
            if hasattr(engine, "__aexit__"):
                await engine.__aexit__(exc_type, exc, tb)
