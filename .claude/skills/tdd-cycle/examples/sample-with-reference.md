# Example: TDD Cycle — NEXUS Backend (reference 로드)

> NEXUS 컨벤션 reference 모두 로드한 case. `sample-no-reference.md` 와 짝.

## 트리거

```
/tdd-cycle issue
```

## reference 로드 결과

```
plan/design-standards/testing-strategy.md  : 로드 (피라미드, 핵심 맵, fixture 룰)
packages/admin-api/tests/mothers/issue.py  : 로드 (IssueMother)
packages/admin-api/tests/mothers/user.py   : 로드 (UserMother — Mother chain)
CLAUDE.md                                   : 로드 (Repository 룰, import 컨벤션)
→ 4/4 로드. 충돌 없음.
```

## 출력 (Red → Green → Refactor)

````markdown
## TDD Cycle 작업 보고

### 대상
- 도메인: `issue`
- reference: `plan/design-standards/testing-strategy.md`, `packages/admin-api/tests/mothers/{issue,user}.py`, `CLAUDE.md` (4/4. 충돌 없음.)

### Red
파일: `tests/api/test_issue.py` (기존 클래스 `TestForwardIssue` 신규 추가)
- `IssueMother` + `UserMother` chain — `plan/design-standards/testing-strategy.md §Mother chain` 패턴 적용
- `admin_api_client.issues.forward()` (sub-client) — `CLAUDE.md §AdminApiClient` 컨벤션
- 시나리오 4 (forward happy / 권한 없음 / 이미 완료 / target 부재) — 모두 fail 시작 ✓

실행: `docker compose exec server uv run pytest tests/api/test_issue.py::TestForwardIssue` → 4 failed ✓

### Green
수정:
- `server/app/schemas/issue.py` — `IssueForwardRequest`, `IssueResponse` (Pydantic v2)
- `server/app/routers/issue.py` — `POST /issues/{id}/forward` (`response_model=IssueResponse`)
- `server/app/services/issue.py` — `IssueService.forward()` (`UserRepository` + `IssueRepository` 조합)
- `server/app/repositories/issue.py` — `IssueRepository.forward_to(user_id)` 도메인 쿼리 추가

reference 출처:
- multi-tenancy 자동 필터: `plan/erd/database-rules.md §multi-tenancy`
- BaseEntity: `plan/erd/table-design.md §BaseEntity`
- Repository 룰 (`get_by_xxx` 추가 금지): `CLAUDE.md §Repository 룰`

실행: `docker compose exec server uv run pytest tests/api/test_issue.py` → 19 passed (기존 15 + 신규 4)
회귀: 전체 `pytest` → all passed ✓

### Refactor
- 네이밍: `target` → `target_user` (도메인 어휘 일관)
- 중복 제거: `_check_already_completed` 의 분기 → `IssueStatusValidator` 클래스로 추출
- grep 위반 검출:
  - Router DB 직접 호출: 0 (`refactor-layered` SKILL 의 `grep` 명령 적용)
  - Service SQLAlchemy 직접: 0
  - Response DTO 누락: 0

회귀 pass 유지 ✓

### 다음 단계
1. `/code-review server/app/services/issue.py server/app/routers/issue.py` — 사후 검토 (Layer Objects / NEXUS 컨벤션 점검)
````

## reference 로드의 가치

`sample-no-reference.md` 와 비교:
- **Mother chain 정확도** — fallback 의 "Pydantic factory 추정" 대신 실제 NEXUS Mother 클래스 사용
- **검증 출처 명시** — 각 결정에 `plan/erd/database-rules.md §multi-tenancy` 처럼 §까지 박힘
- **회귀 안정성** — `plan/design-standards/testing-strategy.md §핵심 맵` 으로 어떤 도메인 회귀 돌릴지 자동 결정
- **Repository 룰 준수** — `CLAUDE.md §Repository 룰` 의 `get_by_xxx` 금지 자동 적용 (BaseRepository.get_all 재사용)
