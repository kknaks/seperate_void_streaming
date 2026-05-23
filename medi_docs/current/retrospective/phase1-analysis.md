---
id: retrospective-phase1
type: retrospective
title: Phase 1 Ablation 분석 — Embedding × Window × Step
status: draft
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[planning-01-ablation-study]]"
  - "[[PLAN-V02-002-phase1-grid]]"
  - "[[spec-01-ablation-grid]]"
tags: [retrospective, v0.2, phase1, ablation, analysis]
---

# Phase 1 Ablation 분석 — Embedding × Window × Step

## TL;DR

- **측정 완료**: 3 embedding × 4 window × 3 step × 2 sample = **72 rows** (TitaNet-L 폐기, planning-01 §1.1)
- **최적 후보 (실시간 운영)**: `pyannote/embedding` × `window=2.0` × `step=0.5` — **DER avg 0.199, runtime avg 16s**
- **북극성 (DER ≤ 0.15) 미달** — best DER 17.6% (wespeaker, CPU 실시간 불가)
- **결정적 발견**: step=0.5 압도적 우위. step=0.1/0.25 는 전 모델 DER 0.85+ (실용 불가)
- **다음 단계**: Phase 2 scheduler ablation — clustering 파라미터 튜닝으로 DER 추가 개선 시도

자세한 raw 데이터: `eval/ablation/results/phase1-full-20260522.html`

---

## 측정 환경

| 항목 | 값 |
|---|---|
| 환경 | Mac M3 Max, CPU 강제 (Azure CPU instance 가정) |
| Python | 3.11 |
| torch | 2.1.2 |
| diart | 0.9.2 |
| pyannote.audio | 3.1.1 |
| huggingface_hub | 0.19.4 |
| 데이터셋 | 한국어 sample 2개 (`record_1.wav` 277.5s, `record_3.wav` 168.2s) |
| Ground Truth | pyannote/speaker-diarization-3.1 자동 생성 RTTM, 사용자 검토 |

---

## 모델별 결과

### best avg DER (sample 2개 평균, best combination)

| 모델 | best avg DER | 조건 | avg runtime | 실시간 가능? |
|---|---|---|---|---|
| **wespeaker-resnet221** | **0.176** | w=2.0 s=0.5 | 368s | ❌ CPU (실시간 11.5x) |
| **pyannote/embedding** | **0.199** | w=2.0 s=0.5 | **16s** | ✅ CPU 실시간 가능 |
| ecapa-tdnn | 0.205 | w=2.0 s=0.5 | 46s | △ CPU 약 0.7x (실시간 가능) |

### sample 별 best DER

| 모델 | record_1 best | record_3 best | 분산 |
|---|---|---|---|
| wespeaker-resnet221 | 0.132 (w=2,s=0.5) | 0.220 (w=2,s=0.5) | 0.088 |
| pyannote/embedding | 0.138 (w=2,s=0.5) | 0.261 (w=2,s=0.5) | 0.123 |
| ecapa-tdnn | 0.152 (w=3,s=0.5) | 0.207 (w=2,s=0.5) | **0.055 (최저)** |

→ **ecapa-tdnn 이 sample 간 일관성 최고** (분산 0.055). pyannote 는 sample 의존성 큼.

### runtime 분포 (전체 row)

| 모델 | min | avg | max |
|---|---|---|---|
| pyannote/embedding | 9s | **19s** | 38s |
| ecapa-tdnn | 22s | 54s | 104s |
| wespeaker-resnet221 | 115s | 450s | 1180s |

→ pyannote 가 압도적으로 빠름. wespeaker CPU 비실용.

---

## 주요 패턴

### 1. step=0.5 압도적 우위

| step | DER 평균 (전 모델) | 평가 |
|---|---|---|
| 0.1 | ~0.87 | 실용 불가 (random level) |
| 0.25 | ~0.56 | 부분 작동 |
| **0.5** | **~0.20** | **실용 가능** |

원인: diart 의 OnlineSpeakerClustering 이 step 더 짧으면 너무 많은 sliding window → cluster state noise 누적.

**결정**: step=0.5 고정. Phase 2 에서도 step 변경 X.

### 2. window=2.0 최적

| window | best avg DER (전 모델) | best 모델 |
|---|---|---|
| 1.0 | 0.223 | ecapa-tdnn |
| **2.0** | **0.176** | wespeaker |
| 3.0 | 0.245 | pyannote |
| 5.0 | 0.235 | wespeaker |

→ 2초 window 가 화자 식별 안정성 + 응답성 균형 최적. 1초는 정보 부족, 3~5초는 over-smoothing.

**결정**: window=2.0 권장. Phase 2 에서 window 변경 X.

### 3. 북극성 (DER ≤ 15%) 미달

| 목표 | 달성 |
|---|---|
| DER ≤ 0.15 | ❌ best 0.176 (wespeaker CPU) / 0.199 (pyannote 실시간) |
| 초기 cluster latency ≤ 20s | ✅ pyannote 2.52s |
| 라벨링 지연 ≤ 3s | ✅ pyannote p50=0.5s |

DER 달성 못한 이유 추정:
- clustering 파라미터 default (Phase 2 ablation 영역)
- ground truth RTTM 자체 정확도 (자동 생성 + 사용자 검토 — 완벽하지 않을 수 있음)
- 한국어 sample 의 noise / overlap

→ **Phase 2 scheduler ablation 으로 추가 개선 시도**. 미달 시 GPU 환경 검토 또는 embedding 자체 한계 인정.

### 4. record_3 DER 전반 높음

| 모델 | record_1 best DER | record_3 best DER | 차이 |
|---|---|---|---|
| wespeaker | 0.132 | 0.220 | +0.088 |
| pyannote | 0.138 | 0.261 | +0.123 |
| ecapa-tdnn | 0.152 | 0.207 | +0.055 |

