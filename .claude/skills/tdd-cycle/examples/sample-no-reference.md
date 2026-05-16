# Example: TDD Cycle — fallback (no reference)

> reference 부재 → role-generic fallback case. `sample-with-reference.md` 와 짝.

## 트리거

```
/tdd-cycle product
```

## reference 로드 결과

```
plan/design-standards/      : 없음
tests/mothers/              : 없음 (Mother 패턴 미사용 추정)
CLAUDE.md                   : 없음
→ fallback (role-generic) 작동
  - 테스트 명령: pytest 가정 (`pytest tests/api/test_<domain>.py`)
  - fixture: Pydantic factory 추정 (사용자에게 위치 주입 요청)
```

## 출력 (Red → Green → Refactor)

````markdown
## TDD Cycle 작업 보고

### 대상
- 도메인: `product`
- reference: fallback (role-generic). pytest + Pydantic factory 가정.

### Red
파일: `tests/api/test_product.py` (신규)
- `TestCreateProduct` 클래스 + 6 메서드 (사용자가 test-design 단계에서 합의한 시나리오 1:1)
- request/response 는 api-design 단계 스펙 그대로
- 실행: `pytest tests/api/test_product.py` → 6 failed ✓

### Green
생성:
- `app/schemas/product.py` — `ProductCreateRequest`, `ProductResponse`
- `app/routers/product.py` — `POST/GET/PATCH/DELETE /products` (`response_model=` 강제)
- `app/services/product.py` — `ProductService` (Repository 조합)
- `app/repositories/product.py` — `ProductRepository(BaseRepository[Product])`

실행: `pytest tests/api/test_product.py` → 6 passed ✓
회귀: `pytest` (전체) → all passed ✓

### Refactor
- 네이밍 정렬: `data` → `product_data` (도메인 어휘)
- 중복 제거: 검증 함수 `_validate_price` Service 로 이전
- grep 위반: 0 (사전 스캔 + 사후 스캔 모두)
- 회귀: pass 유지 ✓

### 다음 단계
1. `/code-review app/routers/product.py app/services/product.py` — 사후 검토
````

## fallback 의 한계

reference 가 있었다면:
- 테스트 위치 / 명령 / Mother 패턴 자동 적용
- 4계층 정확한 위치 (사용처 디렉토리)
- 테스트 전략 (피라미드 / 핵심 맵) 자동 반영

→ 사용처가 reference 박으면 다음 호출부터 자동 로드.
