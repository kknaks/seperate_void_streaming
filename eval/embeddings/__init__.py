from .protocol import EmbeddingModel
from .pyannote_emb import PyannoteEmbedding
from .ecapa_tdnn import EcapaTdnnEmbedding
from .wespeaker_emb import WeSpeakerEmbedding
from .titanet_l import TitaNetLEmbedding

__all__ = [
    "EmbeddingModel",
    "PyannoteEmbedding",
    "EcapaTdnnEmbedding",
    "WeSpeakerEmbedding",
    "TitaNetLEmbedding",
]
