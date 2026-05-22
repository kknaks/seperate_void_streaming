---
id: reference-05
type: reference
title: pyannote SpeakerDiarization Pipeline — 코드 흐름
status: draft
created: 2026-05-14
updated: 2026-05-14
source_url: https://github.com/pyannote/pyannote-audio/blob/main/src/pyannote/audio/pipelines/speaker_diarization.py
fetched_at: 2026-05-14
sources:
  - "[[reference-01-pyannote-segmentation-3]]"
  - "[[reference-02-pyannote-embedding]]"
  - "[[reference-03-pyannote-audio-overview]]"
  - "[[reference-04-pyannote-audio-inference]]"
  - "[[reference-06-powerset-decoder]]"
  - "[[reference-07-pyannote-embedding-code]]"
tags: [reference, pyannote, pipeline, diarization, clustering, study-step-2, source-code]
---

# pyannote SpeakerDiarization Pipeline — 코드 흐름

> **출처**: `pyannote-audio/src/pyannote/audio/pipelines/speaker_diarization.py` (총 787 줄, class `SpeakerDiarization`)
> **목적**: 학습 2단계 — segmentation→embedding→clustering 단계와 데이터 흐름 확정

## Summary

`SpeakerDiarization.apply()` 가 batch (= 파일 전체) diarization 의 진입점. 흐름은:
**segmentation → (binarize) → embedding (mask 가중) → clustering (VBxClustering default) → reconstruct → Annotation 생성**.
streaming X. community-1 / precision-2 의 default 가 이 파이프라인.

---

## 1. 생성자 (speaker_diarization.py:193-279)

community-1 의 default checkpoint configuration:

```python
def __init__(
    self,
    legacy: bool = False,
    segmentation: PipelineModel = {
        "checkpoint": "pyannote/speaker-diarization-community-1",
        "subfolder": "segmentation",
    },
    segmentation_step: float = 0.1,    # = 90% overlap
    embedding: PipelineModel = {
        "checkpoint": "pyannote/speaker-diarization-community-1",
        "subfolder": "embedding",
    },
    embedding_exclude_overlap: bool = False,
    plda: PipelinePLDA = {
        "checkpoint": "pyannote/speaker-diarization-community-1",
        "subfolder": "plda",
    },
    clustering: str = "VBxClustering",
    embedding_batch_size: int = 1,
    segmentation_batch_size: int = 1,
    ...
):
```

**핵심 default 값**:
- `segmentation_step = 0.1` (duration 의 10% — 즉 90% overlap)
- `clustering = "VBxClustering"` — VBx (Variational Bayes with HMM) clustering (PLDA scoring 기반)
- `embedding_batch_size = 1`, `segmentation_batch_size = 1`
- `embedding_exclude_overlap = False` (overlap frame 도 embedding 에 사용, 단 weight 자연 감소)

`Inference` 래핑 (line 237-244):
```python
segmentation_duration = model.specifications.duration  # ← 10초 (segmentation-3.0)
self._segmentation = Inference(
    model,
    duration=segmentation_duration,
    step=self.segmentation_step * segmentation_duration,  # = 1.0초 hop
    skip_aggregation=True,   # ← chunk 별 raw 출력 유지
    batch_size=segmentation_batch_size,
)
```

→ pipeline 은 **`skip_aggregation=True`** 로 segmentation 호출. chunk 별 `(num_chunks, num_frames, num_speakers)` raw segmentation 을 그대로 보관 (clustering 후 reconstruct 단계에서 재가공).

### Default hyperparameters (speaker_diarization.py:289-293)

```python
def default_parameters(self):
    return {
        "segmentation": {"min_duration_off": 0.0},
        "clustering": {"threshold": 0.6, "Fa": 0.07, "Fb": 0.8},
    }
```

- `min_duration_off = 0.0` — 화자 turn 사이 silence 최소 길이 (turn merge 조건)
- `clustering.threshold = 0.6` — VBx 의 PLDA score threshold (값이 클수록 더 자유롭게 분리)
- `Fa = 0.07`, `Fb = 0.8` — VBx forward/backward smoothing 파라미터 (이 plan 범위 밖)

### Powerset 분기 (line 246-255)

```python
if self._segmentation.model.specifications.powerset:
    self.segmentation = ParamDict(
        min_duration_off=Uniform(0.0, 1.0),
    )
else:
    self.segmentation = ParamDict(
        threshold=Uniform(0.1, 0.9),
        min_duration_off=Uniform(0.0, 1.0),
    )
```

