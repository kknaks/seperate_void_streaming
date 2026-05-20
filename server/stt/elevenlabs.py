"""ElevenLabsSTT — ElevenLabs Realtime streaming STT 어댑터 (spec-06 §1, §3).

인터페이스:
    async def feed(self, chunk: bytes) -> None
    async def stream(self) -> AsyncIterator[Transcript]
    async def close(self) -> None

WS 재연결 정책: fail-fast (§OQ-06-2 항목 1 결정).
partial/final 노출: 둘 다 emit (§OQ-06-2 항목 2 결정).
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
    """

    def __init__(
        self,
        api_key: str | None = None,
        language: str = "ko",
        include_timestamps: bool = True,
    ) -> None:
        resolved_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not resolved_key:
            raise ValueError(
                "ELEVENLABS_API_KEY 환경변수 또는 api_key 인자가 필요합니다."
            )
        self._api_key = resolved_key
        self._language = language
        self._include_timestamps = include_timestamps
        self._send_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def feed(self, chunk: bytes) -> None:
        """PCM16 bytes 를 내부 큐에 적재. stream() 의 sender task 가 WS 로 전송."""
        await self._send_queue.put(chunk)

    async def stream(self) -> AsyncIterator[Transcript]:
        """ElevenLabs WS 에 연결 후 Transcript 를 yield.

        close() 호출 → commit 시그널 전송 → 서버 응답 수신 후 WS close → 제너레이터 종료.
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
            f"&commit_strategy=manual"
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
        """graceful 종료 — None 센티넬을 큐에 넣어 sender 가 commit 전송 후 종료하도록."""
        await self._send_queue.put(None)

    async def _run_sender(self, ws: object) -> None:
        """큐에서 청크를 꺼내 WS 로 전송. None 수신 시 commit 전송 후 종료."""
        while True:
            chunk = await self._send_queue.get()
            if chunk is None:
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
                logger.debug("ElevenLabsSTT: commit 전송")
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
