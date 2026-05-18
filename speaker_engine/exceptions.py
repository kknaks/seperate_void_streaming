"""패키지 공개 예외 — ModelLoadError / StorageError / IntegrityError."""


class ModelLoadError(Exception):
    """pyannote 모델 다운로드·로드 실패."""


class StorageError(Exception):
    """SpeakerStore 연결·영속 실패."""


class IntegrityError(Exception):
    """UNIQUE(name, model_id) 제약 위반 — spec-02 §5."""


__all__ = ["ModelLoadError", "StorageError", "IntegrityError"]
