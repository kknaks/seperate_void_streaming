---
id: adr-03
type: adr
title: SpeakerStore — Protocol 추상 + env URL backend 선택
status: accepted
created: 2026-05-14
updated: 2026-05-14
sources:
  - "[[planning-02-speaker-engine]]"
  - "[[reference-07-pyannote-embedding-code]]"
tags: [adr, decision, speaker-engine, storage, persistence]
---

# SpeakerStore — Protocol 추상 + env URL backend 선택

## Context

speaker-engine 은 `registered` (사전 등록) / `stored` (세션 내 발견 후 저장) speaker 의 embedding 을 영속화해야 한다. 화자 식별 시 등록된 embedding 과 cosine 유사도를 비교하므로, 실행 환경에 따라 저장 backend 를 교체할 수 있어야 한다 (개발 = 인메모리, 로컬 = SQLite, 프로덕션 = pgvector).

embedding 차원 D 는 모델에 의존한다 (legacy `pyannote/embedding` = 512, community-1 WeSpeaker ResNet34 = 256). 따라서 스키마가 D 를 유연하게 수용해야 한다 [[reference-07-pyannote-embedding-code]].

초기 설계에서는 두 테이블 분리(registered / stored) 또는 DI 주입 방식도 검토했으나 단순화를 이유로 폐기.

## Decision

**`SpeakerStore` Protocol 추상 + `SPEAKER_ENGINE_STORAGE_URL` 환경변수 한 줄로 backend 선택. 단일 `SPEAKER` 테이블에 `origin` 컬럼으로 registered/stored 구분. `model_id` + `embedding_dim` 컬럼으로 D 가변 대응.**

| `SPEAKER_ENGINE_STORAGE_URL` | backend | 비고 |
|---|---|---|
| `postgresql://user:pw@host/db` | pgvector | 프로덕션 |
| `sqlite:///path/to/db.sqlite` | SQLite (sqlite-vec) | 로컬 개발 |
| `memory://` | in-memory dict | default, 테스트 |

테이블 핵심 컬럼:
- `origin`: `"registered"` | `"stored"`
- `embedding_dim`: 저장 시 D 함께 박아 모델 교체 감지
- `model_id`: 같은 `model_id` 끼리만 cosine 매칭 (모델 교체 시 매칭 거절)
- `embeddings`: D-dim vector (복수 샘플 허용)

backend 구현체: `PgvectorStore`, `SqliteVecStore`, `MemoryStore` (default).

## Why

1. **단순성**: env 한 줄 교체로 backend 전환. DI 로 store 인스턴스를 주입하는 것보다 구성 지점이 명확.
2. **D 가변 대응**: `embedding_dim` + `model_id` 컬럼이 모델 교체 시 embedding 혼용을 방지.
3. **단일 테이블**: registered/stored 구분은 `origin` 컬럼으로 충분. 두 테이블이면 promotion(stored → registered) 시 row 이동 쿼리 필요.
4. **Protocol 추상**: 테스트 시 `MemoryStore` 로 교체 용이 → 외부 DB 없이 단위 테스트 가능.

## Alternatives Considered

| 대안 | 거부 사유 |
|---|---|
| (a) 두 테이블 분리 (registered / stored) | UNION 쿼리 복잡도 ↑. promotion 시 row 이동 필요. 단일 테이블 + origin 컬럼이 동일 목적 달성 |
| (b) registered in-memory only | 매 세션 dict 주입 필요. 다중 인스턴스 동기화 불가. 영속화 필요 시 재설계 비용 |
| (c) DI 로 store 인스턴스 주입 | env 한 줄이 더 단순. 사용처가 store 인스턴스 생성 책임을 지지 않아도 됨 |

## Consequences

**긍정**
- 사용처는 env 한 줄로 backend 결정 → 배포 환경 전환 용이
- MemoryStore default 로 테스트 DB 불필요
- model_id 매칭으로 embedding 혼용 방지

**부정/중립**
- D (embedding 차원) 가 모델 의존 → `embedding_dim` 컬럼 필수 관리
- backend별 마이그레이션은 엔진 책임 (`engine.init_storage()`)
- 추가 extras 패키지: `[pgvector]` (asyncpg, pgvector), `[sqlite]` (aiosqlite, sqlite-vec)

## Related

- [[planning-02-speaker-engine]] §5 SpeakerStore, §2 Out of Scope (스키마/마이그레이션은 사용처)
- [[reference-07-pyannote-embedding-code]] — D=512/256 모델 의존 확인
- [[adr-02-pattern-b-fanout-chain]] — SpeakerStore 가 3-tier 라벨 판별에 사용
- [[adr-04-manual-persist-flow]] — `engine.persist()` 가 SpeakerStore.save 호출
