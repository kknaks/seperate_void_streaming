---
id: adr-09
type: adr
title: 서버 live grouping layer — STT-화자 매핑 책임을 클라이언트에서 서버로 이전
status: approved
created: 2026-05-21
updated: 2026-05-21
sources:
  - "[[spec-07-demo-ui-protocol]]"
  - "[[planning-03-demo-v04]]"
  - "[[adr-02-pattern-b-fanout-chain]]"
tags: [adr, live-grouping, server, websocket, architecture, labeled-word, final-grouped]
---

# ADR-09 — 서버 live grouping layer: STT-화자 매핑 책임을 클라이언트에서 서버로 이전

## 배경

spec-07 §OQ-07-1 에서 v0.1.0 결정: "클라이언트가 `stt.t_start` 가 `segment` 구간에 포함되는지 직접 판단". PLAN-004 T-014 시연에서 이 결정의 두 가지 문제를 확인:

1. **클라이언트 복잡도**: 스트리밍 중 시간 좌표 매핑 + relabel 소급 갱신 + UI 렌더를 클라이언트가 동시에 처리 — 구현·디버깅 비용 높음.
2. **표시 품질**: engine sliding window 특성상 segment 는 발화 종료 후 1~2초 뒤 도착. 클라이언트가 stt 이벤트와 실시간 결합 시 라벨 없는 텍스트가 오래 노출 — UX 저하.

측정 baseline (PLAN-005, 2026-05-20): streaming raw DER avg 19.40%, finalize DER avg 19.73%. 라이브 즉시 정확 매핑은 본질 불가. 사용자 의도 = 회의 도구 수준 — 1~2초 지연 라벨링이면 충분.

## 결정 (Decision)

**서버 `audio_ws` 핸들러 안에 live grouping layer 를 추가한다.** 클라이언트는 시간 좌표 매핑 로직을 제거한다.

서버 live grouping layer 책임:

```
STT word 도착 (stt is_final=true):
  → pending_words 에 push

engine segment 도착:
  → segment 이벤트 emit (디버깅용 — 클라이언트 UI 표시 X)
  → pending_words 중 [t_start, t_end] 범위 단어 → labeled_word 이벤트 emit + pending 에서 제거

이후 도착 word (segment 이미 커버 구간):
  → 즉시 라벨 attach → labeled_word emit

finalize 완료 후:
  → canonical 라벨 기준 utterance 단위 grouping
  → final_grouped 이벤트 emit (wipe + 재구성용)
```

## Why

- **1~2초 지연 허용 = 서버 처리가 자연스러운 위치**: segment 도착 타이밍이 이미 1~2초 지연을 갖고 있어 서버에서 버퍼링해도 추가 지연 없음.
- **클라이언트 단순화**: UI 는 이벤트 수신 → 표시만. 시간 좌표 매핑 로직 제거.
- **Pattern B 유지 (adr-02)**: fan-out 구조 불변 — live grouping layer 는 두 채널(engine + STT) 결과를 **합성**하는 사용처 계층, 라이브러리(`speaker_engine`) 변경 0.

## Alternatives

| 대안 | 거부 이유 |
|---|---|
| 클라이언트 매핑 유지 (OQ-07-1 v0.1 결정) | T-014 시연에서 복잡도 + UX 문제 확인 — 지속 불가 |
| 서버에서 stt+segment 단일 이벤트 결합 (merge event) | 타임라인 불일치 시 대기 로직 필요 — 복잡도 동일, 유연성 저하 |
| 라이브 매핑 포기 (done 이후에만 표시) | 회의 도구 UX 요건 미달 — 실시간성 상실 |

## Consequences

- 서버 `audio_ws` 핸들러에 `pending_words` 버퍼 + 시간 매칭 로직 추가 (T-002, realtime-api 워커).
- WS 이벤트 5종 → 7종: `labeled_word`, `final_grouped` 신규 추가 (spec-07 §3).
- 클라이언트: 우-중 `segment` 직접 표시 제거 → `labeled_word` 핸들러로 대체 (T-003, demo-ui 워커).
- `engine` / `speaker_engine` 라이브러리 변경 0 — V-01 closed 상태 유지.
- spec-07 §OQ-07-1 resolved (v0.2 대기 철회).
