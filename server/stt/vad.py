"""Server-side VAD — webrtcvad 기반 silence 감지 (PLAN-006-T-007).

webrtcvad 는 30ms 프레임 단위로 동작 (16kHz mono PCM16 기준 960 bytes).
불규칙 크기 chunk 가 들어와도 내부 buffer 로 정렬.
"""

from __future__ import annotations

from typing import Callable

_SAMPLE_RATE = 16000
_FRAME_MS = 30
_FRAME_SAMPLES = int(_SAMPLE_RATE * _FRAME_MS / 1000)  # 480 samples
_FRAME_BYTES = _FRAME_SAMPLES * 2  # 960 bytes (int16 LE × 2)


class ServerVAD:
    """webrtcvad 기반 server-side VAD.

    feed(chunk) 를 통해 16kHz mono PCM16 바이트를 받아,
    연속 silence 가 silence_ms 이상 지속되면 on_silence 를 동기 호출.

    on_silence 는 반드시 non-blocking 이어야 함 (Queue.put_nowait 등).
    """

    def __init__(
        self,
        on_silence: Callable[[], None],
        aggressiveness: int = 2,
        silence_ms: int = 500,
    ) -> None:
        try:
            import webrtcvad as _wvad
        except ImportError as exc:
            raise ImportError(
                "webrtcvad 패키지가 필요합니다: pip install webrtcvad"
            ) from exc
        self._vad = _wvad.Vad(aggressiveness)
        self._on_silence = on_silence
        # 최소 1 프레임
        self._silence_threshold = max(1, silence_ms // _FRAME_MS)
        self._buf = b""
        self._silence_count = 0
        self._has_speech = False

    def feed(self, chunk: bytes) -> None:
        """PCM16 16kHz mono bytes 를 입력; silence threshold 도달 시 on_silence 호출."""
        self._buf += chunk
        while len(self._buf) >= _FRAME_BYTES:
            frame = self._buf[:_FRAME_BYTES]
            self._buf = self._buf[_FRAME_BYTES:]
            if self._vad.is_speech(frame, _SAMPLE_RATE):
                self._silence_count = 0
                self._has_speech = True
            elif self._has_speech:
                self._silence_count += 1
                if self._silence_count >= self._silence_threshold:
                    self._silence_count = 0
                    self._has_speech = False
                    self._on_silence()
