# Refactor Layered Rules

> 스킬이 강제하는 룰셋. SKILL.md trigger 후 지연 로드 ([[adr-0007-skill-authoring-rules]] §1).
>
> **rules.md 의 책임 (본질·SSOT)**: *무엇을 강제 / 왜 / 위반 시*. 운영 절차는 `checklist.md` SSOT.

## 4 계층 책임표

```
Router(HTTP)  →  Service(비즈니스)  →  Repository(DB 접근)  →  Model(ORM)
    ↕ Request/Response DTO        ↕ Internal DTO / ORM 인스턴스
```

| 계층 | 책임 (강제) | 금지 (강제) |
|------|-------------|-------------|
| Router | 경로·메서드·상태코드 / 인증·권한 Depends / DTO 파싱 / Service 호출 / Response DTO 반환 / `response_model=` 강제 | DB 직접 호출 / Repository import / Model 응답 / 라우터 내 쿼리 헬퍼 |
| Schema | `*Request` / `*Response` / `*DTO` (Pydantic v2 등) / Model→Response 변환 (`model_validate`) | ORM 모델 import / Request·Response 클래스 공유 |
| Service | 비즈니스 로직 / 트랜잭션 조율 / Repository 조합 / Request → Response 변환 / `flush` 까지 | DB 직접 호출 / `data: dict` 파라미터 / Model 직접 반환 / `commit()` |
| Repository | `BaseRepository[Model]` 상속 / 도메인 쿼리 확장 / Model 인스턴스 반환 | 비즈니스 룰 (상태 전이·권한 체크) / `commit()` |

## 정렬 절차 (라우터 1 개 단위)

| 단계 | 시간 (가이드) | 본질 (강제) | 검증 |
|------|---------------|-------------|------|
| 사전 스캔 | 5분 | grep 으로 현재 위반 N 카운트 | 위반 N 측정 |
| Schema 정렬 | 10–20분 | Request / Response 분리 / Model→Response 변환 박기 | Schema 의 ORM import 0 |
| Service 정렬 | 20–60분 | DB 접근 → Repository 위임 / `data: dict` → DTO | Service 의 select / db.execute 0 |
| Repository 정렬 | 10–30분 | BaseRepository 재사용 / 도메인 쿼리만 추가 | 비즈니스 룰 0 |
| Router 정렬 | 10–20분 | DB 호출 제거 / `response_model=` 추가 / 헬퍼 → Service | Router 의 select / db.execute 0 |
| 사후 검증 | 5분 | grep 위반 0 + 회귀 테스트 100% | 0 violation + all green |

**컬럼 구분** — *시간 (가이드)* 가이드라인 / *본질 (강제)* 강제.

**순서 권장** — Schema → Service → Repository → Router. Schema 가 *데이터 계약* 이라 가장 먼저 박혀야 다음 계층이 명확. Router 는 *어댑터* 라 마지막 (다른 계층 정리되면 자연 정렬).

## grep 기반 위반 검출

각 계층 정렬 끝에서 검증. 위반 0 = 4 계층 정렬 통과.

```bash
# Router 의 DB 직접 호출
grep -n "select\|db\.execute\|db\.add\|db\.flush" {router-dir}/<router>.py

# Service 의 SQLAlchemy / ORM 직접 사용
grep -n "^from sqlalchemy import.*select\|await db\.execute\|db\.add(\|db\.flush(" {service-dir}/<service>.py

# Response DTO 누락 검출
grep -L "response_model=" {router-dir}/<router>.py
```

자동화 가능한 checklist — CI 후크 또는 PreToolUse hook 으로 박을 수 있음 (follow-up).

## reference 로드 모델

| 우선순위 | 경로 | 슬롯 |
|---------|------|------|
| 1 | `plan/refactor/re*-*.md` | 도메인별 4 계층 정렬 진행 트래커 |
| 2 | `CLAUDE.md` | Repository 룰 / import 컨벤션 / 4계층 책임 |
| 3 | 사용처 `<router-dir>` / `<service-dir>` 등 | 디렉토리 위치 (자동 탐색) |
| 4 (fallback) | role-generic | 프레임워크 자동 추정 (Spring / Express / NestJS / FastAPI / Django REST) + 사용자 확인 |

**fallback 동작**:
- FastAPI: `app/{routers,services,repositories,schemas}/`
- Spring Boot: `controller/service/repository/entity`
- Express: `routes/services/dao/models`
- NestJS: `<module>.controller.ts / .service.ts / ...`
- 자동 탐색 후 사용자 확인 필수

**충돌 룰** — 우선순위 낮은 번호 우선. 충돌 자체를 작업 보고에 박는다.

## 허용 예외

다음 영역은 4 계층 위반 검출 *제외* (사용처에서 명시):
- 시드 스크립트 (DB 직접 조작 허용)
- 마이그레이션 (ORM 우회 가능)
- WebSocket 핸들러 (Service 위임하되 메시지 파싱·전송은 핸들러)

사용처별 예외 영역은 reference 의 §허용 예외 또는 `CLAUDE.md` 에 명시.

## Don't

- 4 계층 가정이 *모든 사용처* 에 적용 X — hexagonal / clean architecture 변형은 분기 ADR 후보 (NEXUS 외 사용처에서 발견 시 분기 또는 fallback 안내).
- grep 위반 0 *없이* Refactor 단계 종료 — 위반 남기면 회귀 위험.
- 회귀 테스트 fail 상태에서 정렬 진행 — 즉시 revert.
- 본 SKILL 본문에 NEXUS 디렉토리 위치 박기 ([[adr-0005-refactor-layered-to-backend]] §자산 분리).
- 사용자 코드 직접 수정 — 본 SKILL 은 *위반 검출 + 정렬 가이드* 만.
