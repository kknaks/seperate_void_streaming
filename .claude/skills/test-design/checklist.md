# Test Design Checklist

> 운영 체크리스트 — *어떤 순서로 무엇을 점검·실행·검증하는가* (SSOT).
> 룰의 본질 (왜 강제되는가) 은 `rules.md` 가 SSOT. 본 checklist 는 *실행 절차* 만 — 룰 본문 중복 박지 않음.
> 운영 점검 항목이 늘어나면 본 파일을, 룰 자체가 늘어나면 `rules.md` 를 갱신.

## Pre-flight

- [ ] 설계 대상 식별 — `/test-design` (마지막 변경 도메인) / `/test-design {domain}` / `/test-design path/to/spec.md` 중 하나
- [ ] 사용처 프로젝트 reference 로드:
  - `docs/common/test-data-builders.md` (Mother 위치·명명) 존재 여부
  - `docs/common/api-clients.md` (API 클라이언트) 존재 여부
  - `CLAUDE.md` (도메인 어휘·권한·에러 코드) 존재 여부
  - 셋 다 없으면 → `rules.md` §reference 로드 모델 §fallback 작동 명시 + 사용자에게 도메인 어휘 주입 요청
- [ ] 기획서·요구사항 문서 식별 (커밋 메시지 / PR 설명 / 별도 spec 파일)
- [ ] 기존 같은 도메인 테스트 파일 스캔 (`tests/api/test_{domain}.py` 등) — 신규 vs 추가 시나리오 판정

## Action — 5요소 합성

### 1. 의도 표현 명명 패턴 결정
- [ ] `test_{verb}s_{subject}_{condition}` 패턴 확인
- [ ] 도메인 어휘 reference 로드 결과 반영 (엔티티 / 권한 / 에러 코드)

### 2. 클래스 docstring 6항목 박기
- [ ] 목적 / 입력 / 응답 / 에러 케이스 / 비즈니스 규칙 / 처리 흐름 모두 작성
- [ ] 미해당 항목은 *왜* 미해당인지 박는다 (침묵 X)

### 3. Mother / Fixture 식별
- [ ] reference 로드 결과로 Mother 위치 결정 (`docs/common/test-data-builders.md` 또는 fallback 자동 탐색)
- [ ] 도메인별 mother 신규 vs 재사용 판정
- [ ] 연관 mother chain 표현 (예: `manager_mother → branch_mother(manager=...)`)
- [ ] API 클라이언트 fixture 식별 (`admin_api_client` 또는 fallback)

### 4. 시나리오 4분류 cover
- [ ] Happy Path 1+ 박음
- [ ] Edge / Error 박음 (입력 부적합·미존재·권한)
- [ ] 비즈니스 규칙 박음 (도메인 제약)
- [ ] 상태 전이 — 도메인이 상태 머신 보유 시 박음, 아니면 *미해당 사유* 명시
- [ ] 각 시나리오의 Given-When-Then 골격 작성

### 5. 리포트 작성
- [ ] §대상 (도메인·기획서 출처·reference 로드 결과)
- [ ] §테스트 클래스 구조 (6항목)
- [ ] §시나리오 표 (#·메서드명·유형·Given·When·Then) — 4유형 카운트 + 미해당 사유
- [ ] §생성할 파일
- [ ] §필요한 Mother/Fixture (위치 + reference 출처)
- [ ] §다음 단계 (사용자 합의 → 구현)

## Post-flight

- [ ] 사용자에게 리포트 전달 — 시나리오 표 검토 합의 받기 (구현 전)
- [ ] 시나리오 # 가 *단일 리포트 내 unique* 인지 확인 (PR·세션 누적 X — `rules.md` §시나리오 # scope)
- [ ] reference 출처 모든 항목에 박혔는지 확인 (Mother 위치 / API 클라이언트 / 도메인 어휘 / fallback 사유)
- [ ] 시크릿 마스킹 확인 (`.env`·token 노출 X)
- [ ] (옵션) 합의 후 구현 → `code-review` SKILL 로 사후 리뷰
