# Example: Code Review — Generic Backend (fallback)

> reference 부재 → role-generic fallback 으로 동작한 case sample.

## 트리거

```
/review src/api/branch_handler.py
```

## reference 로드 결과

```
docs/common/*.md  : 없음 (사용처 프로젝트가 컨벤션 문서 미보유)
CLAUDE.md         : 없음
→ fallback (role-generic) 작동
```

## 출력

````markdown
## Code Review Report

### 맥락
- 대상: `src/api/branch_handler.py`
- 변경 규모: 87 줄 (적정)
- 변경 유형: 새 기능 (지점 생성 API)
- 컨벤션 reference: fallback (role-generic)

### 요약
- 🔴 Blocking: 1개
- 🟡 Important: 2개
- 🟢 Nit: 1개
- 💡 Suggestion: 1개

---

### 🔴 Blocking Issues

#### [B-001] 입력 검증 누락 — handler 가 raw payload 를 그대로 service 로 전달
- **파일**: `src/api/branch_handler.py:23`
- **문제**: `payload = request.json()` 후 검증 없이 `BranchService.create(payload)` 호출. 비정형 입력으로 도메인 오염 위험.
- **Convention**: role-generic — 검증 책임 분리 (input validation 은 경계, business rule 은 도메인/service).
- **해결방안**:
  ```python
  # Before
  async def create_branch(request):
      payload = await request.json()
      return await BranchService.create(payload)

  # After
  async def create_branch(request):
      payload = await request.json()
      command = CreateBranchCommand.from_request(payload)  # 형식 검증
      return await BranchService.create(command)
  ```

---

### 🟡 Important Issues

#### [I-001] N+1 쿼리 의심 — 지점 목록 조회 시 manager 별 추가 쿼리
- **파일**: `src/repository/branch_repo.py:45`
- **문제**: `for branch in branches: branch.manager` 패턴 — manager 별 SELECT 발생.
- **Convention**: role-generic — 일반 성능 (N+1 회피).
- **해결방안**:
  ```python
  # Before
  branches = await session.execute(select(Branch))
  for b in branches:
      await b.awaitable_attrs.manager  # N+1

  # After
  branches = await session.execute(
      select(Branch).options(selectinload(Branch.manager))
  )
  ```

#### [I-002] 도메인 어휘 비일관 — `data` 라는 추상 명칭 사용
- **파일**: `src/api/branch_handler.py:34`
- **문제**: `data = build_response(...)` — 도메인 의도 안 드러남.
- **Convention**: role-generic — 명명 의도 표현.
- **해결방안**: `branch_response = ...` 또는 `created_branch = ...` 로 변경.

---

### 🟢 Nits

#### [N-001] 미사용 import
- **파일**: `src/api/branch_handler.py:3`
- **제안**: `from typing import Dict` 미사용 — 제거.

---

### 💡 Suggestions

#### [S-001] 에러 핸들링 일관화 후보
- **파일**: `src/api/branch_handler.py` 전반
- **제안**: 현재 try-except 가 handler 마다 흩뿌려져 있음. 전역 exception handler + 도메인 예외 라이즈 패턴이 일반적으로 유지보수 ↑. 도입 시 별 PR 권장.

---

### 🎉 잘된 점
- 요청·응답 타입 별도 클래스로 분리 (Pydantic 모델) — 입출력 모델 분리 원칙 충실.
- 함수명 `create_branch` 가 도메인 의도 명확 — 단순 `post()` / `handle()` 회피.

---

### 다음 단계
1. 🔴 B-001 (입력 검증) 먼저 수정 → 머지 전 필수
2. 🟡 I-001 (N+1) 동일 PR 내 또는 후속 PR — 트래픽 영향 측정 후 결정
3. 🟢 N-001 / 💡 S-001 — 별 PR 또는 차후 리팩토링
````

## fallback 의 한계

reference 가 있었다면 추가로 잡혔을 가능성:
- Layer Objects 4객체 패턴 (Request/Command/Result/Response) 적용 여부 (Convention 강제 시)
- Validator 3계층 위치 (L1 Field / L2 model_validator / L3 Validator)
- Repository 메서드 컨벤션 (BaseRepository 재사용·`get_by_xxx` 추가 금지 등)

→ 사용처 프로젝트가 `docs/common/layer-objects.md` / `layer-design.md` / `code-convention.md` 박으면 자동 로드됨. 분기 ADR 도입 시 [[adr-0001-code-review-to-backend]] §자산 분리 룰 (b) 참조.
