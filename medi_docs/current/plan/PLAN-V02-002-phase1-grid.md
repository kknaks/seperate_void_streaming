---
id: plan-V02-002
type: plan
title: PLAN-V02-002 — Phase 1: embedding × window grid 실행
status: draft
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[planning-01-ablation-study]]"
  - "[[plan-V02-001]]"
  - "[[spec-01-ablation-grid]]"
  - "[[spec-06-metrics]]"
tags: [plan, v0.2, ablation, phase1, grid]
---

# PLAN-V02-002 — Phase 1: embedding × window grid 실행

## 한 줄

48 조합(4 embedding × 4 window × 3 step) × sample N개 전체 측정 → HTML report 2종 → 최적 후보 3~5개 선정.

## 목표

Phase 2 scheduler ablation의 기반이 될 최적 (embedding, window, step) 조합을 실험으로 결정.

## 의존

- PLAN-V02-001 DoD 통과 (e2e smoke 성공)

## 실행 단위 (step별)

| step | 입력 | 출력 | 검증 | 의존 |
|------|------|------|------|------|
| 002-1 | Phase 0 산출 + record_1.wav | sample 1개 × 48 조합 JSON | 48 row 모두 채워짐 | PLAN-V02-001 |
| 002-2 | 002-1 JSON | HTML report (1차 pilot) | 모든 chart 렌더 + 상위 3~5 후보 식별 | PLAN-V02-001 |
| 002-3 | 002-2 + 상위 후보 | AMI 4 session + 한국어 N sample × 후보 측정 | cross-sample variance 측정 완료 | 002-2 |
| 002-4 | 002-3 JSON | HTML report (cross-sample validation) | chart 렌더 + 최적 1~3개 후보 확정 | 002-3 |
| 002-5 | 002-4 | `retrospective/phase1-analysis.md` 분석 보고서 | 최적 조합 결정 박제 | admin |

## step별 상세

### step 002-1: pilot 측정 (sample 1개 × 48 조합)

**목적**: 빠른 pilot — record_1.wav 1개로 전 조합 스크린

```bash
python scripts/eval_ablation.py \
  --models pyannote ecapa wespeaker titanet \
  --windows 1.0 2.0 3.0 5.0 \
  --steps 0.1 0.25 0.5 \
  --audio eval/data/korean/record_1.wav \
  --output results/phase1_pilot.json
```

완료 기준: `wc -l results/phase1_pilot.json` == 48 row

### step 002-2: 1차 pilot HTML report

```bash
python scripts/render_report.py \
  --input results/phase1_pilot.json \
  --output reports/phase1_pilot.html
```

chart 확인 → DER 기준 상위 3~5 조합 식별 → admin 합의

**선정 기준**: DER ≤ 20% + CPU_peak ≤ 80% + cold_load_s ≤ 10s

### step 002-3: cross-sample validation (후보 × AMI 4 + 한국어 N)

**목적**: pilot 상위 후보의 sample 간 분산 확인

```bash
python scripts/eval_ablation.py \
  --models {후보 목록} \
  --windows {후보 목록} \
  --steps {후보 목록} \
  --audio eval/data/ami/*.wav eval/data/korean/*.wav \
  --output results/phase1_validation.json
```

### step 002-4: cross-sample validation HTML report

```bash
python scripts/render_report.py \
  --input results/phase1_validation.json \
  --output reports/phase1_validation.html
```

chart 확인 → 최적 1~3개 후보 확정 → admin 최종 결정

### step 002-5: 분석 보고서 (admin)

`medi_docs/current/retrospective/phase1-analysis.md` 작성:
- 실험 결과 요약
- 최적 조합 결정 (embedding, window, step)
- trade-off 분석 (DER vs CPU/RAM cost)
- Phase 2 scheduler ablation 기반으로 채택할 조합

## DoD

- [ ] 48 × 1 sample pilot 측정 완료 (phase1_pilot.json)
- [ ] HTML report 1차 pilot (phase1_pilot.html)
- [ ] 후보 × (4+N) sample cross-sample 측정 완료 (phase1_validation.json)
- [ ] HTML report cross-sample validation (phase1_validation.html)
- [ ] Phase 1 최적 조합 (1~3개) 박제 (phase1-analysis.md)

## 예상 소요

- step 002-1: CPU 기준 48조합 × ~4min = ~3시간 (병렬 가능 시 단축)
- step 002-3: 후보 5개 × (4+N) sample = 가변

## 금지

- Phase 2 scheduler 측정 (→ PLAN-V02-003)
- 최적 조합 임의 결정 (admin 합의 필수, step 002-5)

## 후속 plan

→ PLAN-V02-003-phase2-scheduler.md (Phase 2 scheduler ablation)

## 참조

- spec-01: ablation grid schema (48 조합 정의)
- spec-06: metrics 측정 방법
- PLAN-V02-001: Phase 0 (eval 인프라)
