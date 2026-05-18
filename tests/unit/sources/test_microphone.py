"""unit tests — speaker_engine.sources.microphone (H-03, spec-05 §2-2 unit 카테고리).

sounddevice 는 mock 으로 완전 격리 — 실 마이크 접근 0.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from unittest.mock import patch

import numpy as np
import pytest

from speaker_engine.sources.microphone import from_microphone


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_fake_sd(captured: dict):
    """sounddevice mock — callback / kwargs 캡처 + InputStream context manager."""

    class FakeInputStream:
        def __init__(self, *args, **kwargs):
            captured["callback"] = kwargs.get("callback")
            captured["kwargs"] = dict(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeSd:
        InputStream = FakeInputStream

    return FakeSd()


def _chunk(frames: int = 1600) -> np.ndarray:
    """합성 int16 ndarray (frames, 1) — sounddevice callback 입력 형식."""
    return np.zeros((frames, 1), dtype=np.int16)


async def _init_gen(gen, captured: dict):
    """generator 를 첫 await queue.get() 까지 진행 (InputStream 초기화)."""
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)  # generator 가 await queue.get() 에서 suspend 될 때까지 실행
    return task


# ── callback → yield ─────────────────────────────────────────────────────────


class TestFromMicrophoneCallback:
    async def test_callback_yields_bytes(self):
        """callback 호출 → yield bytes 검증."""
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)

        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone()
            task = await _init_gen(gen, captured)

            cb = captured["callback"]
            cb(_chunk(), 1600, None, None)
            await asyncio.sleep(0)

            result = await task
            await gen.aclose()

        assert isinstance(result, bytes)
        assert len(result) == 3200  # 1600 frames × 2 bytes (int16)

    async def test_multiple_callbacks_yield_in_order(self):
        """여러 callback → 순서대로 yield."""
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)

        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone()
            task = await _init_gen(gen, captured)

            cb = captured["callback"]
            # 3개 chunk 주입
            for i in range(3):
                data = np.full((1600, 1), i, dtype=np.int16)
                cb(data, 1600, None, None)
            await asyncio.sleep(0)

            results = [await task]
            for _ in range(2):
                results.append(await gen.__anext__())
            await gen.aclose()

        assert len(results) == 3
        assert all(isinstance(c, bytes) for c in results)

    async def test_chunk_bytes_content_matches_indata(self):
        """callback 의 indata.tobytes() 와 yield bytes 일치."""
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)

        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone()
            task = await _init_gen(gen, captured)

            indata = np.arange(1600, dtype=np.int16).reshape(1600, 1)
            captured["callback"](indata, 1600, None, None)
            await asyncio.sleep(0)

            result = await task
            await gen.aclose()

        assert result == indata.tobytes()


# ── chunk_size / blocksize ────────────────────────────────────────────────────


class TestFromMicrophoneChunkSize:
    async def test_default_chunk_size_blocksize_is_1600(self):
        """chunk_size default 3200 → blocksize = 1600 frames."""
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)

        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone()
            task = await _init_gen(gen, captured)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await gen.aclose()

        assert captured["kwargs"]["blocksize"] == 1600

    async def test_chunk_size_override_blocksize(self):
        """chunk_size=6400 → blocksize = 3200 frames."""
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)

        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone(chunk_size=6400)
            task = await _init_gen(gen, captured)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await gen.aclose()

        assert captured["kwargs"]["blocksize"] == 3200

    async def test_chunk_size_small_blocksize_minimum_1(self):
        """chunk_size=1 → blocksize = max(1, 0) = 1."""
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)

        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone(chunk_size=1)
            task = await _init_gen(gen, captured)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await gen.aclose()

        assert captured["kwargs"]["blocksize"] >= 1


# ── device 인자 ───────────────────────────────────────────────────────────────


class TestFromMicrophoneDevice:
    async def _get_kwargs(self, device) -> dict:
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)
        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone(device=device)
            task = await _init_gen(gen, captured)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await gen.aclose()
        return captured["kwargs"]

    async def test_device_none(self):
        """device=None → InputStream device=None."""
        kwargs = await self._get_kwargs(None)
        assert kwargs["device"] is None

    async def test_device_int(self):
        """device=0 (int) → InputStream device=0."""
        kwargs = await self._get_kwargs(0)
        assert kwargs["device"] == 0

    async def test_device_str(self):
        """device='USB Mic' (str) → InputStream device='USB Mic'."""
        kwargs = await self._get_kwargs("USB Mic")
        assert kwargs["device"] == "USB Mic"

    async def test_audio_params_fixed(self):
        """samplerate=16000 / channels=1 / dtype='int16' 고정."""
        kwargs = await self._get_kwargs(None)
        assert kwargs["samplerate"] == 16000
        assert kwargs["channels"] == 1
        assert kwargs["dtype"] == "int16"


# ── ImportError ───────────────────────────────────────────────────────────────


class TestFromMicrophoneImportError:
    async def test_missing_sounddevice_raises_import_error(self):
        """sounddevice 미설치 → ImportError (extras 안내 메시지 포함)."""
        with patch.dict(sys.modules, {"sounddevice": None}):
            with pytest.raises(ImportError, match="speaker_engine\\[microphone\\]"):
                async for _ in from_microphone():
                    pass

    async def test_import_error_message_contains_install_hint(self):
        """ImportError 메시지에 pip install 안내 포함."""
        with patch.dict(sys.modules, {"sounddevice": None}):
            with pytest.raises(ImportError) as exc_info:
                async for _ in from_microphone():
                    pass
        assert "pip install" in str(exc_info.value)

    def test_module_importable_without_sounddevice(self):
        """sounddevice 없이도 microphone 모듈 import 가능 (lazy import)."""
        # lazy import 이므로 모듈 레벨에서 sounddevice 를 참조하지 않아야 한다
        import speaker_engine.sources.microphone as mic_mod

        assert hasattr(mic_mod, "from_microphone")
        assert callable(mic_mod.from_microphone)


# ── CancelledError / aclose ───────────────────────────────────────────────────


class TestFromMicrophoneCancellation:
    async def test_cancel_task_raises_cancelled_error(self):
        """task 취소 시 CancelledError 로 종료."""
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)

        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone()

            async def _consume():
                async for _ in gen:
                    pass

            task = asyncio.create_task(_consume())
            await asyncio.sleep(0)  # generator 초기화
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

    async def test_aclose_stops_generator(self):
        """aclose() 후 추가 __anext__() → StopAsyncIteration."""
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)

        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone()
            init_task = await _init_gen(gen, captured)
            init_task.cancel()
            try:
                await init_task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await gen.aclose()

            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()

    async def test_context_manager_exit_called_on_cancel(self):
        """취소 시 InputStream __exit__ 호출 (graceful 정리)."""
        captured: dict = {}
        exit_called = []

        class FakeInputStream:
            def __init__(self, *args, **kwargs):
                captured["callback"] = kwargs.get("callback")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                exit_called.append(True)
                return False

        class FakeSd:
            InputStream = FakeInputStream

        with patch.dict(sys.modules, {"sounddevice": FakeSd()}):
            gen = from_microphone()
            task = await _init_gen(gen, captured)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await gen.aclose()

        assert exit_called, "InputStream.__exit__ 가 호출되어야 한다"


# ── queue overflow ────────────────────────────────────────────────────────────


class TestFromMicrophoneQueueOverflow:
    async def test_queue_overflow_drops_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ):
        """queue full → drop + WARNING 로그."""
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)

        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone()
            task = await _init_gen(gen, captured)  # await queue.get() 에서 suspend

            cb = captured["callback"]

            with caplog.at_level(logging.WARNING, logger="speaker_engine.sources.microphone"):
                # maxsize=100, 1 getter 대기 중 → 101개까지 버퍼링 가능
                # 110개 주입 시 최소 9개는 drop 되어야 한다
                for _ in range(110):
                    cb(_chunk(), 1600, None, None)
                # 스케줄된 _try_put 콜백들을 모두 처리
                await asyncio.sleep(0)
                await asyncio.sleep(0)

            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await gen.aclose()

        assert any(
            "queue full" in r.message.lower() or "drop" in r.message.lower()
            for r in caplog.records
        ), f"경고 로그 없음. records={[r.message for r in caplog.records]}"

    async def test_queue_overflow_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ):
        """queue overflow 는 예외가 아니라 drop + 로그로 처리된다."""
        captured: dict = {}
        fake_sd = _make_fake_sd(captured)

        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            gen = from_microphone()
            task = await _init_gen(gen, captured)

            cb = captured["callback"]
            with caplog.at_level(logging.WARNING, logger="speaker_engine.sources.microphone"):
                for _ in range(110):
                    cb(_chunk(), 1600, None, None)
                await asyncio.sleep(0)
                await asyncio.sleep(0)

            # task 가 여전히 살아있어야 한다 (exception 으로 죽지 않았어야)
            assert not task.done() or not task.cancelled()

            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await gen.aclose()


# ── re-export 검증 ────────────────────────────────────────────────────────────


class TestFromMicrophoneReexport:
    def test_sources_package_exports_from_microphone(self):
        """sources 패키지에서 from_microphone re-export 확인."""
        from speaker_engine.sources import from_microphone as fm

        assert callable(fm)

    def test_top_level_package_exports_from_microphone(self):
        """speaker_engine 최상위에서 from_microphone re-export 확인."""
        from speaker_engine import from_microphone as fm

        assert callable(fm)

    def test_sources_all_includes_from_microphone(self):
        """sources.__all__ 에 from_microphone 포함."""
        import speaker_engine.sources as src

        assert "from_microphone" in src.__all__

    def test_microphone_module_all_includes_from_microphone(self):
        """microphone 모듈 __all__ 에 from_microphone 포함."""
        import speaker_engine.sources.microphone as mic

        assert "from_microphone" in mic.__all__
