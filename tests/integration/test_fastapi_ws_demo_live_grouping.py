"""fastapi_ws_demo live grouping 통합 테스트 (PLAN-005-T-002, spec-07 §3 v0.1.1).

검증 대상:
  - labeled_word 이벤트 스키마 준수 (segment + stt final 결합 시 emit)
  - final_grouped 이벤트 스키마 준수 + done 직전 수신
  - 기존 5 이벤트 (segment, stt, relabel, done, error) 스키마 불변 확인

실행 조건:
    HF_TOKEN + ELEVENLABS_API_KEY 환경변수 필요.
    pytest tests/integration/test_fastapi_ws_demo_live_grouping.py -m integration -v

sine 입력에서는 STT final 이 발생하지 않으므로 labeled_word / final_grouped 이벤트 수신은
조건부 검증 (이벤트가 있을 때만 스키마 검사, utterances 는 empty 허용).
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


def _collect_events(wsc, max_iter: int = 300) -> list[dict]:
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


@pytest.mark.integration
class TestLiveGroupingEvents:
    """live grouping layer 신규 이벤트 검증 (PLAN-005-T-002)."""

    @pytest.fixture(autouse=True)
    def _skip_without_tokens(self):
        if not HF_TOKEN:
            pytest.skip("HF_TOKEN 없음 — integration test skip")
        if not ELEVENLABS_API_KEY:
            pytest.skip("ELEVENLABS_API_KEY 없음 — integration test skip")
        os.environ.setdefault("SPEAKER_ENGINE_STORAGE_URL", "memory://")

    def _get_app(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("starlette.testclient 없음")
        try:
            from examples.fastapi_ws_demo import app
        except ImportError as exc:
            pytest.skip(f"fastapi_ws_demo import 실패: {exc}")
        return TestClient(app), app

    def test_final_grouped_received_before_done(self):
        """final_grouped 이벤트가 done 이벤트보다 먼저 수신된다 (spec-07 §3)."""
        client, _ = self._get_app()
        one_sec = _sin_pcm(1.0)

        with client.websocket_connect("/audio/test-final-grouped") as wsc:
            for _ in range(30):
                wsc.send_bytes(one_sec)
            wsc.send_text(json.dumps({"type": "eof"}))
            received = _collect_events(wsc)

        event_types = [m["type"] for m in received]
        assert "done" in event_types, "done 이벤트를 수신하지 못함"
        assert "final_grouped" in event_types, (
            "final_grouped 이벤트를 수신하지 못함 — PLAN-005-T-002 DoD 위반"
        )

        done_idx = event_types.index("done")
        fg_idx = event_types.index("final_grouped")
        assert fg_idx < done_idx, (
            f"final_grouped({fg_idx}) 이 done({done_idx}) 보다 뒤에 수신됨 — spec-07 §3 순서 위반"
        )

    def test_final_grouped_schema(self):
        """final_grouped 이벤트가 spec-07 §3 스키마를 준수한다."""
        client, _ = self._get_app()
        one_sec = _sin_pcm(1.0)

        with client.websocket_connect("/audio/test-fg-schema") as wsc:
            for _ in range(30):
                wsc.send_bytes(one_sec)
            wsc.send_text(json.dumps({"type": "eof"}))
            received = _collect_events(wsc)

        fg_events = [m for m in received if m.get("type") == "final_grouped"]
        assert len(fg_events) == 1, f"final_grouped 이벤트 수: {len(fg_events)} (1 이어야 함)"

        fg = fg_events[0]
        assert "utterances" in fg, "final_grouped 에 utterances 필드 없음"
        assert isinstance(fg["utterances"], list), "final_grouped.utterances 가 list 아님"

        # utterances 가 있을 때만 내부 스키마 검증 (sine 에서는 empty 허용)
        for utt in fg["utterances"]:
            assert "label" in utt, "utterance 에 label 없음"
            assert "t_start" in utt, "utterance 에 t_start 없음"
            assert "t_end" in utt, "utterance 에 t_end 없음"
            assert "text" in utt, "utterance 에 text 없음"
            assert isinstance(utt["t_start"], (int, float)), "t_start 가 숫자 아님"
            assert isinstance(utt["t_end"], (int, float)), "t_end 가 숫자 아님"

    def test_final_grouped_utterances_time_ordered(self):
        """final_grouped.utterances 는 t_start 오름차순 정렬이다 (spec-07 §3)."""
        client, _ = self._get_app()
        one_sec = _sin_pcm(1.0)

        with client.websocket_connect("/audio/test-fg-order") as wsc:
            for _ in range(30):
                wsc.send_bytes(one_sec)
            wsc.send_text(json.dumps({"type": "eof"}))
            received = _collect_events(wsc)

        fg_events = [m for m in received if m.get("type") == "final_grouped"]
        assert fg_events, "final_grouped 이벤트 없음"
        utterances = fg_events[0]["utterances"]
        if len(utterances) >= 2:
            t_starts = [u["t_start"] for u in utterances]
            assert t_starts == sorted(t_starts), (
                f"final_grouped.utterances 가 t_start 순 정렬 아님: {t_starts}"
            )

    def test_labeled_word_schema_when_present(self):
        """수신된 labeled_word 이벤트가 spec-07 §3 스키마를 준수한다 (있을 때만)."""
        client, _ = self._get_app()
        one_sec = _sin_pcm(1.0)

        with client.websocket_connect("/audio/test-lw-schema") as wsc:
            for _ in range(30):
                wsc.send_bytes(one_sec)
            wsc.send_text(json.dumps({"type": "eof"}))
            received = _collect_events(wsc)

        lw_events = [m for m in received if m.get("type") == "labeled_word"]
        for lw in lw_events:
            assert "label" in lw, "labeled_word 에 label 없음"
            assert "t_start" in lw, "labeled_word 에 t_start 없음"
            assert "t_end" in lw, "labeled_word 에 t_end 없음"
            assert "text" in lw, "labeled_word 에 text 없음"
            assert "segment_id" in lw, "labeled_word 에 segment_id 없음"

    def test_no_new_event_breaks_existing_events(self):
        """labeled_word / final_grouped 추가 후 기존 이벤트 스키마 불변 확인 (spec-07 §3 보존)."""
        client, _ = self._get_app()
        one_sec = _sin_pcm(1.0)

        with client.websocket_connect("/audio/test-schema-compat") as wsc:
            for _ in range(30):
                wsc.send_bytes(one_sec)
            wsc.send_text(json.dumps({"type": "eof"}))
            received = _collect_events(wsc)

        event_types = {m["type"] for m in received}

        # utterance 는 spec-07 §3 에서 폐기 — 수신 시 오류
        assert "utterance" not in event_types, "utterance 이벤트가 수신됨 — spec-07 §3 폐기 위반"
        assert "done" in event_types, "done 이벤트를 수신하지 못함"

        for seg in [m for m in received if m.get("type") == "segment"]:
            assert "utterance_id" in seg
            assert "label" in seg
            assert "t_start" in seg
            assert "t_end" in seg
            assert "confidence" in seg
            assert "text" not in seg, "segment 에 text 필드 — spec-07 §3 위반"

        for stt in [m for m in received if m.get("type") == "stt"]:
            assert "t_start" in stt
            assert "t_end" in stt
            assert "text" in stt
            assert "is_final" in stt
            assert "label" not in stt, "stt 에 label 필드 — spec-07 §3 위반"
