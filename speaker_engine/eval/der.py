"""DER 측정 하네스 — T-024 grid sweep 의 evaluate() API (V-01, spec-05 §3).

T-024 는 이 모듈의 evaluate() 를 36회 호출해서 grid sweep 을 수행한다.
API 안정성 = 본 모듈의 핵심 deliverable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np

logger = logging.getLogger(__name__)

WINDOW_SAMPLES: int = 16_000 * 10
SAMPLE_RATE: int = 16_000


@dataclass(frozen=True)
class TuningConfig:
    """grid search 1 조합 (spec-05 §6.3 튜닝 대상 파라미터)."""

    delta_new: float               # OnlineSpeakerClusterer — 새 화자 생성 cosine threshold
    hungarian_threshold: float     # FinalReclusterer — Hungarian 매핑 거부 임계
    hdbscan_epsilon: float         # FinalReclusterer — cluster_selection_epsilon


@dataclass(frozen=True)
class DERResult:
    """evaluate() 반환 — 1 config × 1 session 의 DER 측정 결과."""

    config: TuningConfig
    der: float               # 0.0 ~ 1.0
    false_alarm: float
    miss: float
    confusion: float
    session: str             # "ES2002a"
    slice_seconds: float | None  # 사용한 slice 길이 (None = full session)
    duration_seconds: float  # 실제 처리한 audio 길이
    elapsed_seconds: float   # wall-clock 측정 시간

    def to_jsonl(self) -> str:
        """1 result → JSONL 1줄 (T-024 sweep append 용)."""
        d = asdict(self)
        # TuningConfig 가 nested dict 로 변환됨 — 그대로 직렬화
        return json.dumps(d, ensure_ascii=False)


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

@dataclass
class _UtteranceRecord:
    """utterance buffer 항목 — UtteranceEntry Protocol 충족 (spec-04 §OQ-04-6)."""

    utterance_id: str
    label: str           # "auto:A" 형식
    embedding: np.ndarray
    is_locked: bool
    t_start: float       # session-relative (seconds)
    t_end: float


def _load_audio_mono16k(wav_path: Path, slice_seconds: float | None) -> np.ndarray:
    """torchaudio 로 WAV 읽기 → 16kHz mono float32 numpy."""
    import torch
    import torchaudio

    waveform, sr = torchaudio.load(str(wav_path))

    if sr != SAMPLE_RATE:
        resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=SAMPLE_RATE)
        waveform = resampler(waveform)

    # mono 변환
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    waveform = waveform[0]  # (samples,)

    if slice_seconds is not None:
        n_samples = int(slice_seconds * SAMPLE_RATE)
        waveform = waveform[:n_samples]

    return waveform.numpy().astype(np.float32)


def _load_reference(rttm_path: Path, session: str, slice_seconds: float | None):
    """RTTM → pyannote.core.Annotation (선택적 crop)."""
    from pyannote.core import Segment
    from pyannote.database.util import load_rttm

    annotations = load_rttm(str(rttm_path))

    # RTTM uri 가 session 이름이 아닐 수도 있으므로 첫 번째 항목 사용
    if session in annotations:
        ref = annotations[session]
    elif annotations:
        ref = next(iter(annotations.values()))
    else:
        raise ValueError(f"RTTM 파일에 annotation 없음: {rttm_path}")

    if slice_seconds is not None:
        ref = ref.crop(Segment(0.0, slice_seconds))

    return ref


def _build_hypothesis(
    utterances: list[_UtteranceRecord],
    label_map: dict[str, str],
    session: str,
):
    """utterance records + label_map → pyannote.core.Annotation."""
    from pyannote.core import Annotation, Segment

    hyp = Annotation(uri=session)
    for utt in utterances:
        final_label = label_map.get(utt.utterance_id, utt.label)
        seg = Segment(utt.t_start, utt.t_end)
        if utt.t_end > utt.t_start:
            hyp[seg] = final_label
    return hyp


def _apply_final_recluster(
    utterances: list[_UtteranceRecord],
    clusterer,
    config: TuningConfig,
) -> dict[str, str]:
    """FinalReclusterer 적용 → utterance_id → final_label 매핑 반환."""
    from speaker_engine.speaker.final import FinalReclusterer
    from speaker_engine.speaker.online import OnlineSpeakerClusterer

    if not utterances:
        return {}

    auto_utts = [u for u in utterances if not u.is_locked]
    # Scale min_cluster_size so HDBSCAN produces ≤ max_letters clusters in expectation.
    # For N utterances and max_letters=20: floor(N/20) members per cluster → ≤20 clusters.
    # Minimum 2 preserves original behavior for small sessions.
    adaptive_min_cluster_size = max(2, len(auto_utts) // 20)

    finalizer = FinalReclusterer(
        min_cluster_size=adaptive_min_cluster_size,
        cluster_selection_epsilon=config.hdbscan_epsilon,
        hungarian_threshold=config.hungarian_threshold,
    )

    # active centers + labels
    centers = clusterer.centers  # (max_speakers, D) 또는 None
    active = sorted(clusterer.active_centers)

    if centers is None or not active:
        return {}

    active_centers = centers[list(active)]  # (K, D)
    center_labels = [OnlineSpeakerClusterer.idx_to_letter(i) for i in active]

    try:
        _, changes = finalizer.finalize(
            utterances=utterances,
            online_centers=active_centers,
            center_labels=center_labels,
        )
    except Exception as exc:
        logger.warning("FinalReclusterer 실패 — online labels 그대로 사용: %s", exc)
        return {}

    # 변경사항을 utterance_id → new_label 로 매핑
    label_map: dict[str, str] = {}
    for change in changes:
        for uid in change.affected_utterance_ids:
            label_map[uid] = change.new_label

    return label_map


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

async def evaluate(
    config: TuningConfig,
    session_dir: Path,
    slice_seconds: float | None = None,
    hf_token: str | None = None,
    der_collar: float = 0.25,
    der_skip_overlap: bool = True,
) -> DERResult:
    """1 session × 1 config 로 DER 측정.

    T-024 는 이 함수를 36회 호출해서 grid sweep 을 수행한다.

    Args:
        config: 튜닝 파라미터 (delta_new, hungarian_threshold, hdbscan_epsilon).
        session_dir: audio.wav + reference.rttm 가 위치한 디렉토리.
        slice_seconds: None 이면 전체 session. 양수면 [0, slice_seconds] 만 사용.
        hf_token: DiartAdapter 모델 로딩용. None 이면 HF_TOKEN 환경변수 사용.
        der_collar: DiarizationErrorRate collar (seconds). pyannote AMI 벤치마크 표준 = 0.25.
        der_skip_overlap: DiarizationErrorRate skip_overlap. pyannote AMI 벤치마크 표준 = True.

    Returns:
        DERResult — T-024 가 .to_jsonl() 로 직렬화해서 append.
    """
    import os

    from pyannote.metrics.diarization import DiarizationErrorRate

    from speaker_engine.diart_adapter import DiartAdapter
    from speaker_engine.speaker.online import OnlineSpeakerClusterer

    session = session_dir.name
    wav_path = session_dir / "audio.wav"
    rttm_path = session_dir / "reference.rttm"

    if not wav_path.exists():
        raise FileNotFoundError(f"audio.wav 없음: {wav_path}")
    if not rttm_path.exists():
        raise FileNotFoundError(f"reference.rttm 없음: {rttm_path}")

    token = hf_token or os.environ.get("HF_TOKEN", "")
    if not token:
        raise EnvironmentError("HF_TOKEN 환경변수 미설정 또는 hf_token 인자 누락")

    t0 = time.perf_counter()

    # --- 1. 오디오 + reference 로드 ---
    waveform = _load_audio_mono16k(wav_path, slice_seconds)
    reference = _load_reference(rttm_path, session, slice_seconds)
    duration_seconds = float(len(waveform)) / SAMPLE_RATE

    # --- 2. DiartAdapter 초기화 (config.delta_new → OnlineSpeakerClusterer) ---
    clusterer = OnlineSpeakerClusterer(delta_new=config.delta_new)
    adapter = DiartAdapter(hf_token=token, clusterer=clusterer)

    # --- 3. 10s window 처리 → utterance records 수집 ---
    utterances: list[_UtteranceRecord] = []
    n_windows = max(1, int(np.ceil(len(waveform) / WINDOW_SAMPLES)))

    for i in range(n_windows):
        start_sample = i * WINDOW_SAMPLES
        chunk = waveform[start_sample : start_sample + WINDOW_SAMPLES]

        # 마지막 window 가 짧으면 zero-pad
        if len(chunk) < WINDOW_SAMPLES:
            chunk = np.pad(chunk, (0, WINDOW_SAMPLES - len(chunk)), mode="constant")

        chunk = chunk.astype(np.float32)
        t_window_start = float(start_sample) / SAMPLE_RATE

        try:
            events = await adapter.process_window(chunk)
        except Exception as exc:
            logger.warning("window %d process_window 실패 — skip: %s", i, exc)
            continue

        for ev in events:
            uid = str(uuid4())
            abs_t_start = t_window_start + ev.t_start
            abs_t_end = t_window_start + ev.t_end
            # clip to actual audio duration
            abs_t_end = min(abs_t_end, duration_seconds)
            if abs_t_end <= abs_t_start:
                continue

            # global speaker id → label 변환
            label = OnlineSpeakerClusterer.idx_to_letter(
                min(ev.local_speaker_id, 19)
            )
            utterances.append(
                _UtteranceRecord(
                    utterance_id=uid,
                    label=label,
                    embedding=ev.embedding,
                    is_locked=False,
                    t_start=abs_t_start,
                    t_end=abs_t_end,
                )
            )

    await adapter.close()

    # --- 4. FinalReclusterer 적용 ---
    label_map = _apply_final_recluster(utterances, clusterer, config)

    # --- 5. hypothesis Annotation 구성 ---
    hypothesis = _build_hypothesis(utterances, label_map, session)

    # --- 6. DER 계산 (pyannote.metrics) ---
    metric = DiarizationErrorRate(collar=der_collar, skip_overlap=der_skip_overlap)
    result = metric(reference, hypothesis, detailed=True)

    elapsed = time.perf_counter() - t0

    total = float(result.get("total", 1.0)) or 1.0
    return DERResult(
        config=config,
        der=float(result["diarization error rate"]),
        false_alarm=float(result.get("false alarm", 0.0)) / total,
        miss=float(result.get("missed detection", 0.0)) / total,
        confusion=float(result.get("confusion", 0.0)) / total,
        session=session,
        slice_seconds=slice_seconds,
        duration_seconds=duration_seconds,
        elapsed_seconds=elapsed,
    )
