---
id: retrospective-v02-final
type: retrospective
title: v0.2 Ablation Study 최종 종합 — Phase 1 + Phase 2
status: accepted
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[planning-01-ablation-study]]"
  - "[[retrospective-phase1]]"
  - "[[PLAN-V02-002-phase1-grid]]"
  - "[[PLAN-V02-003-phase2-scheduler]]"
tags: [retrospective, v0.2, final, ablation, decision]
---

# v0.2 Ablation Study 최종 종합 — Phase 1 + Phase 2

## TL;DR

**최종 최적 조합**:
```
embedding   = pyannote/embedding
window_s    = 2.0
step_s      = 0.5
scheduler   = baseline (diart OnlineSpeakerClustering 기본)
device      = cpu (Azure CPU instance)
```

**측정 결과**:
- DER avg **0.199** (북극성 ≤ 0.15 미달, 그러나 실시간 가능 후보 중 최선)
- runtime **16s** / 277s audio = **0.06x realtime** (실시간 OK)
- 초기 cluster latency 2.52s, labeling latency p50 0.5s
- CPU avg 162%, RAM avg 292MB

**총 측정**:
- Phase 1: 3 embedding × 4 window × 3 step × 2 sample = 72 rows
- Phase 2: 2 후보 × 5 scheduler × 2 sample = 20 rows (Phase 1 baseline 4 row 재사용)
- 합계: **92 unique rows**

---

## 결정 사항

### Decision 1 — 최종 최적 조합: pyannote/embedding × w=2.0 × s=0.5 × baseline

| 기준 | pyannote ⭐ | ecapa-tdnn | wespeaker-resnet221 |
|---|---|---|---|
| best avg DER | **0.199** | 0.205 | 0.176 (CPU 비실용) |
| runtime | **16s** ✓ | 46s ✓ | 368s ✗ |
| 초기 latency | 2.52s ✓ | ~3s ✓ | ~5s |
| 라벨링 p50 | 0.5s ✓ | 0.5s ✓ | 0.5s |
| sample 분산 | 0.123 (큼) | **0.055** | 0.088 |
| 운영 추천 | **1순위** | 2순위 (일관성 fallback) | GPU 검토 별도 |

**왜 pyannote**:
- 유일하게 CPU 실시간 가능 (0.06x realtime)
- runtime 가장 빠름 (네이티브, no SpeechBrain/wespeaker overhead)
- 라벨링 latency 북극성 (≤ 3s) 통과

**왜 ecapa-tdnn 2순위**:
- sample 간 DER 분산 최저 (0.003) — 운영 환경 일관성 보장
- pyannote 실패 시 fallback

### Decision 2 — scheduler 채택: baseline (diart 기본)

Phase 2 + Phase 2b (legacy wrapper 진짜 측정) 결과:

| scheduler | pyannote avg | ecapa avg | 비고 |
|---|---|---|---|
| **baseline** ⭐ | **0.200** | **0.206** | 채택 |
| decay-A | 0.273 (+7.3pp) | 0.261 (+5.5pp) | 정적 근사 — 악화 |
| decay-B | 0.231 (+3.1pp) | 0.216 (+1.0pp) | 정적 근사 — 소폭 악화 |
| hdbscan-off | 0.200 (±0) | 0.206 (±0) | 대조군 |
| hdbscan-on | 0.196 (−0.4pp) | 0.289 (+8.3pp) | 비일관 |
| **legacy-adaptive** | **0.195 (−0.5pp)** | **0.203 (−0.3pp)** | **legacy 진짜 동적 — 미미 개선** |
| legacy-final | 0.209 (+0.9pp) | 0.306 (+10.0pp) | HDBSCAN 악화 |
| legacy-both | 0.209 (+0.9pp) | 0.306 (+10.0pp) | final 덮어씀 |

