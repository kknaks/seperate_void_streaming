---
id: plan-V02-003
type: plan
title: PLAN-V02-003 — Phase 2: 시간감쇠 scheduler ablation
status: draft
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[planning-01-ablation-study]]"
  - "[[plan-V02-002]]"
  - "[[spec-01-ablation-grid]]"
  - "[[spec-06-metrics]]"
tags: [plan, v0.2, ablation, phase2, scheduler]
---

# PLAN-V02-003 — Phase 2: 시간감쇠 scheduler ablation

## 한 줄

Phase 1 최적 조합 위에서 시간감쇠 scheduler 4변형 측정 → HTML report → 최종 최적 (embedding, window, step, scheduler) 결정.

## 목표

시간감쇠 scheduler의 실제 DER 개선 효과를 검증하고, 채택/폐기 결정을 데이터로 박제.

## 의존

- PLAN-V02-002 DoD 통과 + phase1-analysis.md 의 최적 조합 결정

## 실행 단위 (step별)

| step | 입력 | 출력 | 검증 | 의존 |
|------|------|------|------|------|
| 003-1 | Phase 1 최적 조합 + scheduler 변형 4종 | 측정 코드 보강 (`eval_ablation.py --schedulers ...`) | mock 1 scheduler × 1 sample smoke 통과 | spec-01 §Phase 2 |
| 003-2 | 003-1 | (Phase 1 최적 × scheduler 4종 × sample N) 측정 JSON | 모든 조합 row 채워짐 | 003-1 |
| 003-3 | 003-2 JSON | HTML report (scheduler 비교) | scheduler 효과 visualization | 003-2 |
| 003-4 | 003-3 + Phase 1 결과 종합 | `retrospective/v02-final.md` 최종 분석 | 최적 (embedding, window, step, scheduler) 결정 박제 | admin |

## step별 상세

### step 003-1: eval_ablation.py scheduler 지원 확장

**목적**: 4종 scheduler를 CLI로 선택 가능하게

scheduler 4종 (spec-01 §Phase 2 기반):

| 변형 ID | 설명 |
|---------|------|
| `baseline` | diart OnlineSpeakerClustering 기본 (감쇠 없음) |
| `decay-a` | initial 매 segment → 점점 매 N segment (시간감쇠 A) |
| `decay-b` | time-windowed recluster (5/15/30/60s 단위) (시간감쇠 B) |
| `hdbscan` | FinalReclusterer (HDBSCAN) on |

smoke: `python scripts/eval_ablation.py --model {best} --window {best} --step {best} --scheduler decay-a --audio eval/data/korean/record_1.wav --dry-run`

### step 003-2: Phase 1 최적 × scheduler 4종 × sample N 측정

```bash
python scripts/eval_ablation.py \
  --models {phase1_best_model} \
  --windows {phase1_best_window} \
  --steps {phase1_best_step} \
  --schedulers baseline decay-a decay-b hdbscan \
  --audio eval/data/ami/*.wav eval/data/korean/*.wav \
  --output results/phase2_scheduler.json
```

완료 기준: `4 scheduler × (4+N) sample` row 모두 채워짐

### step 003-3: scheduler 비교 HTML report

```bash
python scripts/render_report.py \
  --input results/phase2_scheduler.json \
  --output reports/phase2_scheduler.html \
  --compare-by scheduler
```

chart:
- x-axis: scheduler 변형
- y-axis: DER (primary), latency_cluster_s, cpu_peak_pct
- sample별 분산 표시

### step 003-4: 최종 분석 (admin)

`medi_docs/current/retrospective/v02-final.md` 작성:
- Phase 1 + Phase 2 통합 결과 요약
- 최종 최적 조합 결정: (embedding, window, step, scheduler)
- DER vs CPU/RAM trade-off 최종 평가
- scheduler 효과 검증: 채택 or 폐기 근거
- Phase 3 demo plan 발주 여부 결정

## DoD

- [ ] scheduler 4종 측정 완료 (phase2_scheduler.json)
- [ ] HTML report scheduler 비교 (phase2_scheduler.html)
- [ ] v0.2 최종 최적 조합 박제 (v02-final.md)
- [ ] Phase 3 demo plan 발주 여부 결정

## 결과 해석 기준

scheduler 채택 결정 기준:
- DER 개선 ≥ 2pp (phase 1 baseline 대비)
- latency_cluster_s 증가 ≤ 5s (latency 허용 범위 내)
- CPU/RAM 비용 허용 범위 내

## 금지

- Phase 3 demo plan 작성 (Phase 2 결과 + admin 결정 후)
- spec 변경 (이미 박힘)

## 후속 (선택)

Phase 3 demo plan: admin이 Phase 2 결과 기반으로 발주 결정

## 참조

- spec-01: ablation grid + scheduler 정의 §Phase 2
- spec-06: metrics 측정
- PLAN-V02-002: Phase 1 최적 조합 (입력)
