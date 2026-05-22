---
id: plan-01
type: plan
title: PLAN-V02 — Embedding × Window × Scheduler Ablation Study
status: draft
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[adr-01-ablation-centric-design]]"
tags: [plan, v0.2, ablation, diarization, korean]
---

# PLAN-V02 — Embedding × Window × Scheduler Ablation Study

## 한 줄

한국어 회의/상담 도메인에서 화자 분리 정확도 최적화하는 (embedding model × window size × step × 시간감쇠 scheduler) 조합 도출.

## 배경

v0.1-demo (PLAN-001~006 STT-driven chain + speaker_engine wrapper) 폐기.  
근거: admin smoke v6~v11 측정으로 phrase-level embedding 의 본질 한계 (duration-dependent cluster, sliding window 정확도 한계) 확인.  
상세: `medi_docs/legacy/v0.1-demo/LEGACY_NOTE.md`

## 북극성

> "한국어 회의/상담 도메인에서 다인 화자 분리 정확도 (DER) ≤ 15% +  
> 초기 cluster 형성 latency ≤ 20s + 라벨링 지연 ≤ 3s"

---

## Phase 0 — 환경 준비

### 0.1 데이터셋

| 종류 | 설명 | 비고 |
|------|------|------|
| AMI corpus subset | 영어 baseline, 4 session | V-01 baseline 그대로 |
| 한국어 회의/상담 sample | record_1.wav 외 N개 | 사용자 제공 |

- 각 sample 의 ground truth annotation: RTTM 또는 동등

### 0.2 metric

| metric | 도구 | 설명 |
|--------|------|------|
| DER (Diarization Error Rate) | pyannote.metrics | 주 KPI |
| 초기 cluster 형성 latency | 자체 측정 | 첫 stable cluster 도달 시점 |
| 라벨링 지연 | 자체 측정 | PCM 입력 → labeled segment emit |
| 라벨 일관성 | 자체 측정 | 동일 화자 라벨 변동률 |
| **CPU 사용률** | `psutil` | per-second peak + average |
| **RAM 사용량** | `psutil` | peak + average (MB) |
| **GPU 사용률** | `pynvml` / `nvidia-smi` | peak + average (%) — GPU 환경 시 |
| **GPU 메모리** | `pynvml` | peak (MB) — GPU 환경 시 |
| **모델 cold-load 시간** | 자체 측정 | embedding 모델 첫 로드 latency |

### 0.3 평가 스크립트

- 신설: `scripts/eval_ablation.py`
- 입력: `(embedding_model, window_s, step_s, scheduler_params, sample_audio)`
- 출력: DER + latency 측정값
- 결과 누적: CSV / JSON 결과 표

---

## Phase 1 — embedding × window ablation

### 1.1 embedding 후보 (4종)

| 모델 | dim | 권장 window | 비고 |
|------|-----|------------|------|
| pyannote/embedding | 512 | 3~5s | baseline |
| ECAPA-TDNN (SpeechBrain) | 192 | 1~2s | 경량 |
| WeSpeaker ResNet152 | 256 | 1s+ | 오픈소스 |
| TitaNet-L (NeMo) | 192 | 0.5~1s | NeMo 의존 — 포함 결정 (admin 2026-05-22) |

### 1.2 window 후보 (4종)

- 1s / 2s / 3s / **5s** (baseline)

### 1.3 step 후보 (3종)

- 0.1s / 0.25s / **0.5s** (baseline)

### 1.4 grid size

```
4 embedding × 4 window × 3 step = 48 combinations
AMI 4 session × 한국어 N sample = 4+N samples
총 measurement: 48 × (4+N)  — 추정 1~2시간 GPU 또는 수시간 CPU
```

### 1.5 결과 표

각 조합의 DER + latency + 라벨 일관성 → 최적 후보 3~5개 선정

---

## Phase 2 — 시간감쇠 scheduler ablation

### 2.1 scheduler 변형

| 변형 | 설명 |
|------|------|
| baseline | diart OnlineSpeakerClustering 기본 (감쇠 없음) |
| 시간감쇠 A | initial 매 segment → 점점 매 N segment |
| 시간감쇠 B | time-windowed recluster (5/15/30/60s 단위) |
| FinalReclusterer (HDBSCAN) | on / off |

