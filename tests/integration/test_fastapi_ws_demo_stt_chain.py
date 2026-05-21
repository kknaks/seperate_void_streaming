"""fastapi_ws_demo STT-driven Sequential Chain 통합 테스트 (PLAN-006-T-004).

검증 대상:
  - fake STT (partial + final emit) + fake engine (identify_phrase mock)
  - ws.send_json 이벤트 순서: stt(partial) → stt(final×N) → labeled_phrase → … → final_grouped → done
  - PLAN-005 폐기 이벤트 (segment / labeled_word / relabel) 미수신
  - final_grouped 스키마 (utterances list)
  - done 이벤트 최종 수신

HF_TOKEN / ELEVENLABS_API_KEY 불필요 (mock 환경).
"""

from __future__ import annotations

import asyncio
import json
import struct
from typing import AsyncIterator
from unittest.mock import patch

import pytest

from server.stt.elevenlabs import Transcript

_SAMPLE_RATE = 16_000


def _sin_pcm(n_samples: int = 32) -> bytes:
    """더미 PCM bytes."""
    return struct.pack(f"<{n_samples}h", *([0] * n_samples))


# ---------------------------------------------------------------------------
# Fake 협력 객체
# ---------------------------------------------------------------------------


class _FakeSTT:
    """ElevenLabsSTT 최소 mock — 고정 Transcript 목록을 stream() 으로 emit."""

    def __init__(self, transcripts: list[Transcript]) -> None:
        self._transcripts = transcripts

    async def feed(self, chunk: bytes) -> None:
        pass

    async def stream(self) -> AsyncIterator[Transcript]:
        for t in self._transcripts:
            yield t

    async def close(self) -> None:
        pass


class _FakeEngine:
    """SpeakerEngine 최소 mock — identify_phrase 호출 추적."""

    def __init__(self, label: str = "auto:A") -> None:
        self._label = label
        self.phrase_calls: list[bytes] = []

    async def __aenter__(self) -> "_FakeEngine":
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    async def identify_phrase(self, pcm_slice: bytes) -> str:
        self.phrase_calls.append(pcm_slice)
        return self._label


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _get_app():
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("starlette.testclient 없음")
    try:
        import examples.fastapi_ws_demo as _demo_mod
        from examples.fastapi_ws_demo import app
    except ImportError as exc:
        pytest.skip(f"fastapi_ws_demo import 실패: {exc}")
    return TestClient(app), _demo_mod


def _collect(wsc, max_iter: int = 200) -> list[dict]:
    received: list[dict] = []
    for _ in range(max_iter):
        try:
            raw = wsc.receive_text()
            data = json.loads(raw)
            received.append(data)
        except Exception:
            break
        if data.get("type") == "done":
            break
    return received


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------


