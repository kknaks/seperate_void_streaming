---
id: reference-01
type: reference
title: pyannote/segmentation-3.0 — 모델 카드 정리
status: draft
created: 2026-05-14
updated: 2026-05-14
source_url: https://huggingface.co/pyannote/segmentation-3.0
fetched_at: 2026-05-14
sources: []
tags: [reference, pyannote, segmentation, model, study-step-1]
---

# pyannote/segmentation-3.0 — 모델 카드 정리

> **출처**: https://huggingface.co/pyannote/segmentation-3.0 (2026-05-14 fetch)
> **목적**: 학습 1단계 — 우리 라이브러리의 핵심 입력 모델 동작 이해

## Summary

10초 audio window 를 받아 frame 단위로 누가 말하는지 (overlap 포함) 출력하는 segmentation 모델. **단독으로 전체 파일 diarization 불가** — sliding window + aggregation + clustering 별도 필요.

---

## 1. 입력 명세

| 항목 | 값 |
|---|---|
| Sample rate | **16 kHz** |
| Audio length (window) | **10초 고정** |
| Channels | **1 (mono)** |
| Shape | `(batch_size, 1, 160000)` |

```python
duration, sample_rate, num_channels = 10, 16000, 1
waveform = torch.randn(batch_size, num_channels, duration * sample_rate)
# shape = (batch_size, 1, 160000)
```

→ 우리 라이브러리에서 **chunk 누적 = 10초 window** 가 정답. 5초 가정 잘못이었음.

## 2. 출력 명세 — Powerset 7-class

| 항목 | 값 |
|---|---|
| Shape | `(num_frames, 7)` |
| Encoding | **Powerset multi-class** (단순 multi-label 아님) |

**7 classes**:

| Class | 의미 |
|---|---|
| 0 | Non-speech |
| 1 | Speaker #1 only |
| 2 | Speaker #2 only |
| 3 | Speaker #3 only |
| 4 | Speaker #1 + #2 (overlap) |
| 5 | Speaker #1 + #3 (overlap) |
| 6 | Speaker #2 + #3 (overlap) |

각 frame 에서 **하나의 class** 만 active (softmax). overlap 은 별도 class 로 표현됨.

### Powerset → Multilabel 변환

```python
from pyannote.audio.utils.powerset import Powerset
max_speakers_per_chunk, max_speakers_per_frame = 3, 2
to_multilabel = Powerset(
    max_speakers_per_chunk,
    max_speakers_per_frame
).to_multilabel
multilabel_encoding = to_multilabel(powerset_encoding)
# 결과: (num_frames, 3) — 각 frame 의 화자별 active 여부
```

**제약**:
- 한 chunk(10초)에 **최대 3 화자**
- 한 frame 에 **최대 2 화자 동시** (overlap)

## 3. Frame Rate / Temporal Resolution

⚠️ **모델 카드 미명시**. 일반적 pyannote 모델은 ~20ms (50 fps) frame shift. **실제 코드 확인 필요** (학습 2단계 — Explore 워커가 검증).

추정: 10초 / 0.02초 = **약 500 frames** per chunk. 실제는 padding/stride 따라 다를 수 있음.

## 4. 단독 사용 한계

> "**Cannot perform full-recording speaker diarization alone**" — 모델 카드 직접 인용

- 10초 chunk 단위로만 inference 가능
- chunk 간 화자 매칭 (다른 chunk 의 Speaker#1 = 같은 사람?) 정보 없음
- 전체 파일 diarization 은 `pyannote/speaker-diarization-community-1` (또는 legacy `3.1`) 별도 파이프라인 사용

## 5. 사용 예시 코드

### 모델 로드
```python
from pyannote.audio import Model
model = Model.from_pretrained(
    "pyannote/segmentation-3.0",
    use_auth_token="HF_TOKEN"
)
```

### VAD (Voice Activity Detection)
```python
from pyannote.audio.pipelines import VoiceActivityDetection
pipeline = VoiceActivityDetection(segmentation=model)
pipeline.instantiate({"min_duration_on": 0.0, "min_duration_off": 0.0})
vad = pipeline("audio.wav")
```

### Overlap Detection
```python
from pyannote.audio.pipelines import OverlappedSpeechDetection
pipeline = OverlappedSpeechDetection(segmentation=model)
pipeline.instantiate({"min_duration_on": 0.0, "min_duration_off": 0.0})
osd = pipeline("audio.wav")
```

## 6. 라이센스 / 접근

- HuggingFace **access token + user condition agreement** 필수
- 사용 전 `https://huggingface.co/pyannote/segmentation-3.0` 에서 Accept 클릭

---

## 우리 라이브러리 영향 (1차)

| 우리 가정 | 실제 | 조정 |
|---|---|---|
| sliding window 5초 | **10초 고정** | window 크기 10초로 |
| 출력 = activity matrix `[T, speakers]` | **powerset `[T, 7]`** | powerset decoder 필요 |
| 한 window 내 화자 식별 끝 | 한 chunk 내에서만 — chunk 간 매칭은 embedding clustering 의 일 | sliding window aggregation + 화자 매핑 별도 |
| overlap = 모델 출력에 자연 포함 | ✅ 맞음 (class 4/5/6) | 그대로 |

**streaming 구현 시 추가 작업**:
1. chunk 누적 → 10초 buffer 채우기 (hop 으로 sliding)
2. 모델 inference → powerset 출력
3. powerset → multilabel decode
4. 화자별 active 시간 구간 추출
5. 겹치는 window 결과 aggregation (보통 평균)
6. chunk 간 화자 매칭 = embedding clustering (다음 단계 — reference-02)

---

## 미확인 사항 (학습 2단계에서)

- [ ] 정확한 frame rate (20ms? 다른 값?)
- [ ] sliding window hop 의 권장 값 (보통 500ms?)
- [ ] aggregation 방식 (mean / max / weighted)
- [ ] padding 처리 (10초 안 차는 마지막 chunk)
- [ ] GPU/CPU latency
