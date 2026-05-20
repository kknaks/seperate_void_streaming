# medi_docs/_map.md

> 갱신 (PLAN-004-T-002 architect, 2026-05-20). V-04 데모 SSOT 3문서 신규: planning-03, spec-06, spec-07. lineage 3 노드 + 4 edges 추가.

_총 20 문서 (planning 3 / plan 1 / spec 7 / policy 0 / adr 8 / runbook 1 / test 0 / release-notes 0 / retrospective 0)_

## 카테고리별

### runbook — 1

- `runbook-01-engine-tuning.md` _(V-01 DER baseline + grid sweep + 한계 박제, 2026-05-19)_

### planning — 3

- `planning-01-consultation-system.md`
- `planning-02-speaker-engine.md`
- `planning-03-demo-v04.md` _(V-04 데모 시나리오, git tag v0.1.0, 2026-05-20)_

### plan — 1

- `plan-01-speaker-engine.md` _(status: ready)_

### adr — 8

- `adr-01-diart-wrapping-strategy.md`
- `adr-02-pattern-b-fanout-chain.md`
- `adr-03-storage-via-env-url.md`
- `adr-04-manual-persist-flow.md`
- `adr-05-ws-race-defaults.md`
- `adr-06-mono-only-v1-multichannel-v2.md`
- `adr-07-helper-scope.md`
- `adr-08-final-recluster-strategy.md`

### spec — 7

- `spec-01-speaker-engine-api.md` _(status: ready, §OQ 2건 박제)_
- `spec-02-speaker-store-schema.md` _(status: ready, §OQ 2건 박제)_
- `spec-03-diart-adapter.md` _(status: ready, §2-1/§2-2 갱신 + §OQ 3건 박제)_
- `spec-04-clustering-algorithms.md` _(status: ready)_
- `spec-05-test-strategy.md` _(status: ready)_
- `spec-06-stt-adapter.md` _(V-04 데모 STT 어댑터 계약, §OQ-06-1 박제, 2026-05-20)_
- `spec-07-demo-ui-protocol.md` _(V-04 데모 WS json schema 정식화, 2026-05-20)_

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

plan-01-speaker-engine (status: ready)
  ← planning-02-speaker-engine (전체 범위/결정)
  ← adr-01 ~ adr-08 (모든 결정 반영)
  ← spec-01-speaker-engine-api (WBS §2 구현 단위 근거)
  ← spec-02-speaker-store-schema (S-01~S-05 Storage phase)
  ← spec-03-diart-adapter (E-01 diart_adapter.py 근거)
  ← spec-04-clustering-algorithms (E-02/E-03/E-04/E-05 구현 단위 근거)
  ← spec-05-test-strategy (T-01/T-02/T-03 + V-01 정책 근거)

spec-04-clustering-algorithms (status: ready)
  ← planning-02-speaker-engine    (§41 3-tier, §43 HDBSCAN, §218 우리 컴포넌트)
  ← spec-01-speaker-engine-api    (§2-1 SpeakerEngine API, §3 SpeakerCandidate)
  ← spec-02-speaker-store-schema  (§4-1 find_match — Identifier 가 호출)
  ← spec-03-diart-adapter         (process_window 출력 — segmentation+embeddings)
  ← adr-01-diart-wrapping-strategy
  ← adr-05-ws-race-defaults       (R3 inline recluster)
  ← adr-08-final-recluster-strategy (HDBSCAN+Hungarian architectural 결정)
  ← reference-07-pyannote-embedding-code (L2 정규화 책임)
  ← reference-08-diart-streaming-structure §5 (OnlineSpeakerClustering 본문)

adr-08-final-recluster-strategy
  ← planning-02-speaker-engine (§5/§43 HDBSCAN 정밀 재정렬, §218/§511 우리 컴포넌트)
  ← spec-01-speaker-engine-api (§3 SpeakerCandidate, §4-3 finalize drain)
  ← adr-01-diart-wrapping-strategy
  ← adr-05-ws-race-defaults (R4 finalize drain 5s)
  ← reference-03-pyannote-audio-overview §77 (hdbscan 의존성)
  ← reference-08-diart-streaming-structure §5
  → spec-04-clustering-algorithms §4.5 (FinalRecluster 정책)
  → spec-05-test-strategy §6 (OQ-08-1 튜닝 워크플로우)

spec-05-test-strategy (status: ready)
  ← planning-02-speaker-engine (§10 DER<15%, §11 검증 절차)
  ← plan-01-speaker-engine (§2 Phase 5 T-01/T-02/T-03, §6 V-01)
  ← spec-01-speaker-engine-api §6 (unit 매핑)
  ← spec-02-speaker-store-schema §3 (live backend)
  ← spec-03-diart-adapter §6 (integration 매핑)
  ← spec-04-clustering-algorithms §6, §OQ-04-1/2 (튜닝 대상)
  ← adr-01-diart-wrapping-strategy (mock 경계)
  ← adr-05-ws-race-defaults (R1~R5 integration 검증)
  ← adr-08-final-recluster-strategy OQ-08-1 (튜닝 대상)

runbook-01-engine-tuning (V-01 closure, 2026-05-19)
  ← planning-02-speaker-engine (§10 DER 목표)
  ← plan-01-speaker-engine (§2 Phase 6 V-01)
  ← spec-05-test-strategy (§3·§6 측정 정책)
  ← spec-04-clustering-algorithms (§OQ-04-1/2 튜닝 대상)
  ← adr-08-final-recluster-strategy (OQ-08-1 튜닝 대상)
  → spec-04-clustering-algorithms §OQ-04-2 (closed)
  → spec-04-clustering-algorithms §OQ-04-1 (deferred)
  → adr-08-final-recluster-strategy OQ-08-1 (deferred)

planning-03-demo-v04 (V-04 데모 시나리오, 2026-05-20)
  ← planning-02-speaker-engine (§3 FastAPI WS 골격, §2 사용처 경계)
  ← adr-06-mono-only-v1-multichannel-v2 (§2 out: 다채널 v0.2, §5 mono only)
  → spec-06-stt-adapter (§5 컴포넌트 경계 — stt-adapter 책임)
  → spec-07-demo-ui-protocol (§5 컴포넌트 경계 — demo-ui + WS 프로토콜)

spec-06-stt-adapter (V-04 STT 어댑터 계약, 2026-05-20)
  ← planning-02-speaker-engine (§2 Out of Scope: STT, §3 Pattern B 통합)
  ← adr-02-pattern-b-fanout-chain (fan-out 결정 인스턴스화)
  ← planning-03-demo-v04 (§5 컴포넌트 경계 — stt-adapter 책임)

spec-07-demo-ui-protocol (V-04 WS json schema, 2026-05-20)
  ← planning-02-speaker-engine (§3 이벤트 2종 정의, §150 FastAPI WS demo)
  ← planning-03-demo-v04 (§3 시나리오, §4 UI 요구사항)
```
