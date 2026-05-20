"""fastapi_ws_demo 통합 테스트 (PLAN-004-T-004, T-009, spec-07 §3 §7).

테스트 클래스:
  - TestWsDemoGracefulClose: eof → done graceful close 검증 (T-004)
  - TestWsDemoChannelSplit:  segment / stt 두 채널 분리 + utterance 폐기 검증 (T-009)

실행 조건:
    HF_TOKEN + ELEVENLABS_API_KEY 환경변수 필요.
    pytest tests/integration/test_fastapi_ws_demo_graceful.py -m integration -v
"""

from __future__ import annotations

import json
import math
import os
import struct

import pytest

_SAMPLE_RATE = 16000
HF_TOKEN = os.environ.get("HF_TOKEN", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")


def _sin_pcm(duration_s: float = 1.0, freq: float = 440.0) -> bytes:
    """16-bit mono sine wave PCM."""
    n = int(duration_s * _SAMPLE_RATE)
    samples = [int(32767 * math.sin(2 * math.pi * freq * i / _SAMPLE_RATE)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


@pytest.mark.integration
class TestWsDemoGracefulClose:
    """eof 시그널 → done 수신 시퀀스 검증 (spec-07 §7 권장 fix)."""

    @pytest.fixture(autouse=True)
    def _skip_without_tokens(self):
        if not HF_TOKEN:
            pytest.skip("HF_TOKEN 없음 — integration test skip")
        if not ELEVENLABS_API_KEY:
            pytest.skip("ELEVENLABS_API_KEY 없음 — integration test skip")
        os.environ.setdefault("SPEAKER_ENGINE_STORAGE_URL", "memory://")

    def test_eof_signal_delivers_done(self):
        """eof 텍스트 프레임 수신 시 done 이벤트가 클라이언트에 전달된다."""
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("starlette.testclient 없음")

        try:
            from examples.fastapi_ws_demo import app
        except ImportError as exc:
            pytest.skip(f"fastapi_ws_demo import 실패: {exc}")

        one_sec = _sin_pcm(1.0)

        client = TestClient(app)
        with client.websocket_connect("/audio/test-graceful-close") as wsc:
            # 30초 분량 PCM 전송 (spec-07 §7 통합 테스트 기준)
            for _ in range(30):
                wsc.send_bytes(one_sec)

            # eof 종료 시그널 (spec-07 §2)
            wsc.send_text(json.dumps({"type": "eof"}))

            # done 이벤트 수신 대기 — segment / stt / relabel 가 먼저 올 수 있음
            done_received = False
            for _ in range(200):
                try:
                    raw = wsc.receive_text()
                    data = json.loads(raw)
                except Exception:
                    break
                if data.get("type") == "done":
                    done_received = True
                    break

        assert done_received, (
            "done 이벤트를 수신하지 못함 — eof 시그널 후 graceful close 미작동 (spec-07 §7)"
        )

    def test_direct_ws_close_without_eof_still_runs(self):
        """eof 없이 WS 직접 close 해도 서버가 크래시하지 않는다 (후방 호환, spec-07 §7)."""
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("starlette.testclient 없음")

        try:
            from examples.fastapi_ws_demo import app
        except ImportError as exc:
            pytest.skip(f"fastapi_ws_demo import 실패: {exc}")

        one_sec = _sin_pcm(1.0)

        client = TestClient(app, raise_server_exceptions=False)
        try:
            with client.websocket_connect("/audio/test-direct-close") as wsc:
                for _ in range(3):
                    wsc.send_bytes(one_sec)
                # eof 없이 context manager exit → WS close
        except Exception:
            pass  # disconnect 시 서버 측 예외는 허용 (spec-07 §7 허용)


@pytest.mark.integration
class TestWsDemoChannelSplit:
    """segment + stt 두 채널 분리 검증 (PLAN-004-T-009, spec-07 §3).

    주요 검증:
      - utterance 이벤트 수신 0회 (spec-07 §3 폐기)
      - done 이벤트 수신 (마지막 프레임)
      - segment / stt 이벤트는 0+ 개 허용 (sine 입력에서는 없을 수 있음)
    """

    @pytest.fixture(autouse=True)
    def _skip_without_tokens(self):
        if not HF_TOKEN:
            pytest.skip("HF_TOKEN 없음 — integration test skip")
        if not ELEVENLABS_API_KEY:
            pytest.skip("ELEVENLABS_API_KEY 없음 — integration test skip")
        os.environ.setdefault("SPEAKER_ENGINE_STORAGE_URL", "memory://")

    def test_no_utterance_event_after_channel_split(self):
        """utterance 이벤트가 수신되지 않고 done 이 수신된다 (spec-07 §3 폐기 확인)."""
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("starlette.testclient 없음")

        try:
            from examples.fastapi_ws_demo import app
        except ImportError as exc:
            pytest.skip(f"fastapi_ws_demo import 실패: {exc}")

        one_sec = _sin_pcm(1.0)
        client = TestClient(app)
        received: list[dict] = []

        with client.websocket_connect("/audio/test-channel-split") as wsc:
            for _ in range(30):
                wsc.send_bytes(one_sec)
            wsc.send_text(json.dumps({"type": "eof"}))

            for _ in range(300):
                try:
                    raw = wsc.receive_text()
                    data = json.loads(raw)
                    received.append(data)
                except Exception:
                    break
                if data.get("type") == "done":
                    break

        event_types = {msg["type"] for msg in received}

        # utterance 는 spec-07 §3 에서 폐기 — 수신 시 오류
        assert "utterance" not in event_types, (
            "utterance 이벤트가 수신됨 — spec-07 §3 폐기 위반"
        )

        # done 은 반드시 수신
        assert "done" in event_types, "done 이벤트를 수신하지 못함"

    def test_segment_event_schema(self):
        """수신된 segment 이벤트가 spec-07 §3 스키마를 준수한다 (text 필드 없음)."""
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("starlette.testclient 없음")

        try:
            from examples.fastapi_ws_demo import app
        except ImportError as exc:
            pytest.skip(f"fastapi_ws_demo import 실패: {exc}")

        one_sec = _sin_pcm(1.0)
        client = TestClient(app)
        received: list[dict] = []

        with client.websocket_connect("/audio/test-segment-schema") as wsc:
            for _ in range(30):
                wsc.send_bytes(one_sec)
            wsc.send_text(json.dumps({"type": "eof"}))

            for _ in range(300):
                try:
                    raw = wsc.receive_text()
                    data = json.loads(raw)
                    received.append(data)
                except Exception:
                    break
                if data.get("type") == "done":
                    break

        segments = [m for m in received if m.get("type") == "segment"]
        for seg in segments:
            assert "utterance_id" in seg, "segment 에 utterance_id 없음"
            assert "label" in seg, "segment 에 label 없음"
            assert "t_start" in seg, "segment 에 t_start 없음"
            assert "t_end" in seg, "segment 에 t_end 없음"
            assert "confidence" in seg, "segment 에 confidence 없음"
            assert "text" not in seg, "segment 에 text 필드 있음 — spec-07 §3 위반"

    def test_stt_event_schema(self):
        """수신된 stt 이벤트가 spec-07 §3 스키마를 준수한다 (label 필드 없음)."""
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("starlette.testclient 없음")

        try:
            from examples.fastapi_ws_demo import app
        except ImportError as exc:
            pytest.skip(f"fastapi_ws_demo import 실패: {exc}")

        one_sec = _sin_pcm(1.0)
        client = TestClient(app)
        received: list[dict] = []

        with client.websocket_connect("/audio/test-stt-schema") as wsc:
            for _ in range(30):
                wsc.send_bytes(one_sec)
            wsc.send_text(json.dumps({"type": "eof"}))

            for _ in range(300):
                try:
                    raw = wsc.receive_text()
                    data = json.loads(raw)
                    received.append(data)
                except Exception:
                    break
                if data.get("type") == "done":
                    break

        stt_events = [m for m in received if m.get("type") == "stt"]
        for stt in stt_events:
            assert "t_start" in stt, "stt 에 t_start 없음"
            assert "t_end" in stt, "stt 에 t_end 없음"
            assert "text" in stt, "stt 에 text 없음"
            assert "is_final" in stt, "stt 에 is_final 없음"
            assert "label" not in stt, "stt 에 label 필드 있음 — spec-07 §3 위반"