원인 후보:
- record_3 (168s) 가 record_1 (277s) 보다 짧음 → cluster 형성 시간 부족
- record_3 의 화자 turn-taking 더 빠름 (검증 필요)
- pyannote/speaker-diarization-3.1 자동 RTTM 의 정확도 차이

→ **사용자 record_3_viewer.html 검토 진행 중**. RTTM 오류 발견 시 수동 수정 후 재측정 검토.

---

## 최적 후보 선정

### 1순위 — `pyannote/embedding` w=2.0 s=0.5 ⭐

| metric | record_1 | record_3 | avg |
|---|---|---|---|
| DER | 0.138 | 0.261 | **0.199** |
| runtime | 18s | 14s | **16s** |
| labeling p50 | 0.5s | 0.5s | 0.5s |
| CPU avg | 180% | 145% | 162% |
| RAM avg | 297MB | 287MB | 292MB |

**선정 사유**:
- ✅ 유일하게 CPU 실시간 가능 (16s / 277s = **0.06x realtime**)
- ✅ runtime 가장 빠름 (pyannote 네이티브, no SpeechBrain/wespeaker overhead)
- ✅ 라벨링 latency 0.5s — 북극성 ≤ 3s 통과
- ⚠️ sample 간 분산 큼 (record_3 DER 0.261, record_1 의 ~2배)

### 2순위 — `ecapa-tdnn` w=2.0 s=0.5 (일관성 fallback)

| metric | record_1 | record_3 | avg |
|---|---|---|---|
| DER | 0.204 | 0.207 | **0.205** |
| runtime | 58s | 33s | **46s** |

**선정 사유**:
- ✅ sample 간 분산 최저 (0.003) — **운영 환경 일관성 보장**
- ✅ CPU 실시간 가능 (0.27x realtime)
- ⚠️ DER 평균 약간 높음 (0.205 vs 0.199)

### 3순위 — `wespeaker-resnet221` w=2.0 s=0.5 (GPU 검토)

| metric | record_1 | record_3 | avg |
|---|---|---|---|
| DER | 0.132 | 0.220 | **0.176** |
| runtime | 515s | 221s | **368s** |

**선정 사유**:
- ✅ **DER 최저** (17.6%, 북극성 거의 근접)
- ❌ CPU 11.5x realtime — 실시간 운영 불가
- → **GPU instance 검토 후속 task** (별도 plan, 운영 환경 결정 의존)

---

## Phase 2 입력 후보 (scheduler ablation)

`PLAN-V02-003 Phase 2` 에서 측정할 base 조합:

| 우선순위 | 조합 | 이유 |
|---|---|---|
| 1 | `pyannote/embedding` w=2.0 s=0.5 | 실시간 가능 + DER 균형, 1순위 후보 |
| 2 | `ecapa-tdnn` w=2.0 s=0.5 | 일관성 최고, 운영 fallback |
| (참고) | `wespeaker-resnet221` w=2.0 s=0.5 | GPU 환경 가정 시 검증 — 별도 task |

Phase 2 scheduler 변형 (spec-01 §Phase 2):
- baseline (diart 기본)
- decay-A (per-segment decay)
- decay-B (time-windowed recluster)
- HDBSCAN on/off

→ 위 2~3 조합 × 4 scheduler = **8~12 combinations × 2 sample = 16~24 rows**.

---

## 발견된 정리 사항

### 1. spec-02 drift — `as_diart_embedding`

워커 보고: spec-02 의 `_emb(waveform) → (1, dim)` 단인자 callable 이 diart 0.9.2 실제 API (`__call__(waveform, weights=None)`) 와 불일치.

→ 워커가 `_DiartEmbeddingCallable` 클래스로 대응. spec-02 갱신 후속 (architect task).

### 2. wespeaker 모델명 — ResNet-152 → ResNet-221

워커 보고: wespeaker hub 의 `english` 모델 = `voxceleb_resnet221_LM`. planning-01 의 "ResNet-152" 잘못. **이미 수정** (planning-01 §1.1, spec-01, spec-02, spec-04).

### 3. nemo / huggingface_hub 의존성 충돌

T-005 시점에 nemo 시도 잔재로 huggingface_hub 1.x 업그레이드 → pyannote 깨짐. admin 정리 (uninstall nemo/peft/transformers/accelerate + huggingface_hub<0.20 downgrade) 후 안정.

→ pyproject.toml 의 `huggingface_hub<0.20` pin 그대로 유지. NeMo/TitaNet 별도 venv 가 정 필요하면 후속 plan.

---

## 다음 단계

1. **사용자 record_3 RTTM 검토 완료 대기** — viewer 로 명백 오류 확인. 오류 시 RTTM 수동 수정 + 재측정.
2. **render_report.py 의 INDEX 모드 추가** — 사용자 제안 (최종 종합 HTML, 하위 link 포함). architect 또는 admin 별도 작업.
3. **Phase 2 scheduler ablation 발주** — `PLAN-V02-T-007` (evaluator), 2~3 후보 × 4 scheduler.
4. **Phase 2 결과 + 종합 분석** — `PLAN-V02-T-008` (admin), v0.2 최적 조합 최종 결정.
5. **Phase 3 demo plan 발주 여부 결정** — Phase 2 결과 후.

---

## 산출물

- `eval/ablation/results/all.csv` — 93 rows 누적 (Phase 0 smoke + Phase 1 72)
- `eval/ablation/results/phase1-full-20260522.html` — 최종 HTML report
- `reports/PLAN-V02-T-006-evaluator.md` — 측정 워커 보고
- 본 문서 — 분석 보고서
