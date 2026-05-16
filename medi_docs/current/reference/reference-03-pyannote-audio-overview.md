---
id: reference-03
type: reference
title: pyannote.audio — toolkit 개요
status: draft
created: 2026-05-14
updated: 2026-05-14
source_url: https://github.com/pyannote/pyannote-audio
fetched_at: 2026-05-14
sources:
  - "[[reference-01-pyannote-segmentation-3]]"
  - "[[reference-02-pyannote-embedding]]"
tags: [reference, pyannote, toolkit, overview, study-step-1]
---

# pyannote.audio — toolkit 개요

> **출처**: https://github.com/pyannote/pyannote-audio (2026-05-14 fetch)
> **현재 버전**: 4.0.4 (2026-02-07)
> **목적**: 학습 1단계 — toolkit 전체 그림

## Summary

PyTorch 기반 **speaker diarization** 오픈소스 toolkit. "누가 언제 말하는지" 식별. 신경망 building blocks (VAD / segmentation / embedding / clustering) + 통합 pretrained pipeline 제공.

---

## 1. 주요 Pretrained Pipelines

| Pipeline | ID | 종류 |
|---|---|---|
| **community-1** | `pyannote/speaker-diarization-community-1` | **오픈소스 무료** |
| **precision-2** | `pyannote/speaker-diarization-precision-2` | 프리미엄 (유료) |
| legacy 3.1 | `pyannote/speaker-diarization-3.1` | 이전 버전 |

→ **우리는 community-1 또는 legacy 3.1 을 직접 사용 가능**. 또는 그 안의 building blocks (segmentation, embedding) 만 떼서 사용.

## 2. Pipeline 사용 예시 (전체 파일 diarization)

```python
from pyannote.audio import Pipeline
pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-community-1",
    token="HUGGINGFACE_ACCESS_TOKEN"
)
output = pipeline("audio.wav")

for turn, speaker in output.speaker_diarization:
    print(f"start={turn.start:.1f}s stop={turn.end:.1f}s speaker_{speaker}")
```

**출력**: `(turn, speaker)` 튜플 stream — turn 은 시간 구간, speaker 는 라벨 (`speaker_0`, `speaker_1`, ...).

→ 이게 **batch 모드**. 전체 파일이 있어야 동작. streaming X.

## 3. Neural Building Blocks

| Block | 역할 |
|---|---|
| **Voice Activity Detection (VAD)** | 음성 vs 비음성 구분 |
| **Speaker Change Detection** | 화자 전환 시점 감지 |
| **Overlapped Speech Detection** | 동시 발화 구간 감지 |
| **Speaker Embedding** | 화자 identity vector |
| (Clustering) | embedding clustering — 같은 화자 그룹화 |

→ 우리 라이브러리는 이 building blocks 을 **streaming 방식으로 재조합**.

## 4. 기술 스택

| 항목 | 값 |
|---|---|
| 언어 | Python |
| 기반 | **PyTorch** |
| 현재 버전 | **4.0.4** (2026-02-07) |
| 모델 배포 | HuggingFace Hub |

→ 우리 라이브러리 의존성: `pyannote.audio >= 4.0`, `torch`, `numpy`, `scipy`, `scikit-learn`, `hdbscan`

## 5. Streaming / 실시간 사용

README 직접 확인 결과:
- "Streaming voice activity detection" 블로그 포스트 언급
- **실시간 / streaming 제약 명시 X**
- 공식 streaming pipeline 제공 X (그래서 diart 같은 외부 도구 존재)

→ **결론**: pyannote.audio 자체는 batch 우선. streaming 은 사용자가 직접 구현 (또는 diart 같은 wrapper).

---

## 우리 라이브러리의 위치

```
┌─────────────────────────────────────────────────────────┐
│ 사용처 (회의/콜센터/의료) — WS, FastAPI, STT, UI, DB    │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ speaker_engine (우리)                                   │
│                                                          │
│  - 3-tier 라벨링 (registered / stored / auto)            │
│  - SpeakerStore (pgvector / sqlite / memory)            │
│  - 발화 단위 SpeakerSegment 출력                         │
│  - persist / candidates / LabelChange                   │
│  - streaming 인프라 (sliding window, VAD, aggregation)  │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼ (직접 / 또는 diart 경유)
┌─────────────────────────────────────────────────────────┐
│ pyannote.audio (외부 의존)                              │
│  - segmentation-3.0 (10초 chunk 화자 분리)               │
│  - embedding (D-dim 화자 identity)                       │
│  - Pipeline (batch diarization)                          │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
                       PyTorch
```

**우리 라이브러리의 가치 = 도메인 layer + streaming 인프라**.
pyannote 모델만 갈아끼우면 (재학습 모델 / 다른 backbone) 우리 코드 그대로 활용 가능.

---

## 학습 2단계에서 확인할 사항

1. `pyannote.audio.Pipeline` 내부 코드 — segmentation + embedding + clustering 어떻게 조합?
2. `pyannote.audio.Inference` 의 sliding window 동작 코드
3. `pyannote/speaker-diarization-community-1` 의 yaml/config — 어떤 hyperparameter?
4. embedding 모델의 정확한 D 차원 + 입력 명세
5. segmentation-3.0 의 정확한 frame rate
6. diart 가 이 위에서 무엇을 추가하는가 (소스 코드 비교)

→ Explore agent 로 `pyannote-audio` repo 핵심 파일 정리 (다음 turn).
