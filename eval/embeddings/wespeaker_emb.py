import numpy as np
import torch


class WeSpeakerEmbedding:
    name = "wespeaker-resnet221"
    dim = 256

    def __init__(self) -> None:
        self._model = None
        self._device = "cpu"

    def load(self, device: str = "cpu") -> None:
        if self._model is not None:
            return
        import wespeaker
        self._device = device
        self._model = wespeaker.load_model("english")
        self._model.set_device("cpu")

    def extract(self, audio: np.ndarray, sr: int) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Call load() before extract()")
        wav = torch.from_numpy(audio.astype(np.float32))
        if wav.ndim == 1:
            wav = wav.unsqueeze(0)  # (channels, samples) required
        emb = self._model.extract_embedding_from_pcm(wav, sr)
        if isinstance(emb, torch.Tensor):
            vec = emb.squeeze().numpy()
        else:
            vec = np.array(emb).flatten()
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.astype(np.float32)

    def unload(self) -> None:
        self._model = None
        torch.cuda.empty_cache() if torch.cuda.is_available() else None
