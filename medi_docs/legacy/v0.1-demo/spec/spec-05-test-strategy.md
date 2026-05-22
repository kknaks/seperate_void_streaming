---
id: spec-05
type: spec
title: Test Strategy 정책 명세 — 카테고리 / DER 베이스라인 / fixture / CI / 임계값 튜닝
status: ready
created: 2026-05-17
updated: 2026-05-17
sources:
  - "[[planning-02-speaker-engine]]"
  - "[[plan-01-speaker-engine]]"
  - "[[spec-01-speaker-engine-api]]"
  - "[[spec-02-speaker-store-schema]]"
  - "[[spec-03-diart-adapter]]"
  - "[[spec-04-clustering-algorithms]]"
  - "[[adr-01-diart-wrapping-strategy]]"
  - "[[adr-05-ws-race-defaults]]"
  - "[[adr-08-final-recluster-strategy]]"
tags: [spec, speaker-engine, test, der, fixture, ci, tuning, ready]
---

# Test Strategy 정책 명세

## Summary

`speaker_engine` v1 의 **테스트 카테고리 책임 분담 / DER 베이스라인 측정 / fixture 정책 / CI 통합 / 도메인 임계값 튜닝 워크플로우** 를 박제. plan-01 §2 Phase 5 (T-01/T-02/T-03) 및 §6 V-01 의 정책 빈자리를 채운다. 구체 테스트 함수명·fixture 파일명·pytest marker 명·conftest 구조 등은 구현 단계 결정 — 본 spec 은 정책과 외부 인터페이스 경계만 박는다.

---

## §1 Scope

### in scope (정책 결정)

- 테스트 3 카테고리 (unit / integration / live) 의 경계와 책임 분담
- 컴포넌트별 검증 카테고리 매핑
- e2e / WS Race / 외부 의존 (DB·HF Hub) 의 위치 정책
- DER 베이스라인 측정 도구·dataset·목표값·시점·회귀 정책
- fixture 정책 (embedding/audio 합성 vs 실, mock 경계, fixture 위치)
- CI 통합 정책 (PR 게이트 / nightly / live / HF secret / 실패 처리)
- 도메인 임계값 튜닝 워크플로우 (`spec-04 §OQ-04-1/2`, `adr-08 OQ-08-1` 해결)

### 구현 단계 결정 (본 spec 에 박지 않음)

- 테스트 함수명 / 함수 분할 / 클래스 단위
- pytest marker 이름 (예: AMI 정확도 측정 분리용) / conftest fixture 이름
- fixture 파일명 / 디렉토리 세부 구조 (위치 정책만 박음)
- 합성 audio 생성 함수 시그니처
- mock 클래스 / 함수 시그니처
- 다운로드 스크립트 인자 형식

### out of scope (다른 문서)

- 컴포넌트별 검증 *시나리오* 자체 — [[spec-01-speaker-engine-api]] §6, [[spec-03-diart-adapter]] §6, [[spec-04-clustering-algorithms]] §6 의 검증 카테고리 목록
- 튜닝 결과의 default 값 갱신 — 본 spec 의 §5 워크플로우 결과로 spec-04 §4.3-4.5 / adr-08 의 default 값이 갱신됨 (별도 사후 작업)
- 릴리스 / 배포 절차 — `runbook-NN-engine-tuning` (todo), `release-NN-v0.1.0` (todo)

---

## §2 테스트 카테고리 정책

[[plan-01-speaker-engine]] §2 Phase 5 의 3 카테고리 (T-01/T-02/T-03) 위에 책임 분담 + e2e/race 위치 정책을 박제.

### 2-1. 카테고리 경계

| 카테고리 | 포함 기준 | 외부 의존 |
|---|---|---|
| **unit** | 모듈 단위 + 합성 fixture + mock diart | numpy 만 |
| **integration** | e2e stream→finalize + 실 audio fixture + `MemoryStore` + R1~R5 race | 실 diart 모델 + HF Hub cache |
| **live** | 외부 인프라 실 통합 (pgvector DB, HF Hub 다운로드 검증) | docker pgvector / 네트워크 |

