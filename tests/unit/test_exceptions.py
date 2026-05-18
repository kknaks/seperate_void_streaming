"""unit tests — speaker_engine.exceptions (F-02)."""

import pytest

from speaker_engine.exceptions import ModelLoadError, StorageError


class TestModelLoadError:
    def test_raise_and_isinstance(self):
        with pytest.raises(ModelLoadError):
            raise ModelLoadError("모델 로드 실패")

    def test_is_exception_subclass(self):
        err = ModelLoadError("test")
        assert isinstance(err, Exception)

    def test_message_preserved(self):
        err = ModelLoadError("HF hub 오류: 네트워크 단절")
        assert "HF hub 오류" in str(err)

    def test_no_args(self):
        err = ModelLoadError()
        assert isinstance(err, ModelLoadError)


class TestStorageError:
    def test_raise_and_isinstance(self):
        with pytest.raises(StorageError):
            raise StorageError("연결 실패")

    def test_is_exception_subclass(self):
        err = StorageError("test")
        assert isinstance(err, Exception)

    def test_message_preserved(self):
        err = StorageError("pgvector 연결 실패")
        assert "pgvector 연결 실패" in str(err)

    def test_distinct_from_model_load_error(self):
        err = StorageError("test")
        assert not isinstance(err, ModelLoadError)

    def test_no_args(self):
        err = StorageError()
        assert isinstance(err, StorageError)
