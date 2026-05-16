# Example: Code Review — NEXUS Backend (reference 로드)

> 사용처 프로젝트가 `docs/common/*.md` + `CLAUDE.md` 보유 → 1번 우선 + role-generic 보완 case sample. `sample-no-reference.md` 와 짝.

## 트리거

```
/review src/branch/router.py src/branch/service.py
```

## reference 로드 결과

```
docs/common/layer-objects.md   : 로드 (Request/Command/Result/Response 4객체)
docs/common/layer-design.md    : 로드 (Validator 3계층, Router·Service·Repository 룰)
docs/common/code-convention.md : 로드 (Python 스타일·import·타입 힌트)
CLAUDE.md                      : 로드 (Repository 룰: get_by_xxx 추가 금지 등)
→ 1번 우선 적용. 충돌 항목 없음.
```

## 출력

````markdown
## Code Review Report

### 맥락
- 대상: `src/branch/router.py`, `src/branch/service.py`
- 변경 규모: 142 줄 (적정)
- 변경 유형: 새 기능 (지점 생성 API, NEXUS 백엔드)
- 컨벤션 reference: `docs/common/layer-objects.md`, `docs/common/layer-design.md`, `docs/common/code-convention.md`, `CLAUDE.md` (4/4 로드. 충돌 없음.)

### 요약
- 🔴 Blocking: 2개
- 🟡 Important: 3개
- 🟢 Nit: 1개
- 💡 Suggestion: 0개

---

### 🔴 Blocking Issues

#### [B-001] L3 Validator 가 Result 를 반환 — Layer Objects 위반
- **파일**: `src/branch/service.py:34`
- **문제**: `BranchValidator.validate_for_creation()` 이 `Result` 객체를 반환. L3 Validator 는 *항상 None 반환* 후 예외 발생 패턴.
- **Convention**: `docs/common/layer-design.md §검증 3계층` — *L3 Validator 는 None 반환, 위반 시 raise BranchValidationError*.
- **해결방안**:
  ```python
  # Before
  def validate_for_creation(self, command: CreateBranchCommand) -> Result:
      if not self.repo.exists_manager(command.manager_id):
          return Result.fail("manager not found")
      return Result.ok()

  # After
  def validate_for_creation(self, command: CreateBranchCommand) -> None:
      if not self.repo.exists_manager(command.manager_id):
          raise BranchValidationError("manager not found")
  ```

#### [B-002] Router 에 try-except — `HTTPException` 사용 금지
- **파일**: `src/branch/router.py:18`
- **문제**: Router 에서 `try: ... except: raise HTTPException(...)`. NEXUS 백엔드는 *전역 핸들러* 에서 도메인 예외 → HTTP 응답 변환.
- **Convention**: `docs/common/layer-design.md §Router 룰` — *Router 는 변환+호출만, try-except / HTTPException 금지*.
- **해결방안**:
  ```python
  # Before
  @router.post("/branches")
  async def create_branch(request: BranchCreateRequest):
      try:
          command = request.to_command()
          result = await service.create(command)
          return BranchResponse.from_result(result)
      except BranchValidationError as e:
          raise HTTPException(status_code=400, detail=str(e))

  # After (try-except 제거 — 전역 핸들러가 BranchValidationError → 400 변환)
  @router.post("/branches")
  async def create_branch(request: BranchCreateRequest):
      command = request.to_command()
      result = await service.create(command)
      return BranchResponse.from_result(result)
  ```

---

### 🟡 Important Issues

#### [I-001] L1 Field 검증을 model_validator 에 박음 — 계층 혼동
- **파일**: `src/branch/request.py:15`
- **문제**: `name` 의 길이 검증 (`>=2, <=50`) 을 `model_validator` 에 박음. 단일 필드 형식 검증은 L1 Field 책임.
- **Convention**: `docs/common/layer-design.md §검증 3계층 §L1` — *단일 필드 형식 검증은 Pydantic Field constraint*.
- **해결방안**:
  ```python
  # Before
  class BranchCreateRequest(BaseModel):
      name: str
      @model_validator(mode="after")
      def check_name(self):
          if not (2 <= len(self.name) <= 50): raise ValueError(...)

  # After
  class BranchCreateRequest(BaseModel):
      name: str = Field(min_length=2, max_length=50)
  ```

#### [I-002] Repository 에 `get_by_manager_id` 추가 — BaseRepository 재사용 룰 위반
- **파일**: `src/branch/repository.py:42`
- **문제**: `BranchRepository.get_by_manager_id()` 신규 추가. CLAUDE.md 의 *Repository 룰* — `get_by_xxx` 메서드 추가 금지, 호출처에서 BaseRepository 의 `get_all(filter=...)` 사용.
- **Convention**: `CLAUDE.md §Repository 룰` — *`get_by_xxx` 추가 금지, BaseRepository 재사용*.
- **해결방안**: 호출처를 `repo.get_all(filter={"manager_id": manager_id})` 로 변경, 신규 메서드 제거.

#### [I-003] Command → Result 변환 누락 — Service 가 raw model 반환
- **파일**: `src/branch/service.py:51`
- **문제**: `service.create()` 가 `Branch` 도메인 모델 직접 반환. Service 는 *Command → Result* 변환 책임.
- **Convention**: `docs/common/layer-objects.md §Result` — *Service 는 Result 반환, Router 가 Response 로 변환*.
- **해결방안**: `Result.from_model(branch)` 로 감싸 반환.

---

### 🟢 Nits

#### [N-001] `Optional[X]` 사용 — Python 3.10+ `X | None` 권장
- **파일**: `src/branch/request.py:8`
- **제안**: `Optional[str]` → `str | None`.
- **Convention**: `docs/common/code-convention.md §타입 힌트` — *PEP 604, Python 3.10+ `|` 권장*.

---

### 🎉 잘된 점
- `BranchCreateRequest.to_command()` / `BranchResponse.from_result()` 변환 메서드 완비 — Layer Objects 4객체 패턴 충실.
- 도메인 예외 (`BranchValidationError`, `BranchNotFoundError`) 명확히 분리 — 전역 핸들러 매핑 용이.

---

### 다음 단계
1. 🔴 B-001, B-002 먼저 수정 → 머지 전 필수 (Layer Objects + Router 룰 위반)
2. 🟡 I-001 ~ I-003 동일 PR 내 — 검증 계층/Repository/Service 룰 정합
3. 🟢 N-001 — 별 PR 또는 lint 자동 적용
````

## reference 로드의 가치

`sample-no-reference.md` (fallback) 와 비교하면:
- 잡힌 이슈 수 ↑ (5 → 6) — Layer Objects / Validator 3계층 / Repository 룰처럼 NEXUS 컨벤션 의존 패턴이 추가로 발견됨
- Convention 출처 정밀도 ↑ — `role-generic — 검증 책임 분리` 대신 `docs/common/layer-design.md §검증 3계층 §L1` 처럼 *파일 + § (섹션)* 까지 박힘
- 사용자가 "왜 이게 룰인가?" 추적 시 즉시 정본 reference 로 이동

reference 충돌 시 [`rules.md` §reference 로드 모델 §충돌 룰](../rules.md) 참조 — 우선순위 1번 (`docs/common/`) 우선 + 충돌 자체를 §맥락 에 박는다.
