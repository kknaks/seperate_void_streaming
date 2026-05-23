from typing import Protocol, runtime_checkable
import numpy as np


@runtime_checkable
class EmbeddingModel(Protocol):
    name: str
    dim: int

    def load(self, device: str = "cpu") -> None:
        """Cold-load model weights to device."""
        ...

    def extract(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """audio (samples,) or (channels, samples) → L2-normalized (dim,) float32."""
        ...

    def unload(self) -> None:
        """Release model from memory."""
        ...
