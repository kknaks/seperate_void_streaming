---
id: adr-01
type: adr
title: Ablation-centric Project Identity
status: accepted
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[medi_docs/legacy/v0.1-demo/LEGACY_NOTE.md]]"
tags: [adr, v0.2, ablation, architecture]
---

# adr-01 — Ablation-centric Project Identity

## Status

Accepted

## Context

v0.1-demo (PLAN-001~006) 폐기.

- speaker_engine wrapper (OnlineSpeakerClusterer / AdaptiveScheduler / FinalReclusterer / identify_phrase) 의 실증 효과 미미: admin smoke v6~v11 측정 결과
- PLAN-006 STT-driven chain 의 본질 한계: phrase-level embedding ≠ speaker discrimination at conversational durations
- 기존 self-built wrapper 의 복잡도 대비 성능 이득 없음 확인

## Decision

프로젝트 정체성 = **ablation study + 결과 기반 단순 demo**.

- wrapper 폐기, 외부 toolkit (diart + embedding lib) 직접 활용
- 최적 (embedding × window × step × scheduler) 조합 실측 기반 도출
- demo 구현은 ablation 결과 확인 후 결정

## Alternatives

| 대안 | 이유로 기각 |
|------|------------|
| wrapper 개선 지속 | 실증 측정에서 구조적 한계 확인 — 추가 튜닝 대비 이득 낮음 |
| 새 wrapper 즉시 설계 | ablation 없이 설계하면 동일 문제 반복 가능 |
| 외부 SaaS diarization | 자체 최적화 능력 포기 — 연구 목적에 부적합 |

## Consequences

- speaker_engine 슬림화: DiartAdapter / Identifier / storage 외 다 폐기 후보
- 새 plan (PLAN-V02) 의 Phase 0~2 = 실험 측정 중심
- Phase 3 demo 구현은 ablation 결과 기반으로 후속 plan 발주
- Phase 4 enrollment + 운영 = out of v0.2 scope
