# Refactor Layered Checklist

> 운영 체크리스트 — *어떤 순서로* (SSOT). 본질·룰은 `rules.md` SSOT.

## Pre-flight

- [ ] 라우터 식별 (인자)
- [ ] 사용처 reference 로드:
  - `plan/refactor/re*-*.md` (해당 라우터의 진행 상태 확인)
  - `CLAUDE.md` (Repository 룰·import 컨벤션)
  - 사용처 디렉토리 (`<router-dir>` / `<service-dir>` / `<repo-dir>` / `<schema-dir>`)
  - 부재 시 → fallback (프레임워크 자동 추정 + 사용자 확인)
- [ ] 회귀 테스트 baseline — 현재 pass 카운트 측정 (정렬 후 비교용)

## Action — 사전 스캔

- [ ] Router DB 직접 호출 grep
- [ ] Service SQLAlchemy 직접 사용 grep
- [ ] Response DTO 누락 grep
- [ ] 위반 N 카운트 보고

## Action — Schema 정렬

- [ ] `*Request` / `*Response` / `*DTO` 분리
- [ ] ORM 모델 import 제거 (Pydantic 만)
- [ ] Model→Response 변환: `model_validate(obj)` 패턴 박기

## Action — Service 정렬

- [ ] DB 직접 호출 → Repository 위임
- [ ] `data: dict` 파라미터 → Request DTO 로 받기
- [ ] Model 직접 반환 → Response DTO 변환
- [ ] `commit()` 제거 (`flush` 까지만)

## Action — Repository 정렬

- [ ] BaseRepository 재사용 (단순 CRUD 는 상속만)
- [ ] 도메인 쿼리만 확장 메서드로
- [ ] 비즈니스 룰 (상태 전이 등) 제거 → Service 로 이전

## Action — Router 정렬

- [ ] DB 호출 제거 (Service 경유)
- [ ] `response_model=` 모든 endpoint 에 추가
- [ ] 라우터 내부 쿼리 헬퍼 → Service 메서드로 이전
- [ ] Repository import 제거

## Action — 사후 검증

- [ ] grep 위반 0 (3 명령 모두)
- [ ] 회귀 테스트 100% pass (baseline 과 비교 — 카운트 동일 또는 ↑)
- [ ] 매 변경 후 *재실행* — fail 시 즉시 revert

## Post-flight

- [ ] 작업 보고 — §대상 (라우터·reference 결과) + §변경 (계층별 수정 파일) + §검증 (사전→사후 위반 N→0 + 테스트 통과)
- [ ] reference 출처 박혔는지 확인 (특히 허용 예외 영역)
- [ ] (선택) `plan/refactor/re*-*.md` 진행 트래커 갱신 (사용자 손)
- [ ] (선택) `/code-review` 인계 — 사후 검토
