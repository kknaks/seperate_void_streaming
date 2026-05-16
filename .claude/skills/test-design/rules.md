# Test Design Rules

> 스킬이 강제하는 룰셋·정책·금지 사항. SKILL.md (사용자 시점 진입점) 가 trigger 시 로드 → 본 rules.md 는 실제 룰 적용 시점에 지연 로드 ([[adr-0007-skill-authoring-rules]] §1).
>
> **rules.md 의 책임 (본질·SSOT)**: *무엇을 강제하는가 / 왜 / 위반 시 어떻게 되는가*. 도메인 룰 본문·정책·금지·예외 처리. 운영 단계 (Pre-flight / Action / Post-flight 표) 는 `checklist.md` 가 SSOT — rules 에는 박지 않음 ([[adr-0007-skill-authoring-rules]] §1 SKILL.md vs rules.md vs checklist.md 분리). 같은 정보가 양쪽에 박히면 표류 — 한쪽만 SSOT.

## 의도 표현 원칙 — *테스트 = 실행 가능한 문서*

테스트는 *무엇을* 검증하는지가 아니라 *왜 그래야 하는지* 를 담는다. 함수명·docstring·assertion 메시지가 모두 비즈니스 규칙의 1차 문서가 되도록 작성.

```python
# ❌ test_create_branch — "무엇만"
# ✅ test_creates_branch_with_auto_generated_slug — "왜·어떻게"
```

명명 규칙: `test_{verb}s_{subject}_{condition}` 패턴 권장 — 동사로 *시스템 동작*, condition 으로 *입력·상태 분기* 표현.

## 3계층 docstring 구조 (강제)

| 계층 | 위치 | 담는 내용 (강제) |
|------|------|------------------|
| 클래스 | `class Test{Action}{Domain}` docstring | **기획 요구사항 박제 6항목** — 목적 / 입력 / 응답 / 에러 케이스 / 비즈니스 규칙 / 처리 흐름 |
| 메서드 | `async def test_*` docstring | **상황·시스템 동작·결과** + Given-When-Then 시나리오 + 검증 사항 목록 |
| 코드 | `# Given / # When / # Then` 주석 | 본문 3구역 명시적 분할 |

**복원 가능성** (강제):
- 클래스 docstring 만 읽어도 *기능 명세 복원 가능* — 6항목 누락 시 기획 의도 유실 신호.
- 메서드 docstring 만 읽어도 *시나리오 의도 전달* — Given-When-Then 누락 시 PR 리뷰어가 코드 다 읽어야 함.
- 코드 `# Given / # When / # Then` 분할 — 본문이 한 덩어리면 "어디까지 셋업이고 어디부터 검증인지" 모호.

## Test Data Builder (Mother) 패턴

- **도메인별 mother fixture (`<entity>_mother`)** — 최소 입력으로 유효한 엔티티 생성, 필드 override 허용.
- **Given 단계에서 mother 호출 1줄 = 셋업 명세 1줄.** 본문은 시나리오에만 집중.
- **연관 엔티티는 mother chain** 으로 표현 (예: branch 가 manager 의존하면 `manager_mother() → branch_mother(manager=...)`).
- mother 의 *기본값 분포* 가 도메인 invariant 를 표현 — 테스트 본문이 default 만 쓰는 건 그 invariant 를 신뢰한다는 뜻.

Mother 파일·클래스 위치는 *프로젝트 의존* — §reference 로드 모델 §A 슬롯 참조.

## 시나리오 4분류 — 커버리지 누락 방지 체크리스트

| 유형 | 본질 (강제 — 4유형 모두 점검) | 예시 |
|------|------------------------------|------|
| Happy Path | 정상 흐름 1개 이상 | `test_creates_resource_successfully` |
| Edge / Error | 입력 부적합·미존재·권한 | `test_rejects_invalid_input`, `test_returns_404_*`, `test_prevents_unauthorized_*` |
| 비즈니스 규칙 | 도메인 제약 | `test_enforces_unique_constraint`, `test_cascades_soft_delete` |
| 상태 전이 | 상태 머신 규칙 | `test_transitions_status_correctly` |

**4유형 모두 점검** 강제 — 각 유형이 0건이면 *왜 0건인지* 리포트 §시나리오 표 에 명시 (해당 도메인이 상태 머신을 안 갖는다 등). 침묵 X.

## 테스트 설계 리포트 포맷

설계 단계 산출물 (구현 *전* 합의용 — TDD 의 "테스트 먼저" 단계의 명세서).

```markdown
## 테스트 설계 리포트

### 대상
- 도메인 / API: {domain} / {endpoint}
- 기획서 출처: {file:line 또는 reference}
- 컨벤션 reference: {로드된 docs/common/*.md 목록 또는 "fallback (role-generic)"}

### 테스트 클래스 구조
class Test{Action}{Domain} 의 docstring 6항목:
- 목적: ...
- 입력: ...
- 응답: ...
- 에러 케이스: ...
- 비즈니스 규칙: ...
- 처리 흐름: ...

### 테스트 시나리오 (총 N개)

| # | 시나리오 (메서드명) | 유형 | Given | When | Then |
|---|---------------------|------|-------|------|------|
| 1 | test_creates_branch_with_auto_generated_slug | Happy | manager_mother | POST /branches (slug 미지정) | 201 + 자동 생성된 slug |
| ... | ... | ... | ... | ... | ... |

4유형 cover 여부:
- Happy: N개
- Edge / Error: N개
- 비즈니스 규칙: N개
- 상태 전이: N개 ({미해당 시 사유})

### 생성할 파일

- `tests/api/test_{domain}.py` — 1 클래스 + N 메서드
- (필요 시) `tests/repository/test_{domain}_repo.py` — 별 클래스

### 필요한 Mother/Fixture

- `{entity}_mother` ({위치 — reference 로드 결과}, 미존재 시 신규)
- `admin_api_client.{sub}` ({위치}, 미존재 시 신규)
- 연관 mother chain: {chain 표현}

### 다음 단계

1. 사용자 합의 (시나리오 표 검토 + 추가/제거)
2. 구현 SKILL 인계 (또는 사용자가 직접 작성)
3. 구현 후 `code-review` SKILL 로 리뷰
```

