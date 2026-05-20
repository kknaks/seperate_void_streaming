"""WaveformBuffer — 10s sliding window 누적기 (spec-03 §2-2, adr-05 R1)."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING, Any

import numpy as np

from speaker_engine.audio.format import bytes_to_float32

if TYPE_CHECKING:
    from speaker_engine.diart_adapter import DiartAdapter, RawSpeakerEvent

WINDOW_SIZE: int = 16000 * 10   # 10초 × 16kHz
HOP_SIZE: int = 16000 * 1       # 1초 hop
DEFAULT_QUEUE_MAXSIZE: int = 100
_SAMPLE_RATE: int = 16_000


class WaveformBuffer:
    """asyncio.Queue 기반 10초 sliding window 누적기.

    feed() 로 PCM bytes 를 넣으면 window 가 채워질 때마다
    DiartAdapter.process_window() 를 호출하고 결과를 내부 큐에 넣는다.
    flush() 는 잔량을 zero-pad 해서 마지막 window 를 처리한다.
    """

    def __init__(
        self,
        adapter: "DiartAdapter",
        queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
    ) -> None:
        self._adapter = adapter
        self._queue: asyncio.Queue[list[Any]] = asyncio.Queue(maxsize=queue_maxsize)
        self._buffer: deque[float] = deque()
        self._samples_consumed: int = 0  # cumulative hop samples popped (Bug B fix)

    async def feed(self, chunk: bytes) -> None:
        """PCM bytes → float32 변환 후 내부 버퍼 append.

        window_size(10s) 채워지면 adapter.process_window() 호출 후 1초 hop.
        큐가 꽉 찬 경우 await 으로 backpressure 흡수 (adr-05 R1).
        """
        samples = bytes_to_float32(chunk)
        self._buffer.extend(samples.tolist())

        while len(self._buffer) >= WINDOW_SIZE:
            # Bug B fix: compute session-relative offset before processing
            window_offset = self._samples_consumed / _SAMPLE_RATE
            window = np.array(list(self._buffer)[:WINDOW_SIZE], dtype=np.float32)
            events = await self._adapter.process_window(window)
            # Shift t_start/t_end to session-relative seconds (spec-01 §3)
            for ev in events:
                ev.t_start += window_offset
                ev.t_end += window_offset
            # backpressure: 큐 full 시 await (R1)
            await self._queue.put(events)
            for _ in range(HOP_SIZE):
                self._buffer.popleft()
            self._samples_consumed += HOP_SIZE

    def drain_queue(self) -> "list[RawSpeakerEvent]":
        """큐에 있는 이벤트 배치를 모두 꺼내어 반환 (non-blocking).

        SpeakerEngine.stream() 이 feed() 후 호출하는 소비 경로.
        backpressure 는 feed() 안의 queue.put await 에서 발생 (R1).
        """
        result: list[Any] = []
        while True:
            try:
                batch = self._queue.get_nowait()
                result.extend(batch)
            except asyncio.QueueEmpty:
                break
        return result

    async def flush(self) -> "list[RawSpeakerEvent]":
        """버퍼 잔량을 zero-pad 후 process_window 호출. finalize 시 사용.

        잔량이 0이면 빈 목록 반환.
        큐에 남은 결과 + flush 결과를 합쳐 반환.
        """
        result: list[Any] = []

        # 큐에 남은 이벤트 drain
        while not self._queue.empty():
            result.extend(self._queue.get_nowait())

        if not self._buffer:
            return result

        # Bug B fix: flush window starts at current consumed offset
        window_offset = self._samples_consumed / _SAMPLE_RATE
        # 잔량 zero-pad → WINDOW_SIZE
        remaining = list(self._buffer)
        pad_len = WINDOW_SIZE - len(remaining)
        padded = np.array(remaining + [0.0] * pad_len, dtype=np.float32)
        events = await self._adapter.process_window(padded)
        for ev in events:
            ev.t_start += window_offset
            ev.t_end += window_offset
        result.extend(events)
        self._buffer.clear()
        return result


__all__ = [
    "WaveformBuffer",
    "WINDOW_SIZE",
    "HOP_SIZE",
    "DEFAULT_QUEUE_MAXSIZE",
]
