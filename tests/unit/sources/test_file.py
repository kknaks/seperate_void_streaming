"""unit tests — speaker_engine.sources.file (H-02, spec-05 §2-2 unit 카테고리).

외부 의존: numpy (코어 포함) + wave (표준 라이브러리) + tmp_path pytest fixture.
"""

from __future__ import annotations

import logging
import math
import wave
from pathlib import Path

import numpy as np
import pytest

from speaker_engine.sources.file import from_file


# ── helpers ───────────────────────────────────────────────────────────────────


async def _collect(gen) -> list[bytes]:
    result = []
    async for chunk in gen:
        result.append(chunk)
    return result


def _write_pcm(path: Path, samples: int = 1600) -> bytes:
    """16-bit mono PCM 파일 작성 후 data bytes 반환."""
    data = (
        (np.sin(np.linspace(0, 2 * np.pi, samples)) * 32767)
        .astype(np.int16)
        .tobytes()
    )
    path.write_bytes(data)
    return data


def _write_wav(
    path: Path,
    samples: int = 1600,
    sample_rate: int = 16000,
    nchannels: int = 1,
    sampwidth: int = 2,
) -> bytes:
    """WAV 파일 작성 후 data bytes 반환."""
    data = (
        (np.sin(np.linspace(0, 2 * np.pi, samples)) * 32767)
        .astype(np.int16)
        .tobytes()
    )
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(nchannels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(data)
    return data


# ── PCM raw ───────────────────────────────────────────────────────────────────


class TestFromFilePCM:
    async def test_yield_count_matches_ceil_div(self, tmp_path: Path):
        """PCM yield count == ceil(size / chunk_size)."""
        data = _write_pcm(tmp_path / "test.pcm", samples=1600)  # 3200 bytes
        chunks = await _collect(from_file(tmp_path / "test.pcm", chunk_size=1000))
        assert len(chunks) == math.ceil(len(data) / 1000)

    async def test_reassembled_data_equals_original(self, tmp_path: Path):
        """yield 를 이어붙이면 원본 bytes 와 일치."""
        data = _write_pcm(tmp_path / "test.pcm", samples=800)
        chunks = await _collect(from_file(tmp_path / "test.pcm", chunk_size=3200))
        assert b"".join(chunks) == data

    async def test_default_chunk_size_is_3200(self, tmp_path: Path):
        """chunk_size default = 3200 bytes."""
        _write_pcm(tmp_path / "test.pcm", samples=1600)  # 3200 bytes
        chunks = await _collect(from_file(tmp_path / "test.pcm"))
        assert len(chunks) == 1
        assert len(chunks[0]) == 3200

    async def test_chunk_size_override(self, tmp_path: Path):
        """chunk_size 인자 override — 6400 bytes / 3200 = 2 chunks."""
        _write_pcm(tmp_path / "test.pcm", samples=3200)  # 6400 bytes
        chunks = await _collect(from_file(tmp_path / "test.pcm", chunk_size=3200))
        assert len(chunks) == 2
        assert all(len(c) == 3200 for c in chunks)

    async def test_odd_byte_drops_last_byte_and_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """홀수 byte PCM → WARN 로그 + 마지막 byte drop."""
        pcm_path = tmp_path / "odd.pcm"
        pcm_path.write_bytes(b"\x01\x02\x03")  # 3 bytes (홀수)
        with caplog.at_level(logging.WARNING, logger="speaker_engine.sources.file"):
            chunks = await _collect(from_file(pcm_path, chunk_size=3200))
        assert b"".join(chunks) == b"\x01\x02"
        assert any(
            "odd" in r.message.lower() or "drop" in r.message.lower()
            for r in caplog.records
        )

    async def test_raw_extension_treated_as_pcm(self, tmp_path: Path):
        """`.raw` 확장자 → PCM raw 경로."""
        data = _write_pcm(tmp_path / "test.raw", samples=800)
        chunks = await _collect(from_file(tmp_path / "test.raw", chunk_size=3200))
        assert b"".join(chunks) == data

    async def test_other_extension_treated_as_pcm(self, tmp_path: Path):
        """`.bin` 등 기타 확장자 (RIFF 헤더 아님) → PCM raw."""
        data = _write_pcm(tmp_path / "test.bin", samples=400)
        chunks = await _collect(from_file(tmp_path / "test.bin", chunk_size=3200))
        assert b"".join(chunks) == data


# ── WAV 파일 ──────────────────────────────────────────────────────────────────


class TestFromFileWAV:
    async def test_wav_data_matches_original(self, tmp_path: Path):
        """WAV header skip 후 data 부분만 yield, 이어붙이면 원본 일치."""
        data = _write_wav(tmp_path / "test.wav", samples=1600)
        chunks = await _collect(from_file(tmp_path / "test.wav", chunk_size=3200))
        assert b"".join(chunks) == data

    async def test_wav_wrong_sample_rate_raises(self, tmp_path: Path):
        """8kHz WAV → ValueError (sample rate mismatch)."""
        _write_wav(tmp_path / "bad.wav", sample_rate=8000)
        with pytest.raises(ValueError, match="sample rate"):
            async for _ in from_file(tmp_path / "bad.wav"):
                pass

    async def test_wav_stereo_raises(self, tmp_path: Path):
        """stereo WAV → ValueError (channel mismatch)."""
        _write_wav(tmp_path / "stereo.wav", nchannels=2)
        with pytest.raises(ValueError, match="channels"):
            async for _ in from_file(tmp_path / "stereo.wav"):
                pass

    async def test_wav_32bit_raises(self, tmp_path: Path):
        """32-bit WAV → ValueError (sample width mismatch)."""
        _write_wav(tmp_path / "wide.wav", sampwidth=4)
        with pytest.raises(ValueError):
            async for _ in from_file(tmp_path / "wide.wav"):
                pass

    async def test_wav_corrupted_raises(self, tmp_path: Path):
        """corrupted WAV header → ValueError."""
        bad = tmp_path / "corrupted.wav"
        bad.write_bytes(b"NOT A VALID WAV FILE HEADER CONTENT HERE")
        with pytest.raises(ValueError):
            async for _ in from_file(bad):
                pass

    async def test_wav_chunk_size_override(self, tmp_path: Path):
        """WAV + chunk_size override — 6400 bytes / 3200 = 2 chunks."""
        _write_wav(tmp_path / "test.wav", samples=3200)  # 6400 bytes
        chunks = await _collect(from_file(tmp_path / "test.wav", chunk_size=3200))
        assert len(chunks) == 2

    async def test_wav_multiple_chunks_reassemble(self, tmp_path: Path):
        """WAV 여러 chunk 이어붙이면 원본 data와 일치."""
        data = _write_wav(tmp_path / "multi.wav", samples=4800)
        chunks = await _collect(from_file(tmp_path / "multi.wav", chunk_size=3200))
        assert len(chunks) > 1
        assert b"".join(chunks) == data


# ── RIFF header fallback ──────────────────────────────────────────────────────


class TestFromFileRIFFHeaderFallback:
    async def test_non_wav_extension_with_riff_header_parsed_as_wav(
        self, tmp_path: Path
    ):
        """`.pcm` 확장자여도 RIFF 시작이면 WAV 파싱 경로 진입."""
        data = _write_wav(tmp_path / "weird.pcm", samples=800)
        chunks = await _collect(from_file(tmp_path / "weird.pcm", chunk_size=3200))
        assert b"".join(chunks) == data

    async def test_no_riff_header_non_wav_stays_pcm(self, tmp_path: Path):
        """RIFF 헤더 없는 non-`.wav` 파일 → PCM raw 경로."""
        data = _write_pcm(tmp_path / "no_riff.pcm", samples=800)
        chunks = await _collect(from_file(tmp_path / "no_riff.pcm", chunk_size=3200))
        assert b"".join(chunks) == data


# ── 에지 케이스 ───────────────────────────────────────────────────────────────


class TestFromFileEdgeCases:
    async def test_empty_pcm_file_yields_nothing(self, tmp_path: Path):
        """빈 PCM 파일 → 빈 generator (예외 없음)."""
        empty = tmp_path / "empty.pcm"
        empty.write_bytes(b"")
        chunks = await _collect(from_file(empty))
        assert chunks == []

    async def test_empty_wav_file_yields_nothing(self, tmp_path: Path):
        """빈 `.wav` 파일 → 빈 generator (예외 없음)."""
        empty = tmp_path / "empty.wav"
        empty.write_bytes(b"")
        chunks = await _collect(from_file(empty))
        assert chunks == []

    async def test_file_not_found_raises(self, tmp_path: Path):
        """존재하지 않는 파일 → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            async for _ in from_file(tmp_path / "nonexistent.pcm"):
                pass

    async def test_path_object_accepted(self, tmp_path: Path):
        """`Path` 객체 입력 동작."""
        data = _write_pcm(tmp_path / "p.pcm", samples=800)
        chunks = await _collect(from_file(Path(tmp_path / "p.pcm")))
        assert b"".join(chunks) == data

    async def test_str_path_accepted(self, tmp_path: Path):
        """`str` 경로 입력 동작."""
        data = _write_pcm(tmp_path / "s.pcm", samples=800)
        chunks = await _collect(from_file(str(tmp_path / "s.pcm")))
        assert b"".join(chunks) == data

    async def test_last_chunk_smaller_than_chunk_size(self, tmp_path: Path):
        """마지막 chunk 크기가 chunk_size 미만일 수 있음."""
        _write_pcm(tmp_path / "partial.pcm", samples=1700)  # 3400 bytes
        chunks = await _collect(from_file(tmp_path / "partial.pcm", chunk_size=3200))
        assert len(chunks) == 2
        assert len(chunks[0]) == 3200
        assert len(chunks[1]) == 200  # 3400 - 3200


# ── import 검증 ───────────────────────────────────────────────────────────────


class TestFromFileImport:
    def test_module_importable(self):
        """speaker_engine.sources.file 는 외부 의존 0 으로 import 가능."""
        import speaker_engine.sources.file as file_mod

        assert hasattr(file_mod, "from_file")
        assert callable(file_mod.from_file)

    def test_sources_package_exports_from_file(self):
        """sources 패키지에서 from_file re-export 확인."""
        from speaker_engine.sources import from_file as ff

        assert callable(ff)

    def test_top_level_import(self):
        """speaker_engine 최상위에서 from_file re-export 확인."""
        from speaker_engine import from_file as ff

        assert callable(ff)
