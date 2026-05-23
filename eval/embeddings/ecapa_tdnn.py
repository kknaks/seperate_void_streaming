import numpy as np
import torch


class EcapaTdnnEmbedding:
    name = "ecapa-tdnn"
    dim = 192

    def __init__(self) -> None:
        self._model = None
        self._device = "cpu"

    def load(self, device: str = "cpu") -> None:
        if self._model is not None:
            return
        from speechbrain.inference.classifiers import EncoderClassifier
        self._device = device
        run_opts = {"device": device}
        self._model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts=run_opts,
            savedir="~/.cache/speechbrain/spkrec-ecapa-voxceleb",
        )
        self._model.eval()

    def extract(self, audio: np.ndarray, sr: int) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Call load() before extract()")
        wav = torch.from_numpy(audio.astype(np.float32))
        if wav.ndim == 1:
            wav = wav.unsqueeze(0)  # (1, samples)
        wav_lens = torch.tensor([1.0])
        with torch.no_grad():
            emb = self._model.encode_batch(wav, wav_lens)  # (1, 1, dim)
        vec = emb.squeeze().numpy()
        if vec.ndim == 0:
            vec = vec.reshape(1)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.astype(np.float32)

    def unload(self) -> None:
        self._model = None
        torch.cuda.empty_cache() if torch.cuda.is_available() else None