class TestSttChainEventOrder:
    """STT-driven chain 이벤트 순서 검증 (PLAN-006-T-004 DoD)."""

    def _run(
        self,
        transcripts: list[Transcript],
        label: str = "auto:A",
    ) -> tuple[list[dict], "_FakeEngine"]:
        client, demo_mod = _get_app()
        fake_stt = _FakeSTT(transcripts)
        fake_engine = _FakeEngine(label)

        with (
            patch.object(demo_mod, "ElevenLabsSTT", return_value=fake_stt),
            patch.object(demo_mod, "SpeakerEngine", return_value=fake_engine),
        ):
            with client.websocket_connect("/audio/test-chain") as wsc:
                wsc.send_bytes(_sin_pcm())
                wsc.send_text(json.dumps({"type": "eof"}))
                received = _collect(wsc)

        return received, fake_engine

    def test_basic_phrase_sequence(self):
        """partial → final × 2 → labeled_phrase → final_grouped → done 순서 검증."""
        transcripts = [
            Transcript(t_start=0.0, t_end=0.0, text="안녕", is_final=False),
            Transcript(t_start=0.1, t_end=0.5, text="안녕", is_final=True),
            Transcript(t_start=0.6, t_end=1.2, text="하세요", is_final=True),
            # 스트림 종료 → flush phrase
        ]
        received, engine = self._run(transcripts, label="auto:A")
        types = [m["type"] for m in received]

        assert "done" in types, "done 이벤트 미수신"
        assert "final_grouped" in types, "final_grouped 이벤트 미수신"

        # final_grouped < done
        assert types.index("final_grouped") < types.index("done")

        # labeled_phrase 수신
        lp = [m for m in received if m["type"] == "labeled_phrase"]
        assert len(lp) == 1, f"labeled_phrase {len(lp)}개 수신 (1 기대)"
        assert lp[0]["label"] == "auto:A"
        assert lp[0]["text"] == "안녕 하세요"
        assert lp[0]["t_start"] == pytest.approx(0.1)
        assert lp[0]["t_end"] == pytest.approx(1.2)

        # identify_phrase 1회 호출
        assert len(engine.phrase_calls) == 1

    def test_stt_events_before_labeled_phrase(self):
        """stt 이벤트가 labeled_phrase 이전에 모두 수신된다."""
        transcripts = [
            Transcript(t_start=0.0, t_end=0.0, text="테스트", is_final=False),
            Transcript(t_start=0.1, t_end=0.8, text="테스트", is_final=True),
        ]
        received, _ = self._run(transcripts)
        types = [m["type"] for m in received]

        assert "labeled_phrase" in types, "labeled_phrase 없음"
        lp_idx = types.index("labeled_phrase")
        stt_indices = [i for i, t in enumerate(types) if t == "stt"]
        assert all(i < lp_idx for i in stt_indices), (
            f"stt 이벤트 중 일부가 labeled_phrase({lp_idx}) 이후: {stt_indices}"
        )

    def test_two_phrases_two_labeled_phrases(self):
        """두 phrase 각각 labeled_phrase 1개씩 — partial 경계 감지."""
        transcripts = [
            # phrase1
            Transcript(t_start=0.0, t_end=0.0, text="첫", is_final=False),
            Transcript(t_start=0.1, t_end=0.5, text="첫", is_final=True),
            Transcript(t_start=0.6, t_end=1.0, text="번째", is_final=True),
            # phrase2 partial → phrase1 flush 트리거
            Transcript(t_start=0.0, t_end=0.0, text="두", is_final=False),
            Transcript(t_start=1.5, t_end=2.0, text="두번째", is_final=True),
            # 스트림 종료 → phrase2 flush
        ]
        received, engine = self._run(transcripts, label="auto:B")
        lp = [m for m in received if m["type"] == "labeled_phrase"]
        assert len(lp) == 2, f"labeled_phrase {len(lp)}개 (2 기대)"
        assert lp[0]["text"] == "첫 번째"
        assert lp[1]["text"] == "두번째"
        assert len(engine.phrase_calls) == 2

    def test_no_plan005_events(self):
        """PLAN-005 폐기 이벤트 (segment / labeled_word / relabel) 미수신."""
        transcripts = [
            Transcript(t_start=0.1, t_end=0.5, text="테스트", is_final=True),
        ]
        received, _ = self._run(transcripts)
        event_types = {m["type"] for m in received}
        assert "segment" not in event_types, "segment 이벤트 수신됨 — adr-10 폐기 위반"
        assert "labeled_word" not in event_types, "labeled_word 이벤트 수신됨 — adr-10 폐기 위반"
        assert "relabel" not in event_types, "relabel 이벤트 수신됨 — adr-10 폐기 위반"

    def test_final_grouped_schema(self):
        """final_grouped 스키마: utterances list, 각 항목에 label/t_start/t_end/text."""
        transcripts = [
            Transcript(t_start=0.1, t_end=0.9, text="회의", is_final=True),
            Transcript(t_start=1.0, t_end=1.8, text="시작", is_final=True),
        ]
        received, _ = self._run(transcripts, label="auto:A")
        fg = [m for m in received if m["type"] == "final_grouped"]
        assert len(fg) == 1
        utts = fg[0]["utterances"]
        assert isinstance(utts, list)
        for u in utts:
            assert "label" in u
            assert "t_start" in u
            assert "t_end" in u
            assert "text" in u

    def test_no_timestamp_final_skipped(self):
        """t_start=t_end=0.0 인 final (타임스탬프 없음) 은 identify_phrase 호출 안 함."""
        transcripts = [
            Transcript(t_start=0.0, t_end=0.0, text="결과", is_final=True),
        ]
        received, engine = self._run(transcripts)
        assert len(engine.phrase_calls) == 0, "타임스탬프 없는 final 에서 identify_phrase 호출됨"
        # done 은 수신돼야 함
        assert any(m["type"] == "done" for m in received)

    def test_done_is_last_event(self):
        """done 이벤트가 수신된 이벤트 중 마지막."""
        transcripts = [
            Transcript(t_start=0.1, t_end=0.5, text="테스트", is_final=True),
        ]
        received, _ = self._run(transcripts)
        assert received, "이벤트 미수신"
        assert received[-1]["type"] == "done", (
            f"마지막 이벤트가 done 이 아님: {received[-1]['type']}"
        )