### 2-2. 컴포넌트별 검증 카테고리 매핑

| 검증 대상 | unit | integration | live |
|---|---|---|---|
| L2 정규화 강제 로직 (identifier 의 normalize 책임) | ✓ (mock embedding) | — | — |
| 3-tier 매칭 정책 (identifier) | ✓ | — | — |
| Adaptive scheduler 트리거 / 재라벨 정책 | ✓ | — | — |
| HDBSCAN 결과 변환 / Hungarian 매핑 / noise 흡수 | ✓ | — | — |
| `SpeakerEngine.__init__` env 검증 (`HF_TOKEN` / `STORAGE_URL` 누락 → `EnvironmentError`) | ✓ (env mock) | — | — |
| `SpeakerEngine` lifecycle (재진입 RuntimeError, `async with` `__aexit__` finalize 자동 호출) | ✓ (mock source) | — | — |
| `DiartAdapter` API surface (RxPY 외부 노출 없음, `embedding_dim` 등 공개 속성) | ✓ (import + inspect) | — | — |
| `DiartAdapter.process_window` 출력 (실 모델 forward, 출력 L2 norm 검증, D 동적 결정) | ✗ (mock 불가) | ✓ | — |
| `SpeakerEngine.stream` e2e (단일 화자/2화자 분리 + finalize → persist) | — | ✓ | — |
| WS Race R1~R5 정책 | — | ✓ | — |
| HDBSCAN/Hungarian 알고리즘의 실 audio 회귀 (V-01 DER 베이스라인 + AMI fixture) | — | ✓ (`speaker/` PR 게이트) | — |
| `SpeakerStore.find_match` / `save` (pgvector backend) | — | — | ✓ |
| HF Hub 모델 다운로드 / cache 검증 | — | — | ✓ |

원칙: `speaker/` 4 모듈의 *정책 로직* 은 모두 unit 으로 검증 가능 (numpy + 합성 embedding). diart 모델 호출이 필요하면 integration. 외부 인프라가 필요하면 live.

### 2-2-1. L2 정규화 검증의 2종 구분

L2 정규화는 두 곳에서 검증 — 같은 키워드지만 다른 검증 대상이라 카테고리 다름:

| 검증 대상 | 위치 | 카테고리 |
|---|---|---|
| **identifier 가 utterance embedding 단에서 정규화를 강제 수행** | identifier 의 normalize 호출 + zero vector → `ValueError` | unit |
| **DiartAdapter 출력 embedding 의 L2 norm ≈ 1.0** | DiartAdapter forward 후 출력 벡터의 norm 측정 | integration |

전자는 정책 로직 (mock embedding 으로 검증 가능). 후자는 실 모델 출력 행동 검증 (실 forward 호출 필요).

### 2-2-2. spec-01/03/04 §6 시나리오와의 매핑

| 출처 | 카테고리 |
|---|---|
| [[spec-01-speaker-engine-api]] §6 T01/T03/T04/T08/T09/T10 (stream/persist/race/timeout/overlap) | integration |
| [[spec-01-speaker-engine-api]] §6 T02 (registered 인식, mock embedding) | unit |
| [[spec-01-speaker-engine-api]] §6 T05 (재진입 RuntimeError) / T06 (`HF_TOKEN`) / T07 (`STORAGE_URL`) | unit |
| [[spec-03-diart-adapter]] §6 T01~T04, T07~T09 (process_window 동작 + max_speakers 한도 + close lifecycle) | integration |
| [[spec-03-diart-adapter]] §6 T05 (출력 L2 norm) | integration |
| [[spec-03-diart-adapter]] §6 T06 (`HF_TOKEN`) / T10 (RxPY 외부 노출) | unit |
| [[spec-04-clustering-algorithms]] §6 카테고리 (단일/분리/Final/Lock/Noise/max/duration/Hungarian/empty/L2) | 기본 unit. "단일 화자 reliability" / "화자 분리 정확도" 는 V-01 DER 베이스라인 fixture (integration) 에서도 회귀 검증 |

