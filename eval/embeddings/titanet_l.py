import numpy as np


class TitaNetLEmbedding:
    """TitaNet-L embedding model (NeMo). Blocked on this environment: nemo_toolkit requires
    torch>=2.6.0 but this project pins torch==2.1.*. Raises ImportError on load()."""

    name = "titanet-l"
    dim = 192

    def __init__(self) -> None:
        self._model = None

    def load(self, device: str = "cpu") -> None:
        raise ImportError(
            "TitaNet-L requires nemo_toolkit which requires torch>=2.6.0. "
            "This project pins torch==2.1.*. Install nemo_toolkit in a separate env "
            "or upgrade torch to use TitaNet-L."
        )

    def extract(self, audio: np.ndarray, sr: int) -> np.ndarray:
        raise RuntimeError("TitaNet-L is blocked — see load() for details.")

    def unload(self) -> None:
        self._model = None