→ **segmentation-3.0 은 powerset 이라 `threshold` 가 없음** (argmax 가 hard binary 결정). legacy non-powerset 모델만 threshold 튜닝.

## 2. apply() — 메인 흐름 (speaker_diarization.py:530-784)

전체 흐름을 7 단계로 분해:

```
┌─────────────────────────────────────────────────────────────┐
│ ① get_segmentations(file)                                   │
│    Inference (skip_aggregation=True)                        │
│    → SlidingWindowFeature                                   │
│      shape: (num_chunks, num_frames, num_speakers=3)        │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ ② Binarize                                                  │
│    if powerset: 그대로 (이미 0/1)                           │
│    else: binarize(threshold, initial_state=False)           │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ speaker_count(binarized, receptive_field, warm_up=(0,0))  │
│    frame 별 동시 발화 화자 수                                │
│    → (num_frames, 1) int                                    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ ④ get_embeddings(file, binarized, exclude_overlap=...)      │
│    각 (chunk, speaker) 별 mask 로 weight 가중                │
│    embedding model forward → mask 가중 stats pool           │
│    → (num_chunks, num_speakers, dimension)                  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ ⑤ clustering(embeddings, segmentations, num_clusters, ...)  │
│    VBxClustering / AgglomerativeClustering 등               │
│    → hard_clusters: (num_chunks, num_speakers)              │
│    → centroids: (num_global_speakers, dimension)            │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ ⑥ reconstruct(segmentations, hard_clusters, count)          │
│    local speaker → global speaker 매핑                       │
│    → discrete_diarization (SlidingWindowFeature)            │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ ⑦ to_annotation → speaker_diarization (pyannote.core)       │
│    + exclusive_speaker_diarization (count 캡 1)             │
│    + speaker_embeddings (centroids)                          │
│    → DiarizeOutput                                          │
└─────────────────────────────────────────────────────────────┘
```

## 3. 단계별 상세

### ① get_segmentations (speaker_diarization.py:305-330)

```python
def get_segmentations(self, file, hook=None) -> SlidingWindowFeature:
    """
    Returns
    -------
    segmentations : (num_chunks, num_frames, num_speakers) SlidingWindowFeature
    """
    if self.training:
        if self.CACHED_SEGMENTATION in file:
            segmentations = file[self.CACHED_SEGMENTATION]
        else:
            segmentations = self._segmentation(file, hook=hook)
            file[self.CACHED_SEGMENTATION] = segmentations
    else:
        segmentations: SlidingWindowFeature = self._segmentation(file, hook=hook)
    return segmentations
```

→ training 모드는 cache. inference 는 매번 새로 계산. `Inference.__call__` 호출 결과.

### ② Binarize (speaker_diarization.py:598-606)

```python
if self._segmentation.model.specifications.powerset:
    binarized_segmentations = segmentations
else:
    binarized_segmentations: SlidingWindowFeature = binarize(
        segmentations,
        onset=self.segmentation.threshold,
        initial_state=False,
    )
```

→ powerset 모델은 이미 argmax 통과 후 multilabel `(0/1)` 이라 그대로. 비-powerset 만 threshold binarize.

### ③ speaker_count (SpeakerDiarizationMixin.speaker_count, speaker_diarization.py:608-614)

```python
count = self.speaker_count(
    binarized_segmentations,
    self._segmentation.model.receptive_field,
    warm_up=(0.0, 0.0),
)
# count.shape = (num_frames, 1), int
```

→ frame 별 "몇 명이 동시에 말하는지" 추정. exclusive diarization (overlap 제거 버전) 생성에 사용.

### ④ get_embeddings (speaker_diarization.py:332-478)

핵심 발췌:

