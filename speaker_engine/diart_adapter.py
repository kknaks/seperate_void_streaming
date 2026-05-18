"""DiartAdapter — diart blocks wrap + asyncio + RxPY 격리 (E-01, spec-03)."""

from __future__ import annotations

import asyncio
import logging
import warnings
from dataclasses import dataclass

import numpy as np

from speaker_engine.exceptions import ModelLoadError
from speaker_engine.speaker.online import OnlineSpeakerClusterer

logger = logging.getLogger(__name__)

WINDOW_SAMPLES: int = 16_000 * 10
SAMPLE_RATE: int = 16_000

# powerset → multilabel 매핑 (3-speaker, 7-class powerset 기준)
_POWERSET_MAPPING = np.array(
    [
        [0, 0, 0],  # 0: silence
        [1, 0, 0],  # 1: spk0
        [0, 1, 0],  # 2: spk1
        [0, 0, 1],  # 3: spk2
        [1, 1, 0],  # 4: spk0+spk1
        [1, 0, 1],  # 5: spk0+spk2
        [0, 1, 1],  # 6: spk1+spk2
    ],
    dtype=np.float32,
)

try:
    import torch as _torch
    import diart.models as _diart_models
    from diart.blocks import (
        OverlapAwareSpeakerEmbedding as _OverlapAwareSpeakerEmbedding,
        SpeakerSegmentation as _SpeakerSegmentation,
    )
    from pyannote.core import (
        SlidingWindow as _SlidingWindow,
        SlidingWindowFeature as _SlidingWindowFeature,
    )

    _DIART_OK = True
except (ImportError, AttributeError):
    _DIART_OK = False


@dataclass
class RawSpeakerEvent:
    """diart process_window 의 단일 화자 출력 (spec-03 §3)."""

    local_speaker_id: int          # 0 ~ max_speakers-1
    embedding: np.ndarray          # shape (D,), L2 normalized
    audio: bytes                   # PCM 16kHz mono 16-bit
    t_start: float                 # window 내 상대 시작 시간 (s)
    t_end: float                   # window 내 상대 종료 시간 (s)
    confidence: float              # segmentation activity probability 0~1


def _powerset_to_multilabel(scores: np.ndarray) -> np.ndarray:
    """powerset scores (num_frames, 7) → multilabel (num_frames, 3)."""
    hard = np.eye(7, dtype=np.float32)[np.argmax(scores, axis=-1)]  # (T, 7)
    return hard @ _POWERSET_MAPPING  # (T, 3)


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    if norm < 1e-9:
        return v
    return v / norm


def _waveform_to_pcm_bytes(waveform: np.ndarray) -> bytes:
    """float32 [-1,1] → 16-bit PCM bytes."""
    clipped = np.clip(waveform, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16).tobytes()


