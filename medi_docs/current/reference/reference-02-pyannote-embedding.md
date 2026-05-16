---
id: reference-02
type: reference
title: pyannote/embedding — 모델 카드 정리
status: draft
created: 2026-05-14
updated: 2026-05-14
source_url: https://huggingface.co/pyannote/embedding
fetched_at: 2026-05-14
sources:
  - "[[reference-01-pyannote-segmentation-3]]"
tags: [reference, pyannote, embedding, model, study-step-1]
---

# pyannote/embedding — 모델 카드 정리

> **출처**: https://huggingface.co/pyannote/embedding (2026-05-14 fetch)
> **목적**: 학습 1단계 — 화자 식별 벡터 추출 모델 동작 이해

## Summary

단일 화자 audio → **D-dim 화자 identity vector** 추출. 같은 사람이면 코사인 거리가 가까움 (VoxCeleb1 EER 2.8%). overlap 구간이 아닌, **이미 화자별로 분리된 audio** 가 입력.

---

## 1. 입력 명세

| 항목 | 값 |
|---|---|
| Sample rate | **모델 카드 미명시** (관행적으로 16 kHz) |
| 최소/최대 길이 | **미명시** |
| Channels | **미명시** (관행적으로 mono) |

→ 학습 2단계 에서 실제 코드 확인 필요.

## 2. 출력 명세

| Mode | 출력 Shape | 의미 |
|---|---|---|
| `whole` | `(1 × D)` numpy | 파일 전체 → 단일 embedding |
| `sliding` | `(N × D)` `pyannote.core.SlidingWindowFeature` | 시간축 N 개 position 별 embedding |

D = embedding 차원. 일반적으로 **512** (확정은 실제 코드 확인 필요).

## 3. Inference 모드

### `whole` — 파일 전체 → 단일 embedding
```python
inference = Inference(model, window="whole")
embedding = inference("speaker1.wav")
# shape = (1, D)
```

### `sliding` — 시간축 sliding window
```python
inference = Inference(model, window="sliding",
                      duration=3.0, step=1.0)
embeddings = inference("audio.wav")
# embeddings[i] = ith position 의 embedding
```

- `duration`: window 길이 (초)
- `step`: hop (초)

## 4. 권장 사용

**단일 화자 audio** 입력. overlap 또는 mixed speaker 구간에 대한 신뢰도 보장 없음.

→ 우리 라이브러리에서: segmentation-3.0 으로 화자별 시간 구간을 먼저 추출하고, 각 구간의 audio 를 잘라서 embedding 모델에 입력.

## 5. 유사도 메트릭

| 항목 | 값 |
|---|---|
| 권장 거리 | **Cosine distance** |
| 성능 | **2.8% EER** on VoxCeleb 1 test set |
| Threshold 가이드 | **모델 카드 미명시** |

> "Using cosine distance directly, this model reaches 2.8% equal error rate (EER) on VoxCeleb 1 test set."

EER 2.8% 는 매우 낮은 (좋은) 수치 — 같은 사람 / 다른 사람 구분 정확도 높음.

**threshold 추정**:
- cosine **distance** ≤ 0.3 → 같은 사람일 가능성 (= cosine **similarity** ≥ 0.7)
- 실제 운영 threshold 는 데이터셋 별 튜닝 필요 (우리 planning-02 의 0.70/0.75 는 일반 가이드)

## 6. 사용 예시 코드

```python
from pyannote.audio import Model, Inference
from scipy.spatial.distance import cdist

model = Model.from_pretrained(
    "pyannote/embedding",
    use_auth_token="HF_TOKEN"
)
inference = Inference(model, window="whole")

embedding1 = inference("speaker1.wav")
embedding2 = inference("speaker2.wav")

distance = cdist(embedding1, embedding2, metric="cosine")[0, 0]
# distance < 0.3 ~ 0.4 → 같은 화자 가능성
```

---

## 우리 라이브러리 영향 (1차)

| 우리 가정 | 실제 | 조정 |
|---|---|---|
| 입력 = 단일 화자 audio | ✅ 맞음 | segmentation-3.0 결과로 화자별 audio 추출 후 입력 |
| 출력 = 512-dim | D-dim, 보통 512 (확정 필요) | 학습 2단계에서 확인 |
| metric = cosine | ✅ 맞음 | 그대로 |
| threshold registered=0.70 / stored=0.75 | 가이드 없음 (튜닝 필요) | 데이터셋 별 측정 후 조정 |

**streaming 구현 시 흐름**:
1. segmentation 결과로 화자별 발화 시간 구간 추출
2. 각 구간의 audio 자르기 (raw waveform slicing)
3. `Inference(window="whole")` 로 embedding 추출 (한 발화 = 1 embedding)
4. 등록 화자 / stored / online cluster centroid 와 cosine 비교

---

## 미확인 사항 (학습 2단계에서)

- [ ] 정확한 D (embedding 차원) — 512 추정
- [ ] 최소 audio 길이 (너무 짧으면 embedding 신뢰도 ↓)
- [ ] sample rate 명시 (16 kHz 추정)
- [ ] sliding mode 의 권장 duration/step
- [ ] GPU/CPU inference latency
- [ ] L2 정규화 여부 (이미 normalized 인지)
