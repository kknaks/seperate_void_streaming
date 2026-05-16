---
id: adr-04
type: adr
title: D3-b 수동 매핑 채택 — finalize 후 운영자 persist
status: accepted
created: 2026-05-14
updated: 2026-05-14
sources:
  - "[[planning-02-speaker-engine]]"
tags: [adr, decision, speaker-engine, persistence, workflow]
---

# D3-b 수동 매핑 채택 — finalize 후 운영자 persist

## Context

세션 내에서 `auto:*` 라벨로 추적된 화자를 다음 세션에서도 인식하려면 SpeakerStore 에 저장해야 한다. 저장 시점을 자동(임계값 통과 즉시) vs 수동(운영자 매핑 후 명시 호출)으로 결정해야 했다.

저장 전략을 D3-a/b/c/d 4가지로 검토했으며, 세션 품질과 DB 정확성 관점에서 D3-b (수동 매핑) 를 채택. `finalize()` 는 `SpeakerCandidate` 목록만 반환하고, 사용처가 STT/audio 와 join 후 운영자 매핑(또는 룰) → `engine.persist()` 별도 호출하는 2-step 흐름.

## Decision

**D3-b 수동 매핑 채택. `engine.finalize()` 는 `list[SpeakerCandidate]` 만 반환. 사용처가 운영자 매핑 또는 자동 룰로 매핑 결정 후 `engine.persist([{auto_id, name}])` 를 별도 호출 → `SpeakerStore.save` 로 저장.**

흐름:
1. `await engine.finalize()` → `list[SpeakerCandidate]` 반환 (저장 안 함)
2. 사용처: STT / audio 데이터와 join → 운영자 UI 또는 자동 룰로 매핑 결정
3. `await engine.persist([{"auto_id": "auto:A", "name": "박○○"}])` → `SpeakerStore.save`

규칙:
- `persist()` 는 `finalize()` 이후에만 유효
- persist 하지 않은 `auto:*` 는 다음 세션에서 새 사람으로 인식 (의도된 동작)
- `stored:*` 로 이미 저장된 speaker 는 임계값 이상 유사도이면 자동 재인식

## Why

1. **DB 품질**: 자동 persist 시 잘못 분리된 클러스터도 저장됨 → DB 오염, identity 정정 어려움. 수동 매핑은 검토된 화자만 stored.
2. **책임 명확**: 사용처가 매핑 UI 또는 자동 룰 작성 책임. 엔진은 "누가 발화했는지 알아서 판단하고 저장"하지 않음.
3. **정확성 우선**: 사용자 명시 "수동 매핑 = 책임 명확" — 운영 부담이 있더라도 정확성 우선.

## Alternatives Considered

| 대안 | 거부 사유 |
|---|---|
| (a) D3-a 자동 persist (신뢰도 임계 통과 시 즉시 save) | 잘못 분리된 클러스터도 박힘. DB 오염. identity 정정 어려움 |
| (b) D3-c env 토글 (자동/수동 전환) | 두 경로 유지 비용. 코드 복잡도 ↑. 어느 경로를 기본으로 할지 모호 |
| (c) D3-d 익명 자동 persist + 사후 alias | 사용자 명시 "수동 매핑 = 책임 명확". 익명 row 관리 비용. 오히려 복잡 |

## Consequences

**긍정**
- DB 깨끗: 운영자 검토 거친 화자만 stored
- 엔진 책임 명확: finalize = 후보 목록 반환만
- 사용처가 도메인에 맞는 매핑 로직 자유롭게 구현 가능

**부정/중립**
- persist 안 한 `auto:*` 는 다음 세션에서 새 사람 → 운영자가 매핑을 빠뜨리면 인식 연속성 소실 (의도된 trade-off)
- 사용처가 매핑 UI 또는 자동 룰 작성 필요 (운영 부담)
- `finalize()` 이후에만 `persist()` 유효 → 순서 강제 (잘못된 순서는 에러)

## Related

- [[planning-02-speaker-engine]] §6 Persist 흐름 (D3-b 수동 매핑), §12 결정 D3-b
- [[adr-02-pattern-b-fanout-chain]] — engine.stream() 종료 후 finalize() 호출 흐름
- [[adr-03-storage-via-env-url]] — persist() 가 호출하는 SpeakerStore.save
