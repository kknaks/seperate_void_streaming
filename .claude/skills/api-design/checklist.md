# API Design Checklist

> 운영 체크리스트 — *어떤 순서로* (SSOT). 본질·룰은 `rules.md` SSOT.

## Pre-flight

- [ ] 도메인 식별 (인자 또는 cwd 컨텍스트)
- [ ] 사용처 reference 로드:
  - `plan/api/*.md` 존재 + 같은 도메인 문서 (충돌 점검용)
  - `plan/erd/database-rules.md` + `table-design.md`
  - `CLAUDE.md`
  - 부재 시 → fallback 작동 + 사용자에게 도메인 어휘 주입 요청
- [ ] 충돌 점검 — 두 reference 가 같은 항목 다르게 정의 시 우선순위 낮은 번호 적용 + 보고

## Action — 5 단계

### 1. 충돌 점검
- [ ] 같은 도메인 문서에 동일 endpoint 존재 여부
- [ ] 다른 도메인 문서와 URL/명명 충돌 여부
- [ ] 결과: "충돌 0" 또는 충돌 리스트 + 해소안

### 2. ERD / DB 룰 정합
- [ ] 엔티티 관계 / FK / 필드 타입 부합
- [ ] PK / 소프트 딜리트 / multi-tenancy 컨벤션 적용

### 3. Request 스키마
- [ ] 입력 DTO 박기 — 필드·타입·필수·기본값
- [ ] 검증 룰 (길이·범위·정규식 등)

### 4. Response + 에러
- [ ] 출력 DTO 박기 — 모든 필드 명시
- [ ] 상태 코드별 응답 (200/201/204)
- [ ] 에러 케이스 enum (400/401/403/404/422 + 도메인 에러 코드)

### 5. 도메인 문서 갱신
- [ ] `<api-docs>/<domain>.md` 의 해당 섹션 추가·수정 (사용자 손)
- [ ] Request / Response / Error 표 박기

## Post-flight

- [ ] 작업 보고 — §대상 (도메인·reference 결과·충돌) + §결정 (endpoint 표) + §갱신 파일
- [ ] reference 출처 모든 결정에 박혔는지 확인 (파일 + §)
- [ ] 시크릿 마스킹 확인
- [ ] (선택) `/test-design <domain>` 인계 — 시나리오 합의
- [ ] (선택) `/tdd-cycle <domain>` 인계 — Red→Green 진행