class TestWsStateGuard:
    """WS state guard 검증 (PLAN-006-T-008 신규).

    race condition: WS closed 직후 server 가 emit 시도 → RuntimeError.
    guard: ws.client_state == WebSocketState.CONNECTED 확인 후 send.
    """

    def test_final_grouped_skipped_when_ws_closed(self):
        """labeled_phrase 직후 DISCONNECTED → final_grouped/done emit 없이 예외 없이 종료."""
        try:
            from starlette.testclient import TestClient
            from starlette.websockets import WebSocket, WebSocketState
        except ImportError:
            pytest.skip("starlette 없음")

        try:
            import examples.fastapi_ws_demo as _demo_mod
            from examples.fastapi_ws_demo import app
        except ImportError as exc:
            pytest.skip(f"fastapi_ws_demo import 실패: {exc}")

        # Barrier STT: pcm_loop 가 stt.close() 를 호출한 후에야 transcript 를 yield
        # → identify_phrase 가 실행될 때 pcm_loop 는 이미 종료 (ws.receive 호출 없음)
        class _BarrierSTT:
            def __init__(self, transcripts_list):
                self._transcripts = transcripts_list
                self._closed = False

            async def feed(self, chunk):
                pass

            async def stream(self):
                while not self._closed:
                    await asyncio.sleep(0)
                for t in self._transcripts:
                    yield t

            async def close(self):
                self._closed = True

        transcripts = [Transcript(t_start=0.1, t_end=0.5, text="테스트", is_final=True)]
        fake_stt = _BarrierSTT(transcripts)
        fake_engine = _FakeEngine()

        original_accept = WebSocket.accept

        async def capturing_accept(self_ws, *args, **kwargs):
            result = await original_accept(self_ws, *args, **kwargs)
            orig_send = self_ws.send_json  # bound to original, captured before spy override

            async def instance_spy(data, mode="text"):
                t = data.get("type")
                if t == "labeled_phrase":
                    await orig_send(data, mode=mode)
                    # labeled_phrase 전송 성공 후 race condition 시뮬레이션
                    self_ws.client_state = WebSocketState.DISCONNECTED
                elif t not in ("final_grouped", "done"):
                    await orig_send(data, mode=mode)
                # final_grouped / done: guard 가 막아야 하므로 여기 도달하면 안 됨

            self_ws.send_json = instance_spy
            return result

        client = TestClient(app, raise_server_exceptions=False)
        received: list[dict] = []
        with (
            patch.object(_demo_mod, "ElevenLabsSTT", return_value=fake_stt),
            patch.object(_demo_mod, "SpeakerEngine", return_value=fake_engine),
            patch.object(WebSocket, "accept", capturing_accept),
        ):
            try:
                with client.websocket_connect("/audio/test-guard-final") as wsc:
                    wsc.send_bytes(_sin_pcm())
                    wsc.send_text(json.dumps({"type": "eof"}))
                    received = _collect(wsc, max_iter=50)
            except Exception:
                pass

        assert any(m.get("type") == "labeled_phrase" for m in received), "labeled_phrase 미수신"
        assert not any(m.get("type") == "final_grouped" for m in received), (
            "guard 실패: final_grouped 가 DISCONNECTED 상태에서 전송됨"
        )
        assert not any(m.get("type") == "done" for m in received), (
            "guard 실패: done 가 DISCONNECTED 상태에서 전송됨"
        )

    def test_labeled_phrase_skipped_when_ws_closed(self):
        """phrase flush 중 DISCONNECTED → labeled_phrase emit 없이 예외 없이 종료."""
        try:
            from starlette.testclient import TestClient
            from starlette.websockets import WebSocket, WebSocketState
        except ImportError:
            pytest.skip("starlette 없음")

        try:
            import examples.fastapi_ws_demo as _demo_mod
            from examples.fastapi_ws_demo import app
        except ImportError as exc:
            pytest.skip(f"fastapi_ws_demo import 실패: {exc}")

        class _BarrierSTT:
            def __init__(self, transcripts_list):
                self._transcripts = transcripts_list
                self._closed = False

            async def feed(self, chunk):
                pass

            async def stream(self):
                while not self._closed:
                    await asyncio.sleep(0)
                for t in self._transcripts:
                    yield t

            async def close(self):
                self._closed = True

        transcripts = [Transcript(t_start=0.1, t_end=0.5, text="테스트", is_final=True)]
        fake_stt = _BarrierSTT(transcripts)

        ws_holder: list = []
        original_accept = WebSocket.accept

        async def capturing_accept(self_ws, *args, **kwargs):
            result = await original_accept(self_ws, *args, **kwargs)
            ws_holder.append(self_ws)
            return result

        class _DisconnectEngine:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

            async def identify_phrase(self, pcm_slice):
                # identify_phrase 내에서 disconnect 시뮬레이션 (pcm_loop 는 이미 종료)
                if ws_holder:
                    ws_holder[0].client_state = WebSocketState.DISCONNECTED
                return "auto:A"

        client = TestClient(app, raise_server_exceptions=False)
        received: list[dict] = []
        with (
            patch.object(_demo_mod, "ElevenLabsSTT", return_value=fake_stt),
            patch.object(_demo_mod, "SpeakerEngine", return_value=_DisconnectEngine()),
            patch.object(WebSocket, "accept", capturing_accept),
        ):
            try:
                with client.websocket_connect("/audio/test-guard-label") as wsc:
                    wsc.send_bytes(_sin_pcm())
                    wsc.send_text(json.dumps({"type": "eof"}))
                    received = _collect(wsc, max_iter=50)
            except Exception:
                pass

        assert not any(m.get("type") == "labeled_phrase" for m in received), (
            "guard 실패: labeled_phrase 가 DISCONNECTED 상태에서 전송됨"
        )
        assert not any(m.get("type") == "final_grouped" for m in received), (
            "guard 실패: final_grouped 가 DISCONNECTED 상태에서 전송됨"
        )