class DiartAdapter:
    """diart SpeakerSegmentation + OverlapAwareSpeakerEmbedding 래퍼.

    OnlineSpeakerClustering 은 외부에서 주입 (DI) — spec-04 §2-2.
    RxPY Subject/Observable 외부 노출 없음 (adr-01, spec-03 §5).
    """

    def __init__(
        self,
        hf_token: str,
        clusterer: OnlineSpeakerClusterer,
        segmentation_model: str = "pyannote/segmentation-3.0",
        embedding_model: str = "pyannote/embedding",
        device: str | None = None,
        max_speakers: int | None = None,  # deprecated — clusterer 에 설정하세요
    ) -> None:
        if max_speakers is not None:
            warnings.warn(
                "DiartAdapter 의 max_speakers 인자는 deprecated 입니다. "
                "OnlineSpeakerClusterer(max_speakers=...) 에 설정하세요.",
                DeprecationWarning,
                stacklevel=2,
            )

        if not _DIART_OK:
            raise ImportError("diart / pyannote.audio 를 import 할 수 없습니다.")

        import torch  # noqa: PLC0415  (lazy — _DIART_OK guard above)

        # device 결정 (spec-03 §2-1: cuda 명시 + unavailable → RuntimeError)
        if device == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("device='cuda' 지정됐으나 CUDA 를 사용할 수 없습니다.")
            self._device = torch.device("cuda")
        elif device is not None:
            self._device = torch.device(device)
        else:
            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        try:
            seg_model = _diart_models.SegmentationModel.from_pyannote(
                segmentation_model, use_hf_token=hf_token
            )
            emb_model = _diart_models.EmbeddingModel.from_pyannote(
                embedding_model, use_hf_token=hf_token
            )
        except Exception as exc:
            raise ModelLoadError(f"HF 모델 로드 실패: {exc}") from exc

        try:
            # diart 0.9.2: SpeakerSegmentation 에 duration 인자 없음 (spec-03 §2-1)
            self._segmentation = _SpeakerSegmentation(seg_model, device=self._device)
            self._embedding = _OverlapAwareSpeakerEmbedding(
                model=emb_model, device=self._device
            )
        except Exception as exc:
            raise ModelLoadError(f"diart blocks 초기화 실패: {exc}") from exc

        self._clusterer = clusterer
        self._max_speakers = clusterer._max_speakers  # delegated from clusterer
        self._closed = False
        self._embedding_dim: int | None = None

    # ------------------------------------------------------------------
    @property
    def embedding_dim(self) -> int:
        """임베딩 차원 — 런타임 결정 (reference-07: legacy 512, community 256)."""
        if self._embedding_dim is None:
            try:
                model = getattr(self._embedding, "model", None)
                if model is not None:
                    for attr in ("dimension", "embedding_dim", "output_size"):
                        val = getattr(model, attr, None)
                        if isinstance(val, int) and val > 0:
                            self._embedding_dim = val
                            break
            except Exception:  # noqa: BLE001
                pass
            if self._embedding_dim is None:
                self._embedding_dim = 256  # fallback; overridden by first process_window
        return self._embedding_dim

    # ------------------------------------------------------------------
    async def process_window(self, waveform: np.ndarray) -> list[RawSpeakerEvent]:
        """10s window → RawSpeakerEvent 목록.

        spec-03 §4-1 흐름:
          1. SpeakerSegmentation forward → multilabel SlidingWindowFeature (T, 3)
          2. multilabel 추출 (diart 0.9.2 PowersetAdapter 내부 변환)
          3. 화자별 활성 구간 추출
          4. OverlapAwareSpeakerEmbedding forward (waveform, segmentation) → (S, D)
          5. L2 normalize
          6. OnlineSpeakerClustering.identify → SpeakerMap
          7. RawSpeakerEvent 구성
        """
        if self._closed:
            raise RuntimeError("DiartAdapter 가 이미 닫혔습니다.")

        if waveform.ndim != 1 or waveform.shape[0] != WINDOW_SAMPLES:
            raise ValueError(
                f"waveform shape 은 ({WINDOW_SAMPLES},) 이어야 합니다. "
                f"받은 shape: {waveform.shape}"
            )

        try:
            return await asyncio.to_thread(self._process_window_sync, waveform)
        except Exception as exc:  # noqa: BLE001
            logger.warning("process_window 1차 실패 (retry): %s", exc)
            try:
                return await asyncio.to_thread(self._process_window_sync, waveform)
            except Exception as exc2:  # noqa: BLE001
                logger.warning("process_window 2차 실패 — chunk skip: %s", exc2)
                return []

    def _process_window_sync(self, waveform: np.ndarray) -> list[RawSpeakerEvent]:
        """동기 처리 — asyncio.to_thread 에서 실행."""
        import torch  # noqa: PLC0415

        # (160000,) → (1, 160000, 1) tensor
        wav_tensor = torch.from_numpy(waveform).float().unsqueeze(0).unsqueeze(-1)

        # ── 1. SpeakerSegmentation ──────────────────────────────────────
        seg_out = self._segmentation(wav_tensor)

        # Extract numpy multilabel from SlidingWindowFeature or raw array
        if isinstance(seg_out, np.ndarray):
            seg_data = seg_out
        elif hasattr(seg_out, "data") and isinstance(getattr(seg_out, "data", None), np.ndarray):
            seg_data = seg_out.data  # SlidingWindowFeature.data
        elif hasattr(seg_out, "numpy") and callable(seg_out.numpy):
            seg_data = seg_out.numpy()
        else:
            seg_data = np.array(seg_out)

        if seg_data.ndim == 3:
            seg_data = seg_data[0]  # (num_frames, num_classes)

        # ── 2. powerset → multilabel ────────────────────────────────────
        # diart 0.9.2 의 PowersetAdapter 가 내부에서 이미 변환하므로 num_classes=3
        num_frames, num_classes = seg_data.shape
        if num_classes == 7:
            multilabel = _powerset_to_multilabel(seg_data.astype(np.float32))
        else:
            multilabel = seg_data.astype(np.float32)

        num_local_speakers = multilabel.shape[1]

        # ── 4. OverlapAwareSpeakerEmbedding ─────────────────────────────
        emb_out = self._embedding(wav_tensor, seg_out)

        if hasattr(emb_out, "detach"):
            emb_array = emb_out.detach().cpu().numpy()
        elif isinstance(emb_out, np.ndarray):
            emb_array = emb_out
        elif hasattr(emb_out, "numpy") and callable(emb_out.numpy):
            emb_array = emb_out.numpy()
        else:
            emb_array = np.array(emb_out)

        if emb_array.ndim == 3:
            emb_array = emb_array[0]  # (num_local_speakers, D)
        emb_array = emb_array.astype(np.float32)

        # ── 5. L2 normalize ──────────────────────────────────────────────
        if emb_array.ndim == 2 and emb_array.shape[0] > 0:
            norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
            norms = np.where(norms < 1e-9, 1.0, norms)
            emb_normalized = (emb_array / norms).astype(np.float32)
        else:
            emb_normalized = emb_array

        # Cache embedding_dim from actual forward pass
        if self._embedding_dim is None and emb_normalized.ndim == 2 and emb_normalized.shape[0] > 0:
            self._embedding_dim = int(emb_normalized.shape[1])

        # ── 6. OnlineSpeakerClustering ──────────────────────────────────
        # Wrap in SlidingWindowFeature for real diart clustering (spec-03 §4-1)
        if not isinstance(seg_out, _SlidingWindowFeature):
            sw = _SlidingWindow(
                duration=10.0 / max(num_frames, 1),
                step=10.0 / max(num_frames, 1),
                start=0.0,
            )
            seg_for_clustering = _SlidingWindowFeature(multilabel, sw)
        else:
            seg_for_clustering = seg_out

        emb_tensor = torch.from_numpy(emb_normalized)
        speaker_map = self._clusterer.identify(seg_for_clustering, emb_tensor)
        local_spks, global_spks = speaker_map.valid_assignments()

        # ── 7. RawSpeakerEvent 구성 ──────────────────────────────────────
        events: list[RawSpeakerEvent] = []
        for l_spk, g_spk in zip(local_spks, global_spks):
            if l_spk >= num_local_speakers:
                continue
            activity = multilabel[:, l_spk]
            active_frames = np.where(activity > 0.5)[0]
            if len(active_frames) == 0:
                continue

            t_start = float(active_frames[0]) / num_frames * 10.0
            t_end = float(active_frames[-1] + 1) / num_frames * 10.0
            confidence = float(np.mean(activity[active_frames]))

            start_sample = int(active_frames[0] / num_frames * WINDOW_SAMPLES)
            end_sample = int((active_frames[-1] + 1) / num_frames * WINDOW_SAMPLES)
            audio_bytes = _waveform_to_pcm_bytes(waveform[start_sample:end_sample])

            if l_spk < len(emb_normalized) and emb_normalized.ndim == 2:
                embedding = _l2_normalize(emb_normalized[l_spk]).astype(np.float32)
            else:
                embedding = np.zeros(self.embedding_dim, dtype=np.float32)

            events.append(
                RawSpeakerEvent(
                    local_speaker_id=int(g_spk),
                    embedding=embedding,
                    audio=audio_bytes,
                    t_start=t_start,
                    t_end=t_end,
                    confidence=confidence,
                )
            )

        return events

    # ------------------------------------------------------------------
    async def close(self) -> None:
        """모델 참조 해제 — GPU 메모리 반환 (spec-03 §2-1)."""
        self._closed = True
        self._segmentation = None  # type: ignore[assignment]
        self._embedding = None  # type: ignore[assignment]
        self._clusterer = None  # type: ignore[assignment]


__all__ = ["DiartAdapter", "RawSpeakerEvent"]