**필수 요소** (재현 가능성의 핵심):
- 클래스 docstring 6항목 누락 X
- 시나리오 표 4분류 컬럼 누락 X (각 유형 카운트 + 미해당 사유)
- Given/When/Then 컬럼 누락 X (메서드 docstring 의 골격)
- Mother/Fixture 위치 명시 (reference 로드 또는 fallback)

**시나리오 # scope** — *단일 설계 리포트 내 unique* (PR·도메인·세션 누적 X).
- 카운터는 매 설계마다 1부터 새로 시작. 같은 도메인의 두 번째 설계 리포트가 `#1` 을 다시 써도 무관 — 두 리포트는 *별 인스턴스*.
- 시나리오 추적은 *메서드명* (`test_creates_*`) 으로 — 리포트 # 는 리포트 내 정렬용.
- 같은 리포트 내 같은 # 재사용 금지.

## reference 로드 모델

SKILL trigger 시 사용처 프로젝트의 컨벤션·인프라 문서를 우선 로드 — 3 슬롯:

| 우선순위 | 경로 | 슬롯 | 책임 |
|---------|------|------|------|
| 1 | `docs/common/test-data-builders.md` | A. Mother 위치 / 명명 | 도메인별 mother 파일 위치, fixture 명, mother chain 컨벤션 |
| 2 | `docs/common/api-clients.md` | B. API 클라이언트 | API 클라이언트 (`AdminApiClient` 등) + sub-client 명, pytest fixture 명 |
| 3 | `CLAUDE.md` | C. 도메인 어휘 | 엔티티 어휘 / 권한 분기 (HQ vs 지점 등) / 에러 코드 컨벤션 (`{DOMAIN}_{REASON}`) |
| 4 (fallback) | role-generic | A·B·C 모두 | 사용처 테스트 디렉토리 자동 탐색 (Mother) + `{role}_api_client` 추정 (API) + 사용자에게 도메인 어휘 주입 요청 |

**fallback (role-generic)** 의 동작:
- **A. Mother 자동 탐색** — `tests/mothers/` 또는 `tests/factories/` 또는 `tests/fixtures/` 패턴으로 디렉토리 탐색. 없으면 신규 박기 후보로 §생성할 파일 에 명시.
- **B. API 클라이언트 자동 추정** — `{role}_api_client` (예: `backend_api_client`) 또는 `client` fixture 추정. 없으면 신규.
- **C. 도메인 어휘 주입 요청** — 사용자에게 "엔티티 / 권한 / 에러 코드 컨벤션을 주입해 주세요" 명시적 질문. 침묵 후 시나리오 명명 빈약 X.

**충돌 룰** — 두 reference 가 같은 항목을 다르게 정의하면:
1. **우선순위 1번 (`docs/common/test-data-builders.md`) 이 우선** (Mother 컨벤션의 SSOT).
2. 단, 충돌 자체를 *리포트 §대상 §컨벤션 reference* 에 명시 — "Mother 명명: docs/common/test-data-builders.md (`<entity>Mother`) vs CLAUDE.md (`<entity>Factory`), 본 설계는 1번 적용".
3. `CLAUDE.md` 의 어휘만 다르고 Mother 위치는 1번이 권위 — *위치 / 어휘* 분리해서 박는다.

**리포트 출처 강제** — 시나리오·Mother·API 클라이언트 모든 항목은 *어느 reference 의 어느 룰* 인지 박는다:
- `docs/common/test-data-builders.md §Mother chain` 처럼 *파일 + § (섹션)* 까지.
- fallback 만으로 결정한 항목은 `role-generic — {항목}` (예: `role-generic — Mother 자동 탐색 (tests/mothers/ 발견)`).
- 출처 미박힘 = 다음 설계 시 재현 불가.

NEXUS 등 특정 컨벤션은 본 SKILL 본문에 박지 않음 — [[adr-0002-test-design-to-backend]] §자산 분리 룰. 사용 사례 누적 시 분기 ADR + 별도 reference 자산.

## Don't

- 4유형 중 일부 cover 누락 + 사유 침묵 금지 — `상태 전이 0개` 같은 비-cover 는 *왜* 박는다.
- 클래스 docstring 6항목 누락 금지 — 기획 요구사항 박제는 본 SKILL 의 핵심 가치.
- 메서드 docstring 의 Given-When-Then 누락 금지 — 코드 다 읽어야 의도 파악 = 사후 비용 ↑.
- Mother 우회 (테스트마다 raw dict 셋업) 금지 — fixture 가독성 ↓ + 도메인 invariant 흩어짐.
- 시나리오 # 를 PR·도메인·세션 차원 누적 추적용으로 쓰기 금지 (§시나리오 # scope 참조).
- 본 SKILL 본문에 NEXUS / Spring 등 특정 컨벤션 박기 금지 ([[adr-0002-test-design-to-backend]] §자산 분리 룰 §금지).
- 사용자 코드 (테스트 본문) 직접 작성 금지 — 본 SKILL 은 *설계 리포트* 산출만. 작성은 사용자 손 (또는 별 구현 SKILL 인계).