### 2-3. e2e 위치

- e2e (stream → finalize → persist) = **integration** 전용. `MemoryStore` 사용
- live 는 e2e 반복 X. pgvector 단독 find_match / save 만 검증
- 사유: e2e 중복 (memory 와 pgvector 양쪽) 은 코드 비용 ↑ vs 안전성 한계. pgvector 회귀는 backend 단독 검증으로 충분 ([[spec-02-speaker-store-schema]] §3 의 backend 인터페이스 일관성 가정)

### 2-4. R1~R5 race 검증 위치

- WS Race R1~R5 ([[adr-05-ws-race-defaults]]) = **integration** 전용 (e2e 안에서)
- 사유: race 는 본질적으로 asyncio coroutine 다수의 상호작용. unit 단에서 mock 으로 재현하기엔 fidelity 부족. integration 의 실 stream loop 안에서 재현

---

## §3 DER 베이스라인 측정 정책

[[planning-02-speaker-engine]] §10 (DER < 15%) + [[plan-01-speaker-engine]] §6 V-01 의 정책을 박제.

### 3-1. 측정 도구

- **`pyannote.metrics`** (DER + JER) — 사용. pyannote 이 이미 의존성, 추가 비용 0
- 자체 metric 신설 X (도메인 표준 우선)

### 3-2. Dataset

- v1 = **AMI Meeting Corpus 1 session**
- 회의 도메인 (화자 3~5명) 이 의료 회의 시나리오에 근접
- CHiME-6 (노이즈 robustness 검증용) 는 v2 후속
- 의료 도메인 자체 dataset 은 v2 (라벨링 비용 v1 timeline 침해)

### 3-3. 목표값

- **DER < 15%** ([[planning-02-speaker-engine]] §10 박제 유지)
- 단계별 / relative 목표는 도입하지 않음 (v1 단일 절대 임계)
- v2 에 도메인 튜닝 결과로 재논의

### 3-4. 측정 시점

| 시점 | 실행 | 사유 |
|---|---|---|
| **V-01 (베이스라인 박제)** | 1회 grid search + DER 측정 → `runbook-NN-engine-tuning` 박제 | 릴리스 전 도메인 fit |
| **`speaker/` 디렉토리 수정 PR** | 자동 측정 (PR 게이트) | 알고리즘 변경에 대한 회귀 감지 |
| **release 직전** | manual 측정 | 종합 검증 |

일반 PR 의 nightly 자동 측정은 v1 에 없음 (운영 부담 회피). v1.1 후 도입 검토.

### 3-5. 회귀 정책 (v1)

- v1 = **회귀 게이트 없음** — 단일 베이스라인 박제만
- `speaker/` PR 게이트가 DER 측정은 하지만, 임계 기반 block 은 v1 에 없음
- 회귀 임계 (예: +2%p) 는 V-01 후 데이터를 보고 v1.1 에 결정

---

## §4 Fixture 정책

### 4-1. unit embedding fixture

| 용도 | 방식 |
|---|---|
| 기본 검증 (재현성) | seeded random + L2 normalize. seed 박제 (구체 seed 값은 구현 단계 결정) |
| threshold 정밀 검증 | hand-crafted 직교 vector (단위 행렬 + 회전) — cosine 비교 의도 명확 |
| 실 audio 추출 embedding | unit 에선 사용 X — integration 이상에서만 |

### 4-2. Mock 경계

| mock 대상 | 정책 |
|---|---|
| **`DiartAdapter.process_window`** | unit 에서 단일 mock point. 입력 audio bytes 무시, 가짜 (segmentation, embeddings) 반환 |
| diart blocks 개별 (`SpeakerSegmentation` 등) | mock 하지 않음 — `DiartAdapter` 가 통합 가림막 ([[adr-01-diart-wrapping-strategy]] 일관) |
| 실 diart 모델 호출 | unit 에서 호출 안 함 — integration 에서만 |
| `SpeakerStore` | mock 사용 안 함, `MemoryStore` 직접 사용. 호출 횟수 검증이 필요한 unit 만 Protocol mock 한정 |

