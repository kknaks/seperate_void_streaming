# Example: Test Design — NEXUS Backend (reference 로드)

> 사용처 프로젝트가 `docs/common/test-data-builders.md` + `docs/common/api-clients.md` + `CLAUDE.md` 보유 → 1번 우선 + 구체 컨벤션 적용 case sample. `sample-no-reference.md` 와 짝.

## 트리거

```
/test-design branch
```

## reference 로드 결과

```
docs/common/test-data-builders.md : 로드 (Mother 위치: packages/admin-api/tests/mothers/{entity}.py, 클래스명: {Entity}Mother)
docs/common/api-clients.md        : 로드 (AdminApiClient + sub-client: admin_api_client.branches, .managers)
CLAUDE.md                         : 로드 (도메인 어휘: branch / manager / customer ... + HQ vs 지점 권한 + 에러 코드 {DOMAIN}_{REASON})
→ 1번 우선 적용. 충돌 항목 없음.
```

## 출력

````markdown
## 테스트 설계 리포트

### 대상
- 도메인 / API: `branch` / `POST /branches`, `GET /branches/{id}`, `PATCH /branches/{id}`
- 기획서 출처: `packages/admin-api/docs/branch.md §1.1-2.3` + `CLAUDE.md §branch 도메인`
- 컨벤션 reference: `docs/common/test-data-builders.md`, `docs/common/api-clients.md`, `CLAUDE.md` (3/3 로드. 충돌 없음.)

### 테스트 클래스 구조

```python
class TestCreateBranch:
    """
    목적: 본사 (HQ) 가 신규 지점을 생성한다
    입력: name (1-50자), manager_id (UUID, 필수), region_code (KR-* 형식)
    응답: 201 + Branch { id, slug, name, manager_id, region_code, status='ACTIVE', created_at }
    에러 케이스:
      - 422 BRANCH_INVALID_INPUT: 입력 형식 위반
      - 404 MANAGER_NOT_FOUND: manager_id 미존재
      - 403 PERMISSION_DENIED_NON_HQ: HQ 외 권한 호출
      - 409 BRANCH_NAME_DUPLICATE: 같은 region_code 내 동일 name 중복
    비즈니스 규칙:
      - slug 자동 생성 (region_code + 일련번호, 예: KR-SEL-001)
      - 생성된 manager 가 이미 다른 branch 매니저이면 거부 (1 manager : 1 branch)
      - region_code 가 KR-* 가 아니면 거부 (현재 한국만 지원)
    처리 흐름:
      1. 권한 검증 (HQ 만)
      2. Validator (L1 형식 → L2 manager_id-region_code 조합 → L3 manager 가용성·name 중복)
      3. slug 생성
      4. save → 201
    """
```

### 테스트 시나리오 (총 9개)

| # | 시나리오 (메서드명) | 유형 | Given | When | Then |
|---|---------------------|------|-------|------|------|
| 1 | test_creates_branch_with_auto_generated_slug | Happy | hq_user, manager_mother (가용) | admin_api_client.branches.create(name, manager, region) | 201 + slug=KR-SEL-001 |
| 2 | test_rejects_invalid_name_length | Edge/Error | hq_user | name 길이 위반 POST | 422 BRANCH_INVALID_INPUT |
| 3 | test_rejects_invalid_region_code | Edge/Error | hq_user | region_code='US-CA' | 422 BRANCH_INVALID_INPUT |
| 4 | test_returns_404_for_nonexistent_manager | Edge/Error | hq_user | 임의 manager_id | 404 MANAGER_NOT_FOUND |
| 5 | test_prevents_unauthorized_non_hq_creation | Edge/Error | branch_manager_user (HQ 아님) | POST | 403 PERMISSION_DENIED_NON_HQ |
| 6 | test_enforces_one_manager_one_branch | 비즈니스 규칙 | manager_mother + 기존 branch (같은 manager) | POST 동일 manager | 409 (manager 중복) |
| 7 | test_enforces_unique_name_within_region | 비즈니스 규칙 | branch_mother(region=KR-SEL, name=강남) | POST 동일 region+name | 409 BRANCH_NAME_DUPLICATE |
| 8 | test_transitions_to_active_status_on_creation | 상태 전이 | hq_user, manager_mother | POST | status=ACTIVE (초기 상태) |
| 9 | test_returns_404_for_soft_deleted_branch_get | 상태 전이 | branch_mother(deleted=True) | GET /branches/{id} | 404 (soft-deleted 노출 X) |

4유형 cover 여부:
- Happy: 1
- Edge / Error: 4
- 비즈니스 규칙: 2
- 상태 전이: 2

### 생성할 파일

- `packages/admin-api/tests/api/test_branch.py` — `TestCreateBranch` (1 클래스 + 9 메서드)
- (별 PR) `test_branch_get.py`, `test_branch_patch.py` — GET/PATCH 흐름

### 필요한 Mother/Fixture

- `branch_mother` ✓ 기존 — `packages/admin-api/tests/mothers/branch_new.py` (`BranchNewMother`. 출처: `docs/common/test-data-builders.md §Mother 위치`)
- `manager_mother` ✓ 기존 — `packages/admin-api/tests/mothers/manager.py` (`ManagerMother`)
- `admin_api_client.branches` ✓ 기존 — `docs/common/api-clients.md §AdminApiClient` (sub-client `branches`)
- `hq_user`, `branch_manager_user` fixture — `CLAUDE.md §권한 분기` 의 HQ vs 지점 권한 어휘 적용. 기존 `tests/fixtures/users.py` 재사용
- 연관 chain: `manager_mother() → branch_mother(manager=...)` (Mother chain — `docs/common/test-data-builders.md §chain`)

### 다음 단계

1. 사용자 합의 — 시나리오 #6, #7 의 에러 코드 컨벤션 확정 (`MANAGER_DUPLICATE` vs `BRANCH_MANAGER_DUPLICATE`)
2. 구현 (테스트 코드 작성)
3. 구현 후 `code-review` SKILL 로 사후 리뷰 — Layer Objects 4객체 / Validator 3계층 / Repository 룰 점검
````

## reference 로드의 가치

`sample-no-reference.md` (fallback) 와 비교하면:
- 시나리오 수 ↑ (6 → 9) — 권한 분기 (HQ vs 지점) / 1 manager : 1 branch / 상태 전이 등 **도메인 어휘 reference 없으면 누락되는 시나리오** 가 추가
- Convention 출처 정밀도 ↑ — `role-generic — Mother 자동 탐색` 대신 `docs/common/test-data-builders.md §Mother 위치` 처럼 *파일 + § (섹션)* 까지 박힘
- Mother chain / sub-client / 에러 코드 컨벤션 (`{DOMAIN}_{REASON}`) 가 *명시 출처* 와 짝 → 다음 설계 시 재현 보장

reference 충돌 시 [`rules.md` §reference 로드 모델 §충돌 룰](../rules.md) 참조 — 우선순위 1번 (`docs/common/test-data-builders.md`) 우선 + 충돌 자체를 §대상 §컨벤션 reference 에 박는다.
