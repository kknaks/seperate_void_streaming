# Example: Refactor Layered — NEXUS Backend (reference 로드)

> NEXUS reference 모두 로드한 case. `sample-no-reference.md` 와 짝.

## 트리거

```
/refactor-layered harness
```

## reference 로드 결과

```
plan/refactor/re6-layered-architecture.md  : 로드 (도메인 진행 트래커 — harness = 미완료)
CLAUDE.md                                   : 로드 (Repository 룰, import 컨벤션)
사용처 디렉토리                              : 명시 — server/app/{routers,services,repositories,schemas}/
허용 예외                                   : seeds/, alembic/, ws_*.py
→ 4/4 로드. 충돌 없음.
```

## 출력

````markdown
## Refactor Layered 작업 보고

### 대상
- 라우터: `harness`
- reference: `plan/refactor/re6-layered-architecture.md` (현재 미완료), `CLAUDE.md`, 사용처 디렉토리 (4/4. 충돌 없음.)

### 사전 스캔
- `server/app/routers/harness.py` DB 직접 호출: 7 (`select(...)`, `db.execute(...)` 라인 12, 34, 56, 78, 91, 102, 145)
- `server/app/services/harness_service.py` SQLAlchemy 직접: 3
- Response DTO 누락: 2 (POST /harness/control, DELETE /harness/{id})

### Schema 정렬
- `server/app/schemas/harness.py` 박기 — `HarnessControlRequest`, `HarnessResponse`, `HarnessListResponse`
- 출처: `CLAUDE.md §Pydantic v2` — `from_attributes=True` 강제
- 라우터 내부 헬퍼 `_resolve_*_slugs()` → Schema 의 `model_validator` 로 이전

### Service 정렬
- `server/app/services/harness_service.py` — 3 건 SQLAlchemy 직접 호출 → `self.repo.*` 위임
- `data: dict` → `HarnessControlRequest` 로 받기
- 트랜잭션 `commit()` 제거 (미들웨어 레벨 트랜잭션에 위임)

### Repository 정렬
- `server/app/repositories/harness.py` — 신규 (BaseRepository[Harness])
- 도메인 쿼리: `list_active_by_company(company_id)` (multi-tenancy 자동 필터 — `plan/erd/database-rules.md §multi-tenancy`)

### Router 정렬
- 7 건 DB 호출 → Service 경유
- `response_model=` 9 endpoint 모두 추가 (2 누락 + 기존 7 명시)
- 라우터 헬퍼 함수 → Service 메서드로 이전 (Schema 검증으로 흡수된 것 외)

### 사후 검증
```bash
grep -n "select\|db\.execute" server/app/routers/harness.py        # → 0 ✓
grep -n "^from sqlalchemy import.*select" server/app/services/harness_service.py  # → 0 ✓
grep -L "response_model=" server/app/routers/harness.py            # → 0 ✓
docker compose exec server uv run pytest tests/api/test_harness.py # → 18 passed (baseline 18) ✓
```

### 진행 트래커 갱신 (사용자 손)
- `plan/refactor/re6-layered-architecture.md` 의 harness 도메인 상태: 미완료 → ✅ 완료

### 다음 단계
1. ✓ Refactor 완료
2. `/code-review server/app/routers/harness.py server/app/services/harness_service.py` — 사후 검토 (NEXUS 컨벤션 점검)
````

## reference 로드의 가치

`sample-no-reference.md` 와 비교:
- **진행 트래커 자동** — `plan/refactor/re6-*.md` 에서 현재 상태 / 갱신 항목 자동 인식
- **multi-tenancy 출처 명시** — `plan/erd/database-rules.md §multi-tenancy` 까지 박힘
- **허용 예외 자동** — `seeds/`, `alembic/`, `ws_*.py` 검출 제외 자동
- **Repository 룰 정확** — `CLAUDE.md §Repository 룰` 의 `get_by_xxx` 금지 자동 적용