```python
duration = binary_segmentations.sliding_window.duration  # = 10초
num_chunks, num_frames, num_speakers = binary_segmentations.data.shape

if exclude_overlap:
    min_num_samples = self._embedding.min_num_samples
    num_samples = duration * self._embedding.sample_rate
    min_num_frames = math.ceil(num_frames * min_num_samples / num_samples)
    clean_frames = 1.0 * (
        np.sum(binary_segmentations.data, axis=2, keepdims=True) < 2
    )
    clean_segmentations = SlidingWindowFeature(
        binary_segmentations.data * clean_frames,
        binary_segmentations.sliding_window,
    )
else:
    min_num_frames = -1
    clean_segmentations = SlidingWindowFeature(
        binary_segmentations.data, binary_segmentations.sliding_window
    )

def iter_waveform_and_mask():
    for (chunk, masks), (_, clean_masks) in zip(binary_segmentations, clean_segmentations):
        waveform, _ = self._audio.crop(file, chunk, mode="pad")
        masks = np.nan_to_num(masks, nan=0.0).astype(np.float32)
        clean_masks = np.nan_to_num(clean_masks, nan=0.0).astype(np.float32)
        for mask, clean_mask in zip(masks.T, clean_masks.T):
            if np.sum(clean_mask) > min_num_frames:
                used_mask = clean_mask
            else:
                used_mask = mask
            yield waveform[None], torch.from_numpy(used_mask)[None]
```

핵심 logic:
- chunk 별로 audio crop (10초)
- chunk 안의 각 local speaker (총 3) 별로 mask 추출
- `exclude_overlap=True` 면 overlap frame 제거한 clean_mask 우선, 너무 짧으면 일반 mask fallback
- `embedding(waveform, masks=mask)` 호출 → mask 가중 stats pool 으로 frame 가중 평균 embedding 계산

결과 shape: **`(num_chunks, num_speakers=3, dimension)`** (line 463). 단 inactive speaker 의 row 는 의미 없음 (mask=0).

### ⑤ Clustering 분기

`Clustering` enum 의 값들 (speaker_diarization.py:268-277):
```python
try:
    Klustering = Clustering[clustering]
except KeyError:
    raise ValueError(...)

if self.klustering == "VBxClustering":
    self.clustering = Klustering.value(self._plda, metric=metric)
else:
    self.clustering = Klustering.value(metric=metric)
```

→ `clustering.py` 에 등록된 enum. community-1 default = **`VBxClustering`** (PLDA 기반). 다른 옵션 `AgglomerativeClustering`, `OracleClustering` 등.

호출 (speaker_diarization.py:640-648):
```python
hard_clusters, _, centroids = self.clustering(
    embeddings=embeddings,
    segmentations=binarized_segmentations,
    num_clusters=num_speakers,
    min_clusters=min_speakers,
    max_clusters=max_speakers,
    file=file,
    frames=self._segmentation.model.receptive_field,
)
# hard_clusters: (num_chunks, num_speakers)
# centroids: (num_speakers, dimension)
```

→ 입력: 모든 chunk 의 모든 local speaker 의 embedding + binary segmentation.
→ 출력: 각 (chunk, local speaker) → global speaker index 매핑 + global speaker 별 centroid.

### ⑥ reconstruct (speaker_diarization.py:480-528)

```python
def reconstruct(self, segmentations, hard_clusters, count) -> SlidingWindowFeature:
    num_chunks, num_frames, local_num_speakers = segmentations.data.shape
    num_clusters = np.max(hard_clusters) + 1
    clustered_segmentations = np.nan * np.zeros((num_chunks, num_frames, num_clusters))

    for c, (cluster, (chunk, segmentation)) in enumerate(zip(hard_clusters, segmentations)):
        for k in np.unique(cluster):
            if k == -2:
                continue
            # max over local speakers that map to same global k
            clustered_segmentations[c, :, k] = np.max(
                segmentation[:, cluster == k], axis=1
            )

    clustered_segmentations = SlidingWindowFeature(...)
    return self.to_diarization(clustered_segmentations, count)
```

→ chunk 별 segmentation 을 cluster label 로 permute → `to_diarization` (Mixin) 이 chunk 간 timeline 통합. `-2` 는 inactive speaker (line 681-685 에서 force-assign).

### ⑦ to_annotation → DiarizeOutput

`SpeakerDiarizationMixin.to_annotation` 이 `SlidingWindowFeature(discrete 0/1)` → `pyannote.core.Annotation(start, end, speaker)` 변환. final output:

```python
@dataclass
class DiarizeOutput:
    speaker_diarization: Annotation
    exclusive_speaker_diarization: Annotation
    speaker_embeddings: np.ndarray | None = None
```

(speaker_diarization.py:63-76). `exclusive_speaker_diarization` 은 overlap 영역 제거 버전 (count 를 1 로 캡, line 702).

`speaker_embeddings` = `(num_speakers, dimension)` array — centroid 가 화자 라벨 순서대로 정렬됨 (line 770-773).

## 4. SlidingWindowFeature — 데이터 컨테이너

pyannote.core 의 핵심 컨테이너. 단계 간 데이터 형식 정리:

| 단계 | data shape | sliding_window |
|---|---|---|
| ① segmentation 출력 | `(num_chunks, num_frames, 3)` | `SlidingWindow(start=0, duration=10, step=1)` |
| ② binarized | 동일 | 동일 |
| ③ count | `(total_num_frames, 1)` | receptive_field |
| ④ embeddings | `(num_chunks, 3, D)` numpy | (없음, raw array) |
| ⑥ reconstruct | `(num_chunks, num_frames, num_global_speakers)` | 동일 |
| ⑦ Annotation | pyannote.core.Annotation (start/end/label 리스트) | - |

## 5. Hyperparameter 기본값 정리

| 파라미터 | default | 위치 | 의미 |
|---|---|---|---|
| `segmentation_step` | 0.1 | 생성자 line 200 | chunk hop = step × duration |
| `embedding_exclude_overlap` | False | 생성자 line 205 | True 면 overlap frame 제거 |
| `clustering` | "VBxClustering" | 생성자 line 210 | PLDA 기반 |
| `embedding_batch_size` | 1 | 생성자 line 211 | embedding mini-batch |
| `segmentation_batch_size` | 1 | 생성자 line 212 | segmentation mini-batch |
| `segmentation.min_duration_off` | 0.0 | default_parameters line 291 | turn merge silence threshold |
| `clustering.threshold` | 0.6 | default_parameters line 292 | VBx threshold |
| `clustering.Fa` | 0.07 | default_parameters line 292 | VBx forward smoothing |
| `clustering.Fb` | 0.8 | default_parameters line 292 | VBx backward smoothing |

---

## 우리 라이브러리 영향 (실제 사실)

| 1단계 가정 | 코드 확정 | 행동 |
|---|---|---|
| Pipeline = segmentation + embedding + clustering | ✅ 정확 (apply() 7단계) | 우리도 동일 골격 |
| clustering algorithm | **VBxClustering (PLDA, default)** — AgglomerativeClustering 도 enum 에 있음 | streaming 은 batch VBx 사용 불가 → diart 의 `OnlineSpeakerClustering` 채택 (reference-08) |
| 각 단계 데이터 형식 | `SlidingWindowFeature` 일관 사용 | 우리도 sliding window 추상화 채택 |
| segmentation step | **0.1 × duration = 1.0초** (90% overlap) | streaming 은 latency vs accuracy trade-off — 0.5초 (50% overlap) 도 흔함 |
| skip_aggregation 모드 | ✅ Pipeline 은 chunk 별 raw segmentation 유지 | streaming 도 동일 패턴 (chunk → mask → emb → cluster → reconstruct) |
| embedding 호출 시 mask | ✅ `weights=mask` 로 frame 가중 — overlap 자동 다운웨이트 | 우리도 mask 가중 embedding 호출 |
| min_duration_off / cluster threshold | 명확한 default (0.0 / 0.6) | 우리 default 시작점 |

### Batch vs Streaming 차이

| 단계 | Batch pyannote | Streaming (우리 라이브러리) |
|---|---|---|
| 전체 파일 vs chunk 누적 | 전체 파일 받음 | 짧은 chunk (0.5초) 가 들어와 10초 buffer 채움 |
| segmentation | 한번에 모든 chunk | chunk 가 채워질 때마다 forward |
| embedding | 모든 chunk 의 모든 speaker 일괄 | chunk 별 즉시 |
| clustering | VBxClustering (전체 globally) | **OnlineSpeakerClustering** (chunk 별 증분, reference-08) |
| 마지막 reconstruct | 전체 timeline 한번에 | 발화 단위로 yield |
| 출력 | `Annotation` 전체 | 발화별 `SpeakerSegment` stream |

→ **streaming 의 핵심 차이는 clustering 단계**. 나머지는 batch 와 동일 building block 재사용 가능.

---

## 미확인 사항 (남은 것)

- `clustering.py` 의 `VBxClustering`, `AgglomerativeClustering`, `OracleClustering` 내부 — clustering.py 자체는 정독 필요시.
- `to_diarization` 의 정확한 로직 (`SpeakerDiarizationMixin` Mixin) — chunk 간 timeline 정합 알고리즘.
- `speaker_count` 의 정확한 알고리즘 — receptive_field 의 sliding window 별 max 추정 등 디테일.
- legacy 3.1 pipeline 의 차이 (PLDA 없음, AgglomerativeClustering) — community-1 와 비교 필요시.
