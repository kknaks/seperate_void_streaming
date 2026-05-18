"""speaker_engine — diart 기반 실시간 화자 분리 라이브러리.

Wave 5 완료 public re-export:
- engine:     SpeakerEngine (E-06)
- types:      SpeakerSegment / LabelChange / SpeakerCandidate / Speaker / PersistMapping (F-02)
- exceptions: ModelLoadError / StorageError / IntegrityError (F-02)
- storage:    from_url (S-05)
- sources: from_websocket / from_file / from_microphone (H-01~H-03)
           from_multichannel_mixdown / from_beamforming (H-04, Wave 6)
- multi:   MultiDeviceMerge (H-05, Wave 6)
"""

from speaker_engine.engine import SpeakerEngine
from speaker_engine.exceptions import IntegrityError, ModelLoadError, StorageError
from speaker_engine.multi.merge import MultiDeviceMerge
from speaker_engine.sources.file import from_file
from speaker_engine.sources.microphone import from_microphone
from speaker_engine.sources.multichannel import from_beamforming, from_multichannel_mixdown
from speaker_engine.sources.websocket import from_websocket
from speaker_engine.storage.url import from_url
from speaker_engine.types import (
    BeamformingConfig,
    LabelChange,
    LabelReason,
    MicrophoneGeometry,
    PersistMapping,
    Speaker,
    SpeakerCandidate,
    SpeakerSegment,
)

__version__ = "0.1.0"
__all__ = [
    "SpeakerEngine",
    "LabelReason",
    "SpeakerSegment",
    "LabelChange",
    "SpeakerCandidate",
    "Speaker",
    "PersistMapping",
    "MicrophoneGeometry",
    "BeamformingConfig",
    "ModelLoadError",
    "StorageError",
    "IntegrityError",
    "from_url",
    "from_websocket",
    "from_file",
    "from_microphone",
    "from_multichannel_mixdown",
    "from_beamforming",
    "MultiDeviceMerge",
]
