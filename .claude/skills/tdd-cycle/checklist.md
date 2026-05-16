# TDD Cycle Checklist

> 운영 체크리스트 — *어떤 순서로* (SSOT). 본질·룰은 `rules.md` SSOT.

## Pre-flight (모든 단계 공통)

- [ ] 호출 단계 식별 (전체 루프 / red / green / refactor)
- [ ] 사용처 reference 로드:
  - `plan/design-standards/testing-strategy.md`
  - `tests/mothers/` 또는 사용처 fixture 위치
  - `CLAUDE.md`
  - 부재 시 → fallback (pytest 가정 + fixture 명 주입 요청)
- [ ] 직전 단계 산출 확인:
  - Red 시작: api-design + test-design 산출 (endpoint / 시나리오 표) 존재
  - Green 시작: Red 의 fail 테스트 존재
  - Refactor 시작: Green pass 확인

## Action — Red

- [ ] 테스트 파일 박기 (`tests/api/test_<domain>.py` 또는 사용처 위치)
- [ ] 시나리오 표의 메서드명 1:1 매핑
- [ ] request/response 형식 스펙 그대로
- [ ] Mother / fixture 활용 (raw dict 셋업 X)
- [ ] 테스트 실행 → **실패 확인** (통과 시 즉시 revert + 재작성)

## Action — Green

- [ ] Schema 박기 — `*Request` / `*Response` DTO
- [ ] Router 박기 — `response_model=` 강제
- [ ] Service 박기 — 클래스 기반, Repository 조합
- [ ] Repository 박기 — `BaseRepository[Model]` 상속
- [ ] 테스트 실행 → **통과 확인**
- [ ] 회귀 테스트 (관련 도메인 전체) → **통과 확인**

## Action — Refactor

- [ ] 사전 grep 위반 검출 (refactor-layered SKILL 도구 활용)
- [ ] 네이밍 정렬 (도메인 어휘 일관)
- [ ] 중복 제거
- [ ] 4계층 위반 0 정렬
- [ ] *매 변경 후* 테스트 재실행 (fail 시 revert)
- [ ] grep 위반 0 + 회귀 테스트 100% 통과

## Post-flight

- [ ] 작업 보고 — §대상 (도메인·단계·reference 결과) + §변경 (생성·수정 파일) + §검증 (테스트 통과 카운트 + grep 위반 0)
- [ ] reference 출처 박혔는지 확인
- [ ] 시크릿 마스킹 확인
- [ ] (선택) `/code-review <files>` 인계 — 사후 검토
