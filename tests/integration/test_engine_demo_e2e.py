"""통합 테스트 — SpeakerEngine 통합 path e2e (PLAN-004-T-001, spec-05 §2-2).

Bug A/B/C fix 검증:
  A — embedding_dim=512 으로 storage 가 잠히는지 (dim mismatch 없음)
  B — t_start ∈ [0, audio_duration] session-relative
  C — finalize() 에러 없음, candidates ≥ 1

requires HF_TOKEN 및 테스트 오디오 파일.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import numpy as np
import pytest

AUDIO_CANDIDATES = [
    Path("/tmp/ami_es2002a_2min.wav"),
    Path("tests/data/ami/ES2002a/audio.wav"),
]
HF_TOKEN = os.environ.get("HF_TOKEN", "")


def _find_audio() -> Path | None:
    for p in AUDIO_CANDIDATES:
        if p.exists():
            return p
    return None


def _wav_to_pcm16_bytes(wav_path: Path) -> bytes:
    """WAV 파일에서 PCM 16kHz mono 16-bit bytes 추출."""
    import wave

    with wave.open(str(wav_path), "rb") as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    # float32 변환 후 resample if needed
    if sampwidth == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2**31
    else:
        raise ValueError(f"지원하지 않는 sample width: {sampwidth}")

    if nchannels > 1:
        samples = samples.reshape(-1, nchannels).mean(axis=1)

    # resample to 16kHz if needed (simple decimation for tests)
    if framerate != 16000:
        ratio = framerate / 16000
        indices = (np.arange(int(len(samples) / ratio)) * ratio).astype(int)
        indices = np.clip(indices, 0, len(samples) - 1)
        samples = samples[indices]

    return (samples * 32767).astype(np.int16).tobytes()


@pytest.mark.integration
class TestSpeakerEngineE2E:
    """SpeakerEngine 통합 path e2e — Bug A/B/C fix 검증."""

    @pytest.fixture(autouse=True)
    def _skip_without_deps(self):
        if not HF_TOKEN:
            pytest.skip("HF_TOKEN 없음 — integration test skip")
        audio_path = _find_audio()
        if audio_path is None:
            pytest.skip(
                f"오디오 파일 없음 — 후보: {[str(p) for p in AUDIO_CANDIDATES]}"
            )
        self._audio_path = audio_path

    async def test_engine_e2e_no_errors(self):
        """SpeakerEngine 통합 path — Bug A/B/C fix 확인."""
        from speaker_engine.engine import SpeakerEngine
        from speaker_engine.types import LabelChange, SpeakerSegment

        pcm_bytes = _wav_to_pcm16_bytes(self._audio_path)

        # chunk 크기: 100ms @ 16kHz 16-bit = 3200 bytes
        CHUNK_SIZE = 3200

        async def audio_source():
            offset = 0
            while offset < len(pcm_bytes):
                yield pcm_bytes[offset : offset + CHUNK_SIZE]
                offset += CHUNK_SIZE

        segments: list[SpeakerSegment] = []
        t_starts: list[float] = []

        async with SpeakerEngine(
            storage_url="memory://",
            hf_token=HF_TOKEN,
        ) as engine:
            async for event in engine.stream(audio_source()):
                if isinstance(event, SpeakerSegment):
                    segments.append(event)
                    t_starts.append(event.t_start)

            candidates = await engine.finalize()

        # Bug B: t_start session-relative (≤ audio duration ~120s + buffer)
        audio_duration = len(pcm_bytes) / (2 * 16000)  # bytes / (bytes_per_sample * sample_rate)
        assert len(t_starts) > 0, "발화 이벤트가 하나도 없음"
        assert min(t_starts) >= 0.0, f"음수 t_start: {min(t_starts)}"
        assert max(t_starts) <= audio_duration + 10.0, (
            f"t_start 가 너무 큼 (session-relative 위반): max={max(t_starts):.1f}s, "
            f"audio_duration={audio_duration:.1f}s"
        )

        # Bug C: finalize() 에러 없음, candidates ≥ 1
        assert candidates is not None
        assert len(candidates) >= 1, "finalize() 결과 candidates 가 비어있음"

        # Bug A: storage 의 embedding_dim 이 실 모델 값으로 잠겼는지 — dim mismatch 없이 여기까지 도달했으면 통과
        # (dim mismatch 발생 시 stream() 도중 StorageError 또는 ValueError 로 조기 종료됨)
        if len(segments) > 0:
            actual_dim = segments[0].embedding.shape[0]
            assert actual_dim > 0, "embedding dim=0"
            assert actual_dim == engine._diart._embedding_dim, (
                f"embedding dim 불일치: segment={actual_dim}, "
                f"diart={engine._diart._embedding_dim}"
            )
