import os
import time
import numpy as np
import torch


class PyannoteEmbedding:
    name = "pyannote/embedding"
    dim = 512

    def __init__(self) -> None:
        self._model = None
        self._device = "cpu"

    def load(self, device: str = "cpu") -> None:
        if self._model is not None:
            return
        token = os.environ.get("HF_TOKEN")
        if not token:
            raise RuntimeError("HF_TOKEN env var required for pyannote/embedding")
        from pyannote.audio import Model
        self._model = Model.from_pretrained("pyannote/embedding", use_auth_token=token)
        self._device = device
        self._model.eval()
        if device != "cpu":
            self._model = self._model.to(device)

    def extract(self, audio: np.ndarray, sr: int) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Call load() before extract()")
        if audio.ndim == 1:
            audio = audio[np.newaxis, :]  # (1, samples)
        # pyannote embedding expects (batch, channels, samples)
        wav = torch.from_numpy(audio.astype(np.float32)).unsqueeze(0)  # (1, ch, samples)
        with torch.no_grad():
            emb = self._model(wav)  # (1, 512)
        vec = emb.squeeze(0).numpy()
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.astype(np.float32)

    def unload(self) -> None:
        self._model = None
        torch.cuda.empty_cache() if torch.cuda.is_available() else None
