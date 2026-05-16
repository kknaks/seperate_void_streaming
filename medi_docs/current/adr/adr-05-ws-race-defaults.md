---
id: adr-05
type: adr
title: WS Race 5종 Default 정책
status: accepted
created: 2026-05-14
updated: 2026-05-14
sources:
  - "[[planning-02-speaker-engine]]"
  - "[[spec-01-speaker-engine-api]]"
tags: [adr, decision, speaker-engine, concurrency, race-condition]
---

# WS Race 5종 Default 정책

## Context

`speaker_engine` 은 WebSocket 수신 루프(Task 1) + engine.stream 처리(Task 2) + event fanout(Task 3) 를 asyncio 로 병렬 구동한다. 이 구조에서 발생 가능한 5종의 race / 경쟁 상태에 대해 default 동작을 명시하지 않으면 구현체마다 결과가 달라져 사용처가 동작을 가정할 수 없다.

[[planning-02-speaker-engine]] §8 에서 5종 race 가 식별되었고, [[spec-01-speaker-engine-api]] §5 에서 예외 처리 계약이 참조된다.

## Decision

**WS race 5종 default 정책 묶음을 다음과 같이 확정한다.**

| 번호 | 상황 | 정책 |
|---|---|---|
| R1 | `audio_queue` overflow | **backpressure** (`queue.put` await — 큐 용량 초과 시 WS recv 일시 중단) |
| R2 | `engine.stream()` 2회 진입 | **`RuntimeError` 즉시 raise** |
| R3 | recluster 발생 시점 | **동기 inline** (process loop 내 실행, yield 지연으로 흡수) |
| R4 | `finalize()` 도중 in-flight 이벤트 | **drain + 5s timeout** (timeout 초과 시 경고 로그 + 강제 반환) |
| R5 | `LabelChange` 순서 | **엔진 보장** (단일 출력 큐 자연 동기화, 사용처 정렬 불필요) |

## Why

- **R1 (backpressure)**: drop-oldest 시 chunk 손실 → STT/engine 시간축 어긋남 + fan-out 동기화 파괴. 무제한 큐는 메모리 폭발. backpressure 는 TCP 흐름 제어와 자연히 cascade — client 도 slow되어 시스템 전체 안정.
- **R2 (RuntimeError)**: engine 1 instance = session 1 모델 강제. 두 세션이 필요하면 두 인스턴스. 큐잉(대기)은 세션 경계를 모호하게 만들어 SpeakerStore 오염 위험.
- **R3 (동기 inline)**: recluster 를 별도 비동기 task 로 분기하면 stream 흐름과의 동기화 복잡도 폭발. 발화 1000개 이하에서는 동기 inline latency 가 허용 범위 내. 1000+ 누적 시 v2 검토 트리거.
- **R4 (drain + 5s timeout)**: 즉시 종료 시 in-flight 이벤트 유실 → DB 불일치. drain 으로 데이터 손실 0. timeout 은 hung 방지 안전망.
- **R5 (엔진 보장)**: 사용처가 `LabelChange` 의 `affected_utterance_ids` 와 이미 yield 된 `SpeakerSegment` 를 매칭할 때 순서 일관성이 전제. 단일 출력 큐 통과로 자연 보장 — 사용처 추가 정렬 로직 불필요.

## Alternatives Considered

| 대안 | 거부 사유 |
|---|---|
| R1: drop oldest | chunk 손실 → STT/engine 시간축 어긋남, fan-out 동기화 파괴 |
| R1: 무제한 큐 | 장시간 세션 메모리 폭발 |
| R2: 큐잉(대기) | 두 세션 인스턴스 분리가 자연스럽고 안전. 큐잉은 SpeakerStore 오염 위험 |
| R3: 비동기 task + label swap | 단순화 우선. 1000+ 발화 시 v2 재검토 예약 |
| R4: 즉시 종료 | in-flight 이벤트 유실 → DB 발화 레코드 불일치 |
| R5: 사용처 책임 정렬 | 사용처 부담 증가, 엔진이 단일 큐로 자연 보장 가능한데 책임 전가 불합리 |

## Consequences

**긍정**
- WS recv 자연 backpressure → TCP 흐름 제어와 cascade. 시스템 전체 안정.
- `LabelChange` 순서 보장으로 사용처 DB UPDATE 일관성.
- `finalize()` drain 으로 세션 종료 시 데이터 손실 0.

**부정/중립**
- R1 backpressure: client 도 slow — 느린 client 는 WS recv 지연 체감 가능.
- R3 동기 inline: recluster latency = stream yield 지연. 발화 1000+ 누적 시 stream 지연 가시화.
- R4 timeout 초과 시: 경고 로그 + 일부 in-flight 발화 누락 가능 — 사용처 모니터링 필요.
- engine 1 instance = session 1 제약: 다중 세션 = 다중 인스턴스 + 공유 SpeakerStore 패턴 강제.

## Related

- [[planning-02-speaker-engine]] §8 WS Race 정책
- [[spec-01-speaker-engine-api]] §5 예외 처리 계약
- [[adr-02-pattern-b-fanout-chain]] — 단일 출력 큐 구조의 근거 (R5 전제)
