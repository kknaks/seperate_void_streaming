# Example: API Design — NEXUS Backend (reference 로드)

> 사용처가 `plan/api/`, `plan/erd/`, `CLAUDE.md` 보유 → 모든 슬롯 로드한 case. `sample-no-reference.md` 와 짝.

## 트리거

```
/api-design issue
```

## reference 로드 결과

```
plan/api/issues.md             : 로드 (~15 endpoint, request/response 형식)
plan/api/overview.md           : 로드 (페이지네이션, Rate Limiting, 공통 응답)
plan/erd/database-rules.md     : 로드 (UUID PK, soft delete, multi-tenancy)
plan/erd/table-design.md       : 로드 (BaseEntity + Mixin)
CLAUDE.md                      : 로드 (Repository 룰, 도메인 어휘)
→ 5/5 reference 로드. 충돌 없음.
```

## 출력

````markdown
## API Design 작업 보고

### 대상
- 도메인: `issue`
- reference: `plan/api/issues.md`, `plan/api/overview.md`, `plan/erd/database-rules.md`, `plan/erd/table-design.md`, `CLAUDE.md` (5/5. 충돌 없음.)

### 1. 충돌 점검
- 기존 `plan/api/issues.md` §issues 섹션과 비교 — 신규 endpoint `POST /issues/{id}/forward` 추가 시 동일 path 없음 ✓

### 2. ERD / DB 룰
- 출처: `plan/erd/database-rules.md §multi-tenancy` (company_id 자동 필터) + `§soft-delete` (deleted_at)
- 출처: `plan/erd/table-design.md §BaseEntity` (id UUID / created_at / updated_at / deleted_at)

### 3-4. Endpoint 설계

| Method | Path | Request | Response | Error |
|--------|------|---------|----------|-------|
| POST | `/issues/{id}/forward` | `{target_user_id, reason?}` | 200 + Issue | 404 (issue/user), 403 (권한), 422 (이미 완료) |

### 5. 도메인 문서 갱신
- 위치: `plan/api/issues.md §forward` 신규 추가 (사용자 손)
- 형식: `plan/api/overview.md` 의 Request/Response/Error 표 컨벤션 그대로

### 다음 단계
1. `/test-design issue` — 4 시나리오 분류 cover (forward happy / 권한 없음 / 이미 완료 / 사용자 부재)
2. `/tdd-cycle issue` — Red 시작 (`tests/api/test_issue.py` 기존 클래스에 메서드 추가)
````

## reference 로드의 가치

`sample-no-reference.md` 와 비교:
- **충돌 점검 자동화** — 기존 도메인 문서가 있어 endpoint 중복 즉시 검출
- **DB 룰 명시 출처** — `plan/erd/database-rules.md §multi-tenancy` 처럼 §까지 박힘
- **도메인 어휘 정확** — 사용자 주입 X, reference 의 어휘 그대로
- **재현 안정성** — 다음 작업 시 같은 reference 로드 → 같은 결정 재현
