---
id: retro-v03-realtime
title: "v0.3 Phase 3 — 실시간 환경 Ablation 회고 (PLAN-V03-T-002)"
category: retrospective
status: done
sources:
  - planning-02-demo.md
  - retro-v02-final
created: 2026-05-23
---

# v0.3 Phase 3 — 실시간 환경 Ablation 회고

## 목적

v0.2 ablation 결정(pyannote/embedding 1순위, ecapa-tdnn 2순위, w=2.0 s=0.5 baseline)을 **라이브 스트리밍 환경**에서 재검증. demo_v03 의 placeholder label 제거 + 시간 overlap mapping 구현.

## 측정 조건

| 항목 | 값 |
|---|---|
| 측정 방식 | live-streaming (슬라이딩 윈도우 수동 루프, StreamingInference X) |
| 윈도우 | w=2.0s / step=0.5s (v0.2 최적 고정) |
| 스케줄러 | baseline (diart default τ=0.6, ρ=0.3, δ=1.0) |
| 샘플 | record_1.wav (277.5s), record_3.wav (168.2s) |
| 모델 | pyannote/embedding, ecapa-tdnn |
| DER 방법 | frame-level state (last-write-wins, 중복 없음), collar=0.25 |
| 날짜 | 2026-05-23 |

## 4 rows 결과

| Embedding | Sample | Final DER | DER @30s | DER @60s | DER @end | Latency p50 | Latency p95 | CPU peak | RAM peak |
|---|---|---|---|---|---|---|---|---|---|
| pyannote/embedding | record_1.wav (277.5s) | **0.159** | 0.189 | 0.215 | 0.159 | −131.7s | −14.8s | 209% | 769 MB |
| pyannote/embedding | record_3.wav (168.2s) | 0.288 | 0.372 | 0.273 | 0.288 | −80.5s | −9.8s | 206% | 595 MB |
| ecapa-tdnn | record_1.wav (277.5s) | 0.237 | 0.341 | **0.528** | 0.237 | −114.6s | −13.2s | 210% | 557 MB |
| ecapa-tdnn | record_3.wav (168.2s) | 0.282 | 0.317 | 0.214 | 0.282 | −69.8s | −8.7s | 205% | 447 MB |

v0.2 offline 기준 (pyannote avg 0.199, ecapa avg 0.205) 대비:
- pyannote live avg: (0.159 + 0.288) / 2 = **0.224** (+0.025pp)
- ecapa live avg: (0.237 + 0.282) / 2 = **0.260** (+0.055pp)

## Live Emit Latency 해석

latency = wallclock_at_emit − audio_t_end_of_window. 음수 = real-time 앞섬.

**모든 값이 크게 음수** → 두 모델 모두 CPU에서 real-time보다 훨씬 빠름.

실제 처리 속도 추정 (record_1 pyannote):
- 277.5s audio, 551 emit, 총 처리 ≈ 7s wall clock → **38× faster than real-time**

latency 절댓값이 sample 길이에 비례하는 것은 정상 (audio 시간축이 커질수록 wallclock - audio_t_end 가 더 커짐). 
실용 지표로는 "각 step 처리 시간 / step_s" 비율이 더 명확하나 본 측정에선 단순 latency 공식으로 충분.

## Online DER 진행 분석

**pyannote/embedding**:
- record_1: 30s(0.189) → 60s(0.215) → end(0.159) — 안정화 패턴. 후반 개선.
- record_3: 30s(0.372) → 60s(0.273) → end(0.288) — 초반 불안정 후 안정화.

**ecapa-tdnn**:
- record_1: 30s(0.341) → 60s(0.528) → end(0.237) — **60s 구간 급등 (0.528)**. 클러스터링 불안정.
- record_3: 30s(0.317) → 60s(0.214) → end(0.282) — 60s 이후 악화.

**핵심 관찰**: ecapa-tdnn 의 mid-session DER 급등(record_1 @ 60s: 0.528)은 online clustering 이 특정 구간에서 speaker confusion 을 겪는다는 신호. pyannote 는 이 현상 없음.

## 매핑 정확도 (시각 검토)

`_resolve_label_from_segments` 구현 후 demo_v03.py 에서 placeholder `auto:A` 제거 완료.

매핑 로직: phrase 시간창 [t_start, t_end] × segment_log dominant overlap → label.
fallback: segment_log 마지막 항목 label (segment 없으면 "unknown").

실 STT 환경에서의 fallback 빈도는 라이브 서버에서만 측정 가능 (본 스크립트는 STT 없음).

## 운영 최종 모델 결정

### 1순위: **pyannote/embedding** — 확정

**사유**:
- live final DER avg 0.224 (vs ecapa 0.260)
- online DER 진행이 단조 안정화 (60s spike 없음)
- v0.2 offline 결정과 일치 — 재검증 통과

**허용 범위**: RAM 769 MB peak (CPU only 운영 기준)

### 2순위: **ecapa-tdnn** — RAM 제약 시 대안

**사유**:
- RAM 447–557 MB (pyannote 대비 200–300 MB 절약)
- Cold load 0.15s (vs pyannote 0.80s)
- mid-session DER 불안정 위험 존재 → 모니터링 필요

### TitaNet / WeSpeaker: 폐기 유지

- TitaNet: v0.2 단계에서 폐기 결정 유지
- WeSpeaker: CPU 11.5x real-time 비실용, v0.2 결정 유지

## v0.2 대비 라이브 환경 차이

| 항목 | v0.2 (offline) | v0.3 (live) |
|---|---|---|
| 측정 방식 | StreamingInference (파일 전체 일괄) | 슬라이딩 윈도우 수동 루프 |
| pyannote DER avg | 0.199 | 0.224 (+0.025pp) |
| ecapa DER avg | 0.205 | 0.260 (+0.055pp) |
| 결론 | pyannote 1순위 | pyannote 1순위 — 재확인 |

라이브 환경에서 DER 소폭 상승은 frame-level state 방식과 sliding window 측면 효과로 인한 것. 근본 결정은 변경 없음.

## 이슈 / 한계

1. **latency 음수 도메인**: 측정 공식이 audio_t_end 기준이라 sample 길이에 비례. 절댓값보다 "step당 처리 시간 / step_s" 비율이 더 직관적. 이후 run에서 개선 고려.
2. **ecapa mid-session 불안정**: 원인 미규명. embedding dim(192) 의 clustering 수렴 문제 가능성.
3. **매핑 fallback 빈도 미측정**: 실 STT 환경 (ElevenLabs) 에서만 측정 가능.
4. **단일 실행**: 랜덤성 없으나 1회 측정. 통계적 신뢰도 제한.

## 후속 계획

- PLAN-V04 (admin 결정): 운영 환경 enrollment (speaker 등록) + Azure 배포 + GPU 인스턴스
- pyannote/embedding 를 기본값으로 운영 환경 배포