### 4-3. 통합 audio fixture

| 종류 | 위치 | 용도 |
|---|---|---|
| 합성 ~30s 2화자 (sin/noise) | repo 내장 (`tests/fixtures/` — 정확 위치는 구현 단계) | smoke / CI 기본 |
| AMI 일부 절단 ~30s | `scripts/download_ami.py` (정확 인터페이스는 구현 단계) | 정확도 검증, marker 분리 |

합성 fixture 는 repo size 영향 최소 (<100KB). AMI 는 사용자 다운로드.

### 4-4. Fixture 재현성

- 합성 fixture = repo 내장 (`tests/fixtures/`, 정확 경로는 구현 단계)
- AMI fixture = 다운로드 스크립트로 환경마다 받음. CI 는 cache action 사용
- git LFS / HF Datasets 미사용 (v1 단순화)

---

## §5 CI 통합 정책

### 5-1. PR 게이트

| 카테고리 | PR 게이트 |
|---|---|
| unit | **필수** |
| integration (memory store + 합성 audio smoke) | **필수** |
| integration (AMI accuracy) | `speaker/` 디렉토리 수정 PR 만 자동 |
| live (pgvector) | `storage/` 디렉토리 수정 PR 만 자동 + release 직전 manual |
| live (HF Hub cache) | release 직전 manual |

원칙: 일상 PR cost 최소 + 변경 영역에 따른 자동 게이트.

### 5-2. nightly / scheduled

- v1 = **없음**
- v1.1 부터 nightly AMI accuracy 도입 검토

### 5-3. 외부 의존성

- `HF_TOKEN` = GitHub Secret 으로 주입
- pyannote 모델 = CI cache action 으로 재사용 (다운로드 비용 절감)
- pgvector = `storage/` PR 자동 게이트에서 docker compose 로 spin up (구현 단계 결정)

### 5-4. 실패 정책

- PR 게이트 unit / integration fail = **PR block**
- emergency override / WARN-only 정책 v1 에 없음 — 도입 시 별도 결정

---

## §6 임계값 튜닝 워크플로우

[[spec-04-clustering-algorithms]] §OQ-04-1 / §OQ-04-2 / [[adr-08-final-recluster-strategy]] OQ-08-1 의 도메인 임계값을 V-01 시점에 1회 측정 → default 갱신하는 절차.

### 6-1. 튜닝 시점 / 책임

- **V-01 직후 1회** 실시 (release 전)
- DER 측정과 동일 시점에 grid search 병행
- v1.1+ 의 정기 재튜닝 정책은 v1 안에 없음 — v1 결과 보고 결정

### 6-2. Dataset

- AMI 1 session 을 **발화 단위 train/val 분할** 사용
- train = grid search 임계값 최적화
- val = 보고 (overfitting 회피)
- 분할 비율 / 분할 시드는 `runbook-NN-engine-tuning` 에서 박제

### 6-3. 튜닝 대상 파라미터 + 격자

| 파라미터 | 격자 (v1) | 근거 |
|---|---|---|
| `delta_new` (cosine distance 환산) | 4 값 (구체 값은 runbook) | spec-04 §OQ-04-1 |
| Hungarian cost threshold | 3 값 (구체 값은 runbook) | spec-04 §OQ-04-2 |
| HDBSCAN `cluster_selection_epsilon` | 3 값 (구체 값은 runbook) | adr-08 OQ-08-1 |

- 격자 크기 = 4 × 3 × 3 = 36 조합
- AMI 1 session 1 회 측정 ~수분 × 36 = ~1 night 안에 완료 가능
- 격자 값 자체는 본 spec 박지 않음 (튜닝 데이터 보고 runbook 에서 박제)

### 6-4. 튜닝 방법

