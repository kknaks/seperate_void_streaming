"""ElevenLabsSTT — ElevenLabs Realtime streaming STT 어댑터 (spec-06 §1, §3).

인터페이스:
    async def feed(self, chunk: bytes) -> None
    async def stream(self) -> AsyncIterator[Transcript]
    async def commit(self) -> None          # server VAD 또는 외부 수동 commit
    async def close(self) -> None

WS 재연결 정책: fail-fast (§OQ-06-2 항목 1 결정).
partial/final 노출: 둘 다 emit (§OQ-06-2 항목 2 결정).
commit_strategy: "manual" (기본, PLAN-006-T-007) 또는 "vad" (legacy).
  manual — server VAD (use_server_vad=True) 또는 외부 commit() 호출로 phrase commit.
           close() 시 잔여 음성 최종 commit.
  vad   — ElevenLabs 자동 silence 감지 (legacy; 한국어 회의에서 11s+ 지연 확인됨).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from dataclasses import dataclass
from typing import AsyncIterator

logger = logging.getLogger(__name__)

_WS_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
_COMMIT_TIMEOUT_S = 10.0
_COMMIT_SIGNAL = object()  # send_queue 내 commit 트리거 센티넬


@dataclass
class Transcript:
    t_start: float
    t_end: float
    text: str
    is_final: bool


class ElevenLabsSTT:
    """ElevenLabs Realtime STT 어댑터.

    Pattern B fan-out (adr-02): feed() 는 asyncio.create_task 로 호출,
    stream() 은 별도 태스크에서 async for 로 소비.

    commit_strategy:
        "manual" (기본, PLAN-006-T-007) — server VAD (use_server_vad=True) 가
            silence 감지 시 자동 commit 트리거. close() 시 잔여 최종 commit.
            use_server_vad=False 시 외부에서 commit() 직접 호출.
        "vad" (legacy) — ElevenLabs 자동 silence 감지 → phrase auto-commit.
            close() 시 WS close 로 종료 신호 전달.
    """

    def __init__(
        self,
        api_key: str | None = None,
        language: str = "ko",
        include_timestamps: bool = True,
        commit_strategy: str = "manual",
        vad_silence_threshold_secs: float = 1.5,
        vad_threshold: float = 0.4,
        use_server_vad: bool = True,
        vad_silence_ms: int = 500,
        vad_aggressiveness: int = 2,
    ) -> None:
        resolved_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not resolved_key:
            raise ValueError(
                "ELEVENLABS_API_KEY 환경변수 또는 api_key 인자가 필요합니다."
            )
        self._api_key = resolved_key
        self._language = language
        self._include_timestamps = include_timestamps
        self._commit_strategy = commit_strategy
        self._vad_silence_threshold_secs = vad_silence_threshold_secs
        self._vad_threshold = vad_threshold
        self._send_queue: asyncio.Queue[bytes | None | object] = asyncio.Queue()

        # server VAD — manual 모드에서만 활성화
        self._server_vad = None
        if use_server_vad and commit_strategy == "manual":
            from server.stt.vad import ServerVAD
            self._server_vad = ServerVAD(
                on_silence=lambda: self._send_queue.put_nowait(_COMMIT_SIGNAL),
                aggressiveness=vad_aggressiveness,
                silence_ms=vad_silence_ms,
            )

    async def feed(self, chunk: bytes) -> None:
        """PCM16 bytes 를 내부 큐에 적재. stream() 의 sender task 가 WS 로 전송."""
        await self._send_queue.put(chunk)
        if self._server_vad is not None:
            self._server_vad.feed(chunk)

    async def commit(self) -> None:
        """명시적 commit 트리거 — server VAD 또는 외부 수동 호출 (manual 모드 전용)."""
        await self._send_queue.put(_COMMIT_SIGNAL)

    async def stream(self) -> AsyncIterator[Transcript]:
        """ElevenLabs WS 에 연결 후 Transcript 를 yield.

        close() 동작:
          vad 모드: WS close → 서버 자동 commit 완료된 메시지 flush 후 종료.
          manual 모드: commit 신호 전송 → 서버 최종 응답 수신 후 WS close → 종료.
        WS 연결 실패 또는 끊김 시 즉시 예외 발생 (fail-fast, §OQ-06-2 항목 1).
        """
        try:
            import websockets
        except ImportError as exc:
            raise ImportError(
                "websockets 패키지가 필요합니다: pip install 'speaker_engine[stt-elevenlabs]'"
            ) from exc

        url = (
            f"{_WS_URL}"
            f"?audio_format=pcm_16000"
            f"&language_code={self._language}"
            f"&commit_strategy={self._commit_strategy}"
        )
        if self._commit_strategy == "vad":
            url += (
                f"&vad_silence_threshold_secs={self._vad_silence_threshold_secs}"
                f"&vad_threshold={self._vad_threshold}"
            )
        if self._include_timestamps:
            url += "&include_timestamps=true"

        headers = {"xi-api-key": self._api_key}

        async with websockets.connect(url, additional_headers=headers) as ws:
            sender_task = asyncio.create_task(self._run_sender(ws))
            try:
                async for raw_msg in ws:
                    msg = json.loads(raw_msg)
                    for transcript in self._parse_messages(msg):
                        yield transcript
            except Exception:
                raise
            finally:
                sender_task.cancel()
                try:
                    await sender_task
                except (asyncio.CancelledError, Exception):
                    pass

    async def close(self) -> None:
        """graceful 종료 — None 센티넬을 큐에 넣어 _run_sender 가 처리하도록."""
        await self._send_queue.put(None)

    async def _run_sender(self, ws: object) -> None:
        """큐에서 청크를 꺼내 WS 로 전송.

        _COMMIT_SIGNAL: server VAD 또는 commit() 외부 호출 → commit 메시지 전송.
        None 수신 시:
          manual: commit=True 메시지 전송 후 종료 (잔여 최종 commit).
          vad: WS close() 호출 후 종료.
        """
        while True:
            chunk = await self._send_queue.get()
            if chunk is _COMMIT_SIGNAL:
                await ws.send(  # type: ignore[attr-defined]
                    json.dumps(
                        {
                            "message_type": "input_audio_chunk",
                            "audio_base_64": "",
                            "commit": True,
                            "sample_rate": 16000,
                        }
                    )
                )
                logger.debug("ElevenLabsSTT: commit 전송 (server VAD / 외부)")
                continue
            if chunk is None:
                if self._commit_strategy == "manual":
                    await ws.send(  # type: ignore[attr-defined]
                        json.dumps(
                            {
                                "message_type": "input_audio_chunk",
                                "audio_base_64": "",
                                "commit": True,
                                "sample_rate": 16000,
                            }
                        )
                    )
                    logger.debug("ElevenLabsSTT: commit 전송 (close/manual)")
                else:
                    logger.debug("ElevenLabsSTT: VAD 모드 종료 — WS close")
                    await ws.close()  # type: ignore[attr-defined]
                break
            payload = json.dumps(
                {
                    "message_type": "input_audio_chunk",
                    "audio_base_64": base64.b64encode(chunk).decode(),
                    "commit": False,
                    "sample_rate": 16000,
                }
            )
            await ws.send(payload)  # type: ignore[attr-defined]

    def _parse_messages(self, msg: dict) -> list[Transcript]:
        """ElevenLabs WS 응답 메시지를 Transcript list 로 변환.

        final (`committed_transcript_with_timestamps`) 은 `words` 배열을 단어별로
        분해 — 각 단어가 자기 t_start/t_end 를 가져 UI 측에서 SpeakerSegment
        와 시간 매핑 가능. 통째 transcript 하나만 emit 하면 긴 transcript 가
        여러 segment 를 cover 해도 한 segment 에만 매핑됨.
        """
        msg_type = msg.get("message_type")

        if msg_type == "partial_transcript":
            text = msg.get("text", "")
            if not text:
                return []
            # partial 은 timestamps 없음 → 0.0 (UI 가 우-상 자막에 사용)
            return [Transcript(t_start=0.0, t_end=0.0, text=text, is_final=False)]

        if msg_type == "committed_transcript_with_timestamps":
            words = msg.get("words") or []
            results: list[Transcript] = []
            for w in words:
                if w.get("type") != "word":
                    continue
                wtext = w.get("text", "")
                if not wtext.strip():
                    continue
                t_s = float(w.get("start", 0.0))
                t_e = float(w.get("end", t_s))
                results.append(Transcript(t_start=t_s, t_end=t_e, text=wtext, is_final=True))
            return results

        if msg_type == "committed_transcript":
            text = msg.get("text", "")
            if not text:
                return []
            return [Transcript(t_start=0.0, t_end=0.0, text=text, is_final=True)]

        if msg_type not in ("session_started", "session_ended"):
            logger.debug("ElevenLabsSTT: 무시된 메시지 type=%s", msg_type)
        return []
