"""Unit tests for ServerVAD + ElevenLabsSTT server VAD integration (PLAN-006-T-007).

webrtcvad 는 결정론적 C 확장 — 실제 라이브러리 사용 (mock 없음).
silence = 올-제로 bytes (webrtcvad.is_speech → False 검증 완료)
speech  = 사인파 PCM   (webrtcvad.is_speech → True 검증 완료)
"""

from __future__ import annotations

import math
import struct
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

from server.stt.vad import ServerVAD, _FRAME_BYTES, _FRAME_MS, _SAMPLE_RATE
from server.stt.elevenlabs import ElevenLabsSTT

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

_SINE_AMP = 3000  # webrtcvad aggressiveness=2 에서 speech 로 분류되는 진폭


def _silence(ms: int) -> bytes:
    """지정 시간(ms)의 silence PCM (all-zero)."""
    n_samples = int(_SAMPLE_RATE * ms / 1000)
    return b"\x00" * (n_samples * 2)


def _speech(ms: int) -> bytes:
    """지정 시간(ms)의 speech PCM (440Hz 사인파)."""
    n_samples = int(_SAMPLE_RATE * ms / 1000)
    samples = [
        int(_SINE_AMP * math.sin(2 * math.pi * 440 * i / _SAMPLE_RATE))
        for i in range(n_samples)
    ]
    return struct.pack(f"<{n_samples}h", *samples)


# ---------------------------------------------------------------------------
# ServerVAD unit
# ---------------------------------------------------------------------------


def test_vad_commit_triggered_after_long_silence():
    """speech → silence 600ms → on_silence 1회 호출."""
    calls: list[int] = []
    vad = ServerVAD(on_silence=lambda: calls.append(1), aggressiveness=2, silence_ms=500)

    vad.feed(_speech(300))
    assert calls == [], "speech 중 on_silence 불가"

    vad.feed(_silence(600))
    assert len(calls) == 1, "600ms silence → on_silence 1회"


def test_vad_no_commit_on_short_silence():
    """speech → silence 200ms → on_silence 호출 없음 (threshold=500ms 미달)."""
    calls: list[int] = []
    vad = ServerVAD(on_silence=lambda: calls.append(1), aggressiveness=2, silence_ms=500)

    vad.feed(_speech(300))
    vad.feed(_silence(200))
    assert calls == [], "200ms silence 는 threshold 미달 — on_silence 불가"


def test_vad_no_commit_without_prior_speech():
    """선행 speech 없이 silence 만 입력되면 on_silence 호출 안 됨."""
    calls: list[int] = []
    vad = ServerVAD(on_silence=lambda: calls.append(1), aggressiveness=2, silence_ms=500)

    vad.feed(_silence(600))
    assert calls == [], "speech 없이 silence 만 → on_silence 불가"


def test_vad_multiple_commits():
    """speech → silence → speech → silence → on_silence 2회."""
    calls: list[int] = []
    vad = ServerVAD(on_silence=lambda: calls.append(1), aggressiveness=2, silence_ms=500)

    vad.feed(_speech(300))
    vad.feed(_silence(600))
    assert len(calls) == 1

    vad.feed(_speech(300))
    vad.feed(_silence(600))
    assert len(calls) == 2, "두 번째 phrase 후 on_silence 2번째"


def test_vad_frame_alignment_unaligned_chunks():
    """불규칙 크기 chunk 를 나눠 넣어도 내부 버퍼가 올바르게 정렬."""
    calls: list[int] = []
    vad = ServerVAD(on_silence=lambda: calls.append(1), aggressiveness=2, silence_ms=500)

    full_speech = _speech(300)
    full_silence = _silence(600)

    # 7 bytes 씩 쪼개서 넣기 (프레임 960 bytes 와 무관한 크기)
    chunk_size = 7
    for i in range(0, len(full_speech), chunk_size):
        vad.feed(full_speech[i : i + chunk_size])
    for i in range(0, len(full_silence), chunk_size):
        vad.feed(full_silence[i : i + chunk_size])

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# ElevenLabsSTT server VAD 통합 (use_server_vad=True)
# ---------------------------------------------------------------------------


class _FakeWS:
    def __init__(self, incoming: list[str]) -> None:
        self._incoming = list(incoming)
        self._sent: list[str] = []
        self._closed = False

    async def send(self, data: str) -> None:
        self._sent.append(data)

    async def close(self) -> None:
        self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        import asyncio
        await asyncio.sleep(0)
        for msg in self._incoming:
            if self._closed:
                return
            yield msg
            await asyncio.sleep(0)


def _make_stt_with_vad(
    incoming: list[str],
    silence_ms: int = 500,
) -> tuple[ElevenLabsSTT, _FakeWS]:
    fake_ws = _FakeWS(incoming)

    @asynccontextmanager
    async def _connect(*args, **kwargs):
        yield fake_ws

    stt = ElevenLabsSTT(
        api_key="test-key-1234",
        language="ko",
        commit_strategy="manual",
        use_server_vad=True,
        vad_silence_ms=silence_ms,
        vad_aggressiveness=2,
    )
    stt._connect_patch = patch("websockets.connect", side_effect=_connect)
    return stt, fake_ws


async def test_server_vad_triggers_commit_message():
    """speech feed → silence feed (500ms+) → commit 메시지가 WS 로 전송되어야 함.

    큐를 미리 채운 뒤 stream() 을 호출 (기존 테스트 패턴과 동일).
    VAD on_silence 는 feed() 내 동기 호출 → _COMMIT_SIGNAL 이 큐에 즉시 적재.
    """
    stt, fake_ws = _make_stt_with_vad(incoming=[])

    # feed() → VAD → put_nowait(_COMMIT_SIGNAL) 모두 동기 경로
    await stt.feed(_speech(300))
    await stt.feed(_silence(600))  # 600ms > 500ms threshold → VAD fires
    await stt.close()              # 잔여 final commit 용 None 추가

    with stt._connect_patch:
        async for _ in stt.stream():
            pass

    commit_sends = [
        s for s in fake_ws._sent
        if '"commit": true' in s or '"commit":true' in s
    ]
    assert len(commit_sends) >= 1, "VAD silence 후 commit 메시지 1회 이상 전송되어야 함"


async def test_server_vad_short_silence_no_mid_commit():
    """speech → silence 200ms → on_silence 없음 → close() 시 commit 1회만."""
    stt, fake_ws = _make_stt_with_vad(incoming=[], silence_ms=500)

    await stt.feed(_speech(300))
    await stt.feed(_silence(200))  # 200ms < 500ms → VAD 미트리거
    await stt.close()              # manual commit 1회만

    with stt._connect_patch:
        async for _ in stt.stream():
            pass

    commit_sends = [
        s for s in fake_ws._sent
        if '"commit": true' in s or '"commit":true' in s
    ]
    assert len(commit_sends) == 1, "짧은 silence 는 VAD commit 없음 — close 1회만"


async def test_external_commit_method():
    """commit() 외부 직접 호출 시 commit 메시지가 WS 로 전송되어야 함."""
    stt, fake_ws = _make_stt_with_vad(incoming=[])

    await stt.feed(_speech(100))
    await stt.commit()   # 외부 명시 commit
    await stt.close()    # 잔여 final commit

    with stt._connect_patch:
        async for _ in stt.stream():
            pass

    commit_sends = [
        s for s in fake_ws._sent
        if '"commit": true' in s or '"commit":true' in s
    ]
    assert len(commit_sends) >= 1, "commit() 직접 호출 → commit 메시지 전송"