**왜 baseline**:
- 8 variant (Phase 2 5 정적 근사 + Phase 2b 3 legacy 동적) 측정 → **어떤 variant 도 ≥ 2pp 개선 못함** (채택 기준 미달)
- legacy-adaptive 가 양 모델 평균 개선한 **유일한 variant** 지만 −0.3~−0.5pp 로 채택 기준 미달
- legacy-final (FinalReclusterer HDBSCAN) 이 ecapa-tdnn 에서 **+10pp 대폭 악화** — embedding 품질 부족 시 HDBSCAN 이 cluster 흐트림 패턴
- legacy v0.1 admin smoke 의 "finalize ≈ online DER" 결과는 v0.2 clean 환경에서 **재현 안 됨** — PLAN-005 boundary 불일치 환경 측정의 신뢰도 부족 확인
- → **wrapper 폐기 결정 (adr-01) 실증 검증 강화** — legacy 직접 측정에서도 baseline 못 이김

### Decision 3 — TitaNet-L 폐기 + wespeaker GPU 검토 별도

| 모델 | 폐기 사유 |
|---|---|
| TitaNet-L (NeMo) | nemo_toolkit 2.7.3 ↔ torch==2.1 충돌, 설치 시 diart 전체 깨짐 |
| WeSpeaker (CPU) | runtime 368s/row (11.5x realtime) — 실시간 운영 불가. **GPU 환경 별도 plan 검토 (best DER 0.176)** |

---

## 북극성 평가

| 지표 | 목표 | 달성 | 평가 |
|---|---|---|---|
| DER | ≤ 0.15 | **0.199** (pyannote 실시간) | ❌ **미달** |
| 초기 cluster latency | ≤ 20s | 2.52s | ✅ 통과 |
| 라벨링 지연 | ≤ 3s | 0.5s (p50) | ✅ 통과 |
| 실시간 처리 | ≤ 1x realtime | 0.06x | ✅ 통과 |

**DER 미달 결론**:
- Phase 1 (embedding × window × step) 한계 영역 도달
- Phase 2 (scheduler) 으로도 미해결
- 후속 가능 방향:
  - (a) **현 수준으로 Phase 3 demo 진행** — 정확도 ~80% 라이브 라벨링은 demo 로 의미 있음
  - (b) **wespeaker GPU 측정** — DER 0.176 → 0.15 근접 가능성. GPU instance 결정 의존
  - (c) **ground truth RTTM 수동 정제** — pyannote 자동 생성 → 명시 검증 → 재측정. record_3 의 높은 DER 부분적 sample 난이도 가능성
  - (d) **embedding 모델 fine-tuning** — 한국어 회의 도메인 특화. 시간 큰 작업

권장: (a) Phase 3 demo 진행 + 병렬로 (b) wespeaker GPU 검토 또는 (c) RTTM 정제.

---

## 발견된 패턴 (재확인)

### 1. step=0.5 압도적 우위

| step | 전 모델 평균 DER |
|---|---|
| 0.1 | ~0.87 (실용 불가) |
| 0.25 | ~0.56 (부분) |
| **0.5** | **~0.20** (실용 가능) |

→ Phase 3 / 후속 ablation 에서도 step=0.5 고정.

### 2. window=2.0 최적

전 모델 공통. 1초는 정보 부족, 3~5초는 over-smoothing.

### 3. record_3 DER 전반 높음 (~0.05~0.12 차이)

원인 후보 (검증 미완):
- record_3 (168s) 가 record_1 (277s) 보다 짧음 → cluster 형성 시간 부족
- record_3 의 화자 turn-taking 더 빠름 가능성
- pyannote 자동 RTTM 정확도 차이 (record_3 viewer 검토 진행 중)

→ ground truth 정제 + 추가 한국어 sample 확보 시 재측정 권장.

### 4. AdaptiveScheduler / FinalReclusterer 의 실증 효과 부족 (재검증)

- legacy v0.1 admin smoke 시점: "finalize DER 19.73% ≈ online DER 19.40%"
- v0.2 Phase 2: scheduler 5종 ablation 결과 어떤 variant 도 ≥ 2pp 개선 못 함
- → **wrapper (AdaptiveScheduler / FinalReclusterer / OnlineSpeakerClusterer wrapper) 폐기 결정 (adr-01) 검증됨**

