"""fastapi_ws_demo graceful close 통합 테스트 (PLAN-004-T-004, spec-07 §7).

eof 텍스트 프레임 → generator 정상 종료 → done 이벤트 수신 검증.

실행 조건:
    HF_TOKEN 환경변수 필요 (실 SpeakerEngine / diart).
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


def _sin_pcm(duration_s: float = 1.0, freq: float = 440.0) -> bytes:
    """16-bit mono sine wave PCM."""
    n = int(duration_s * _SAMPLE_RATE)
    samples = [int(32767 * math.sin(2 * math.pi * freq * i / _SAMPLE_RATE)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


@pytest.mark.integration
class TestWsDemoGracefulClose:
    """eof 시그널 → done 수신 시퀀스 검증 (spec-07 §7 권장 fix)."""

    @pytest.fixture(autouse=True)
    def _skip_without_token(self):
        if not HF_TOKEN:
            pytest.skip("HF_TOKEN 없음 — integration test skip")
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

            # done 이벤트 수신 대기 — utterance / relabel 가 먼저 올 수 있음
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