### 2.2 적용 기반

Phase 1 최적 embedding × window 위에서 각 scheduler 조합 측정

### 2.3 결과

- 시간감쇠 실제 효과 검증 (PLAN-005 측정: finalize ≈ online 결과 재확인)
- 효과 있으면 채택, 없으면 폐기

---

## Phase 3 (선택, 후속 plan) — demo 구현

ablation 결과 기반 단순 demo (별도 plan 분리):

- diart + 선택 embedding + ElevenLabs STT
- segment ↔ STT overlap → labeled_phrase
- 4-패널 grid UI (v0.1 자산 활용)
- speaker_engine wrapper 폐기 또는 슬림화

> Phase 0~2 결과 보고 후 별도 plan 발주 결정

## Phase 4 (out of scope) — enrollment + 운영

별도 plan. v0.2 에선 제외.

---

## 작업 분해

| T | 작업 | 워커 | 상태 |
|---|------|------|------|
| T-003 | spec suite 작성 (ablation grid + embedding interface + eval script + report + dataset + metrics) | architect | **done** (PLAN-V02-T-003) |
| T-004 | Phase 0 환경 구축 — 4 모델 install + 데이터셋 + eval_ablation.py 구현 | evaluator | 예정 |
| T-005 | Phase 1 — embedding × window grid 실행 + JSON 결과 | evaluator | 예정 |
| T-006 | Phase 1 결과 분석 + 최적 후보 선정 | admin | 예정 |
| T-007 | Phase 2 — scheduler ablation | evaluator | 예정 |
| T-008 | Phase 2 결과 + 종합 분석 + 최적 조합 결정 | admin | 예정 |
| T-009 (선택) | Phase 3 demo 구현 plan 분리 | architect | 예정 |

---

## DoD (v0.2 plan 자체)

- [ ] Phase 0~2 결과 표 + 최적 조합 도출
- [ ] speaker_engine wrapper 폐기/슬림화 결정 (Phase 2 결과 후)
- [ ] 다음 plan (Phase 3 demo 또는 enrollment) 발주 준비

---

## 보존 자산 (legacy 참조 가능)

| 자산 | 위치 |
|------|------|
| ElevenLabs STT 어댑터 | server/stt/elevenlabs.py |
| ServerVAD | server/stt/vad.py |
| 4-패널 grid UI | web/index.html |
| AudioWorklet PCM capture | web/ |
| Docker compose | docker-compose.yml |
| AMI 데이터 + 한국어 sample | (사용자 보유) |

## 폐기 자산 (v0.1-demo)

- speaker_engine: OnlineSpeakerClusterer wrapper / AdaptiveScheduler / FinalReclusterer / identify_phrase / running average / threshold knobs
- PLAN-006 STT-driven chain: _flush_phrase / word gap / sentence split / segment lookup
- 모든 v0.1-demo plan/adr/spec/planning

> 코드 자체 삭제는 별도 task — 현재는 git history 로 보존

---

## 아키텍처 흐름 (Phase 1)

```mermaid
flowchart TD
    A["Audio Input<br/>AMI / 한국어 sample"] --> B[eval_ablation.py]
    B --> C{"embedding model<br/>× window × step<br/>48 combinations"}
    C --> D["DER 측정<br/>pyannote.metrics"]
    C --> E["latency 측정<br/>초기 cluster + 라벨링"]
    C --> F[라벨 일관성]
    C --> R["리소스 측정<br/>CPU / RAM / GPU% / GPU mem"]
    C --> S[모델 cold-load 시간]
    D & E & F & R & S --> G[결과 CSV / JSON]
    G --> H["최적 후보 3~5개 선정<br/>(정확도 + 비용 trade-off)"]
```

## 아키텍처 흐름 (Phase 2)

```mermaid
flowchart TD
    H[Phase 1 최적 조합] --> I{scheduler 변형}
    I -->|baseline| J[diart default]
    I -->|시간감쇠 A| K[per-segment decay]
    I -->|시간감쇠 B| L[time-windowed recluster]
    I -->|HDBSCAN| M[FinalReclusterer on/off]
    J & K & L & M --> N[DER 측정]
    N --> O{"효과 있음?"}
    O -->|Yes| P[scheduler 채택]
    O -->|No| Q[폐기]
```
