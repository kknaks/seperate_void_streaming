# TDD Cycle Rules

> 스킬이 강제하는 룰셋. SKILL.md trigger 후 지연 로드 ([[adr-0007-skill-authoring-rules]] §1).
>
> **rules.md 의 책임 (본질·SSOT)**: *무엇을 강제 / 왜 / 위반 시*. 운영 절차는 `checklist.md` SSOT.

## 3 단계 루프

| 단계 | 시간 (가이드) | 본질 (강제) | 산출 |
|------|---------------|-------------|------|
| Red | 20–60분 | 스펙 기반 테스트 작성 → **실패 확인** | 테스트 파일 + fail 출력 |
| Green | 30–120분 | 통과하는 *최소* 구현 (과도 설계 금지) | 4계층 파일 + pass 출력 |
| Refactor | 20–60분 | 통과 유지하면서 정리 | 정리 후 pass 유지 |

**컬럼 구분** — *시간 (가이드)* 가이드라인 / *본질 (강제)* 강제.

**순서 강제**:
- Red 없이 Green 들어가면 *의도 미반영* — 통과해도 의미 없음
- Green 없이 Refactor 들어가면 *회귀 검증 불가*
- 각 단계 시작 전 직전 단계 산출 확인 필수

## Red 단계 — 테스트 작성

**입력**:
- API 스펙 (`/api-design` 의 산출 — endpoint / Request / Response / 에러 케이스)
- 시나리오 표 (`/test-design` 의 산출 — 4 분류 cover)

**작성 규칙**:
- request/response 형식 *스펙 그대로* — 형식 미일치 시 Green 단계에서 false positive
- 시나리오 표의 메서드명 1:1 매핑 — 시나리오 누락 = 테스트 누락
- Mother / Fixture 활용 — raw dict 셋업 금지 (test-design SKILL §Mother 패턴)

**실패 확인 필수** — 통과하면 *반드시 잘못 작성됨* (구현 0 인데 통과 = 의도 미반영). 즉시 revert 후 재작성.

## Green 단계 — 최소 구현

**4 계층 순서 강제** (refactor-layered SKILL §책임표 참조):
1. Schema (Request / Response DTO)
2. Router (response_model 강제)
3. Service (Repository 조합)
4. Repository (BaseRepository 상속)

**과도 설계 금지** — 통과만 시키고 다음 단계 (Refactor) 로. 미래 확장·최적화 금지 (Refactor 또는 별 PR).

**통과 확인**:
- 모든 시나리오 pass
- 회귀 테스트 (관련 도메인 전체) pass

## Refactor 단계 — 정리

**검증 항목**:
- 네이밍 (도메인 어휘 일관)
- 중복 제거
- 책임 분리 (4계층 위반 — refactor-layered SKILL 의 grep 활용)

**매 변경 후 재실행** — 한 번이라도 fail 시 즉시 revert. Refactor 는 *행동 변경 X* 가 본질.

## reference 로드 모델

| 우선순위 | 경로 | 슬롯 |
|---------|------|------|
| 1 | `plan/design-standards/testing-strategy.md` | 테스트 피라미드·케이스 생성·도메인별 핵심 |
| 2 | `tests/mothers/` (사용처) | Mother 패턴·fixture 명 |
| 3 | `CLAUDE.md` | Repository 룰·import 컨벤션 |
| 4 (fallback) | role-generic | pytest 가정·`tests/` 자동 탐색·fixture 명 사용자 주입 요청 |

**fallback 동작**:
- 테스트 명령: `pytest tests/api/test_<domain>.py` (또는 `python -m pytest`)
- fixture 위치: `tests/conftest.py` 또는 `tests/fixtures/` 자동 탐색
- Mother 패턴 미사용 시 Pydantic factory 추정

**충돌 룰** — 우선순위 낮은 번호 우선. 충돌 자체를 작업 보고에 박는다.

## Don't

- 단계 순서 위반 (Red→Green→Refactor 강제).
- Red 통과 — 즉시 revert + 재작성.
- Green 단계 과도 설계 — 통과만 시킬 것.
- Refactor 중 fail — 즉시 revert.
- 본 SKILL 본문에 NEXUS / Spring 등 특정 컨벤션 박기 ([[adr-0004-tdd-cycle-to-backend]]).
- 사용자 코드 직접 작성 — 본 SKILL 은 *절차 안내 + 검증* 만. 실제 코드는 사용자 손.