---

## 다음 단계

### Phase 3 — demo 구현 (별도 plan, 발주 예정)

| 구성 요소 | 기준 |
|---|---|
| 화자 분리 | diart + pyannote/embedding × w=2.0 s=0.5 baseline |
| STT | ElevenLabs Realtime (legacy v0.1 자산 재활용) |
| 매핑 | diart SpeakerSegment ↔ STT phrase time overlap (legacy v0.1 T-025 패턴) |
| UI | 4-panel grid (legacy v0.1 자산 재활용) |
| **신규 측정** | **실시간 라벨링 latency (per-chunk emit timestamp)** — v0.2 ablation 에 없던 진짜 라이브 측정 |

planning-02 또는 PLAN-V03 신설 (architect 발주).

### 후속 task 후보

| task | 우선순위 | 담당 |
|---|---|---|
| Phase 3 demo plan 신설 (`planning-02-demo.md`) | ★ 즉시 | architect |
| Phase 3 demo 구현 | Phase 3 plan 박힌 후 | evaluator / realtime-api / demo-ui |
| wespeaker GPU 측정 (별도) | 운영 GPU 결정 후 | evaluator |
| record_3 RTTM 수동 정제 | 사용자 검토 후 | admin |
| eval_ablation.py 의 실시간 latency 측정 보강 (StreamingInference hook) | Phase 3 와 같이 | evaluator |

### 폐기 / 보존 정리

**v0.2 에서 채택 X — 폐기 명확**:
- TitaNet-L (NeMo 충돌)
- scheduler 5 variant 중 baseline 외 4종 (개선 효과 없음)
- legacy v0.1 의 speaker_engine wrapper (OnlineSpeakerClusterer wrapper, AdaptiveScheduler, FinalReclusterer, identify_phrase)

**보존**:
- diart 0.9.2 + pyannote.audio 3.1.1 (의존성 stack)
- 3 embedding wrap (`eval/embeddings/`) — Phase 3 에서 pyannote 채택, 다른 2개는 후속 검증용
- 한국어 sample 2개 + RTTM ground truth (`eval/data/korean/`)
- legacy v0.1 자산: ElevenLabs STT 어댑터, ServerVAD, web UI, AudioWorklet, Docker

---

## 산출물 정리

| 분류 | 파일 | 비고 |
|---|---|---|
| INDEX | `eval/ablation/results/INDEX.html` | top-level entry point |
| Phase 1 HTML | `phase1-full-20260522.html` | 72 rows |
| Phase 2 HTML | `phase2-20260522.html` | 20 rows + scheduler 차트 |
| Phase 1 분석 | `retrospective/phase1-analysis.md` + `.html` | 1차 분석 |
| **v0.2 최종** (본 문서) | `retrospective/v02-final.md` | Phase 1 + 2 종합 |
| Raw 데이터 | `eval/ablation/results/all.csv` (93 rows), `*.json` | 누적 |
| 측정 코드 | `scripts/eval_ablation.py`, `render_report.py`, `render_index.py`, `rttm_viewer.py`, `generate_rttm.py` | v0.2 산출 |
| Embedding wrap | `eval/embeddings/` | pyannote/ecapa-tdnn/wespeaker |
| 데이터셋 | `eval/data/korean/` | record_1.wav/.rttm + record_3 |

---

## v0.2 완료 선언

- ✅ Phase 0: 환경 구축
- ✅ Phase 1: embedding × window × step grid 측정 + 분석
- ✅ Phase 2: scheduler ablation 측정 + baseline 채택 결정
- ⏭ Phase 3: demo 구현 — 별도 plan 분리 (다음 단계)
- ⏭ Phase 4: enrollment + 운영 — out of v0.2 scope

**v0.2 ablation study 핵심 산출**:
- 최적 조합 박제 (Phase 3 demo 의 base)
- wrapper 폐기 결정 (adr-01) 실증 검증
- 북극성 미달의 명확한 근거 + 후속 방향 박제
- 재현 가능한 ablation 환경 (코드 + 데이터 + report HTML)
