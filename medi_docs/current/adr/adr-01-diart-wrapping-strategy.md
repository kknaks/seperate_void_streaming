---
id: adr-01
type: adr
title: diart 래핑 전략 — 알고리즘만 import + asyncio wrap
status: accepted
created: 2026-05-14
updated: 2026-05-14
sources:
  - "[[planning-02-speaker-engine]]"
  - "[[reference-08-diart-streaming-structure]]"
tags: [adr, decision, speaker-engine, diart, dependency]
---

# diart 래핑 전략 — 알고리즘만 import + asyncio wrap

## Context

speaker-engine 은 실시간 화자 분리를 위해 streaming-friendly 한 클러스터링 알고리즘이 필요하다. diart 라이브러리는 `SpeakerSegmentation`, `OverlapAwareSpeakerEmbedding`, `OnlineSpeakerClustering` 블록을 제공하며, 이 알고리즘들은 streaming 환경에서 이미 검증되어 있다 [[reference-08-diart-streaming-structure]].

그러나 diart 는 내부적으로 RxPY 기반 `Observable` 파이프라인으로 동작한다. RxPY 를 그대로 노출하면 asyncio 기반 라이브러리와 충돌하며, 외부 사용처에 RxPY 의존이 새어나온다.

v0.3 에서는 diart 의존 없이 pyannote 만으로 자체 래핑하는 전략을 결정했으나, [reference-08] 학습 결과 `OnlineSpeakerClustering` 의 centroid 누적 + τ/ρ/δ 알고리즘과 `OverlapAwareSpeakerEmbedding` 을 자체 구현하면 ~1000줄 추가 + 검증 부담이 생기는 것이 확인되어 v0.4 에서 번복.

## Decision

**diart 통째 의존 폐기. `diart.blocks.{SpeakerSegmentation, OverlapAwareSpeakerEmbedding, OnlineSpeakerClustering}` 블록만 import. RxPY pipeline 은 사용하지 않으며, asyncio 로 우리가 직접 wrap. `diart_adapter.py` 단일 종속점에서 격리.**

구체적으로:
- `SpeakerSegmentation`, `OverlapAwareSpeakerEmbedding`, `OnlineSpeakerClustering` 3개 블록만 import
- `AudioSource`, RxPY `Observable` / `Subject` 는 사용 X
- `diart_adapter.py` 가 3개 블록을 asyncio.Queue 기반 비동기 버퍼로 호출
- 3-tier 라벨 / SpeakerStore / FinalReclusterer / AdaptiveScheduler 는 우리가 직접 구현

## Why

1. **알고리즘 재사용 비용**: `OnlineSpeakerClustering`(centroid 누적 + τ/ρ/δ), `OverlapAwareSpeakerEmbedding` 을 자체 구현하면 ~1000줄 + 정확도 검증 부담 [[reference-08-diart-streaming-structure]].
2. **RxPY 격리 필요**: diart 전체 의존 시 RxPY `Observable` 이 라이브러리 외부로 새어나와 asyncio 기반 사용처와 충돌.
3. **단일 종속점**: `diart_adapter.py` 에서만 diart 를 import 하면 diart 버전업 시 adapter 만 수정.

## Alternatives Considered

| 대안 | 거부 사유 |
|---|---|
| (a) diart 통째 import (RxPY pipeline 포함) | RxPY Observable 이 라이브러리 외부로 새어나옴. asyncio 와 충돌. 사용처가 RxPY 를 알아야 함 |
| (b) 자체 pyannote 래핑 (v0.3 결정, 취소) | `OnlineSpeakerClustering` 등 재구현 ~1000줄 + 독자 검증 부담. 검증된 알고리즘을 굳이 재구현할 이유 없음 |

## Consequences

**긍정**
- diart 의 검증된 알고리즘 그대로 활용 → 구현 리스크 최소화
- RxPY 외부 노출 X → asyncio 사용처와 충돌 없음
- diart 버전업 시 `diart_adapter.py` 만 수정

**부정/중립**
- 의존성 추가: `diart>=0.9`, `pyannote-audio>=4.0`, `torch`
- diart `AudioSource` 사용 불가 — `from_websocket`, `from_file`, `from_microphone` 헬퍼 우리가 유지
- diart 내부 API 변경 시 adapter 수정 필요 (버전 pin 권장)

## Related

- [[planning-02-speaker-engine]] §3.5 diart 래핑 전략
- [[reference-08-diart-streaming-structure]] — OnlineSpeakerClustering 알고리즘 확인
- [[adr-02-pattern-b-fanout-chain]] — diart blocks 출력이 Pattern B 이벤트 체인으로 연결