- **Grid search** (단순, 재현성)
- Coordinate descent / Bayesian / Optuna 의존성 v1 도입 X
- 구체 grid 실행 script 형식은 구현 단계 결정 (CI 외부에서 실행)

### 6-5. 결정 기준

- **val DER 최소값** 의 조합 = 새 default
- 동률 시 v1 default (보수적 변경 최소화) 유지
- LabelChange 빈도 / 라벨 안정성 같은 추가 weight 는 v1 에 도입 X

### 6-6. 결과 박제 (SOT 갱신 절차)

| 박제 위치 | 갱신 내용 |
|---|---|
| `spec-04 §4.3-4.5` | 새 default 값으로 갱신, §OQ-04-1/2 닫음 |
| `adr-08` Decision 표 | `cluster_selection_epsilon` 값 갱신, OQ-08-1 닫음 |
| `runbook-NN-engine-tuning` (todo) | 격자 표, 측정 raw 결과, train/val 분할 시드, 결정 근거 박제 |

spec/adr 가 default SOT. runbook 이 측정 과정·재현 자료. 한쪽만 갱신은 inconsistent — 양쪽 모두 갱신해야 튜닝 완료.

---

## §7 의존성

| 패키지 | 출처 | 본 spec 의 용도 |
|---|---|---|
| `pyannote.metrics` | pyannote.audio 가 끌어옴 | DER / JER 측정 |
| `pytest` | 코어 dev 의존성 (v1 도입) | 카테고리별 실행 |
| (GH Actions) cache action | CI infra | HF 모델 cache |
| (docker) pgvector image | live 카테고리 인프라 | `storage/pgvector.py` 검증 |

추가 라이브러리 의존성 0 — Optuna / hypothesis / property-based 도구는 v1 도입 X.

---

## §OQ 후속 박제 대상

| ID | 질문 | 해결 시점 |
|---|---|---|
| OQ-05-1 | nightly AMI accuracy 도입 vs 유지 — v1 사용 후 회귀 발견 빈도 보고 결정 | v1.1+ |
| OQ-05-2 | DER 회귀 임계 (예: +2%p block) 의 적정값 | v1.1, V-01 결과 데이터 기반 |
| OQ-05-3 | v1.1+ 정기 재튜닝 주기 (releaes 마다? 분기? annual?) | v1 사용 데이터 보고 결정 |
| OQ-05-4 | 의료 도메인 자체 dataset 준비 — 어느 시점? 라벨링 책임 / 비용 | v2 로드맵 |
| OQ-05-5 | pgvector 외 다른 backend (SQLite VEC, in-memory FAISS 등) 회귀 검증 카테고리 | backend 추가 시점에 결정 |
| OQ-05-6 | 구체 fixture 경로 / pytest marker 이름 / mock 클래스 이름 | **구현 단계 결정** — 본 spec 정책을 만족하는 한 워커 자유도 |

---

## §8 참조

- [[planning-02-speaker-engine]] — §10 (DER < 15%), §11 (검증 절차 5단계)
- [[plan-01-speaker-engine]] — §2 Phase 5 (T-01/T-02/T-03), §6 V-01 (DER 베이스라인), §7 후속 문서 `runbook-NN-engine-tuning`
- [[spec-01-speaker-engine-api]] — §6 검증 시나리오 (unit 매핑 대상)
- [[spec-02-speaker-store-schema]] — §3 backend 인터페이스 (live 검증 대상)
- [[spec-03-diart-adapter]] — §6 검증 시나리오 (integration 매핑 대상)
- [[spec-04-clustering-algorithms]] — §6 검증 카테고리, §OQ-04-1 / OQ-04-2 (튜닝 대상)
- [[adr-01-diart-wrapping-strategy]] — `DiartAdapter` 단일 가림막 (mock 경계 근거)
- [[adr-05-ws-race-defaults]] — R1~R5 race 정책 (integration 검증 대상)
- [[adr-08-final-recluster-strategy]] — OQ-08-1 (튜닝 대상)
