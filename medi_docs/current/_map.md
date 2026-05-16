# medi_docs/_map.md

> 갱신 (PLAN-002-T-008, 2026-05-14). plan-01 신규 추가. planning-02 §13 plan-01 반영.

_총 13 문서 (planning 2 / plan 1 / spec 3 / policy 0 / adr 7 / runbook 0 / test 0 / release-notes 0 / retrospective 0)_

## 카테고리별

### planning — 2

- `planning-01-consultation-system.md`
- `planning-02-speaker-engine.md`

### plan — 1

- `plan-01-speaker-engine.md` _(status: draft)_

### adr — 7

- `adr-01-diart-wrapping-strategy.md`
- `adr-02-pattern-b-fanout-chain.md`
- `adr-03-storage-via-env-url.md`
- `adr-04-manual-persist-flow.md`
- `adr-05-ws-race-defaults.md`
- `adr-06-mono-only-v1-multichannel-v2.md`
- `adr-07-helper-scope.md`

### spec — 3

- `spec-01-speaker-engine-api.md` _(status: ready)_
- `spec-02-speaker-store-schema.md`
- `spec-03-diart-adapter.md` _(status: ready)_

## lineage 요약

```
planning-02-speaker-engine
  ← adr-01-diart-wrapping-strategy   (§3.5 diart 래핑 전략)
  ← adr-02-pattern-b-fanout-chain    (§1/§3 Pattern B + 2종 이벤트)
  ← adr-03-storage-via-env-url       (§5 SpeakerStore env URL)
  ← adr-04-manual-persist-flow       (§6 D3-b 수동 매핑)
  ← adr-05-ws-race-defaults          (§8 WS Race R1~R5 default 정책)
  ← adr-06-mono-only-v1-multichannel-v2 (§7 mono 강제 + v2 로드맵)
  ← spec-01-speaker-engine-api       (§7 Engine API 구현 명세)
  ← spec-02-speaker-store-schema     (§5 SpeakerStore DDL 구현 명세)
  ← spec-03-diart-adapter            (§3.5 diart 래핑 구현 명세)

spec-01-speaker-engine-api (status: ready)
  ← planning-02-speaker-engine
  ← adr-02-pattern-b-fanout-chain
  ← adr-04-manual-persist-flow
  ← adr-05-ws-race-defaults          (R1~R5 정책 반영)
  ← adr-06-mono-only-v1-multichannel-v2 (mono 강제 + 헬퍼 전처리 책임)
  ← adr-07-helper-scope              (헬퍼 3종 시그니처 + device 인자 + 예외 정책)
  → spec-02-speaker-store-schema     (persist → SpeakerStore.save 호출)
  → spec-03-diart-adapter            (stream → DiartAdapter.process_window 호출)

spec-02-speaker-store-schema
  ← planning-02-speaker-engine
  ← adr-03-storage-via-env-url
  ← reference-07-pyannote-embedding-code

spec-03-diart-adapter (status: ready)
  ← planning-02-speaker-engine
  ← adr-01-diart-wrapping-strategy
  ← adr-05-ws-race-defaults          (R3 동기 inline, R5 단일 출력 큐)
  ← reference-04-pyannote-audio-inference
  ← reference-08-diart-streaming-structure

adr-05-ws-race-defaults
  ← planning-02-speaker-engine (§8)
  ← spec-01-speaker-engine-api (§5 예외 처리)
  → adr-02-pattern-b-fanout-chain (단일 출력 큐 — R5 전제)

adr-06-mono-only-v1-multichannel-v2
  ← planning-02-speaker-engine (§7, §10)
  ← reference-01-pyannote-segmentation-3 (mono 학습 한계)
  → adr-01-diart-wrapping-strategy (multi-channel 도입 시 충돌 영역)
  → adr-07-helper-scope           (헬퍼 범위 결정의 전제 — mono 강제 + 사용처 전처리)

adr-07-helper-scope
  ← planning-02-speaker-engine (§7 멀티채널 시나리오)
  ← spec-01-speaker-engine-api (§2 헬퍼 시그니처 명세)
  ← adr-06-mono-only-v1-multichannel-v2 (v1 mono 강제 결정의 후속)

plan-01-speaker-engine
  ← planning-02-speaker-engine (전체 범위/결정)
  ← adr-01 ~ adr-07 (모든 결정 반영)
  ← spec-01-speaker-engine-api (WBS §2 구현 단위 근거)
  ← spec-02-speaker-store-schema (S-01~S-05 Storage phase)
  ← spec-03-diart-adapter (E-01 diart_adapter.py 근거)
```
