# Example: Test Design — Generic Backend (fallback)

> reference 부재 → role-generic fallback 으로 동작한 case sample. `sample-with-reference.md` 와 짝.

## 트리거

```
/test-design product-catalog
```

## reference 로드 결과

```
docs/common/test-data-builders.md : 없음 (사용처 프로젝트가 컨벤션 문서 미보유)
docs/common/api-clients.md        : 없음
CLAUDE.md                         : 없음
→ fallback (role-generic) 작동
  - A. Mother 자동 탐색: tests/fixtures/ 발견 (Mother 패턴 X — Pydantic factory 추정)
  - B. API 클라이언트: client fixture 추정 (TestClient 추정)
  - C. 도메인 어휘: 사용자에게 주입 요청 → "product (id, sku, name, price), category (id, name), 권한 분기 없음"
```

## 출력

````markdown
## 테스트 설계 리포트

### 대상
- 도메인 / API: `product` / `POST /products`, `GET /products/{id}`, `PATCH /products/{id}`
- 기획서 출처: `docs/spec/product-catalog-mvp.md:15-48` (사용자 첨부)
- 컨벤션 reference: fallback (role-generic). 도메인 어휘는 사용자 주입 (product, category, 권한 분기 없음).

### 테스트 클래스 구조

```python
class TestCreateProduct:
    """
    목적: 신규 상품 등록 API
    입력: name (1-100자), price (>0), category_id (UUID)
    응답: 201 + Product { id, sku, name, price, category_id, created_at }
    에러 케이스:
      - 422: 입력 형식 위반 (price <= 0, name 길이)
      - 404: category_id 미존재
      - 409: 같은 카테고리 내 동일 name 중복
    비즈니스 규칙:
      - sku 자동 생성 (CAT{카테고리코드}-{랜덤6자리})
      - soft delete 된 카테고리에는 등록 불가
    처리 흐름: validate → category 존재 + active 검증 → sku 생성 → save → 201
    """
```

### 테스트 시나리오 (총 6개)

| # | 시나리오 (메서드명) | 유형 | Given | When | Then |
|---|---------------------|------|-------|------|------|
| 1 | test_creates_product_with_auto_generated_sku | Happy | active category | POST /products (sku 미지정) | 201 + sku 자동 생성 (`CAT...`) |
| 2 | test_rejects_invalid_price | Edge/Error | (없음) | POST 에 price=0 | 422 + price 위반 |
| 3 | test_rejects_invalid_name_length | Edge/Error | (없음) | POST 에 name 길이 위반 | 422 |
| 4 | test_returns_404_for_nonexistent_category | Edge/Error | (없음) | POST 에 임의 category_id | 404 |
| 5 | test_enforces_unique_name_within_category | 비즈니스 규칙 | 같은 카테고리 product 1개 | POST 에 동일 name | 409 |
| 6 | test_rejects_creation_for_soft_deleted_category | 비즈니스 규칙 | soft-deleted category | POST | 422 (또는 409) |

4유형 cover 여부:
- Happy: 1
- Edge / Error: 3
- 비즈니스 규칙: 2
- 상태 전이: 0 (**미해당** — product 가 상태 머신 보유 X. status 필드 추가 시 재설계.)

### 생성할 파일

- `tests/api/test_product.py` — `TestCreateProduct` (1 클래스 + 6 메서드)
- (구현 단계에서 추가) `tests/api/test_product_get.py`, `test_product_patch.py` — 별 PR

### 필요한 Mother/Fixture

- `product_fixture` (신규 — `tests/fixtures/product.py`. fallback: Mother 패턴 미사용 프로젝트로 추정, Pydantic factory 형태)
- `category_fixture` (신규 — 동일 위치)
- `client` (재사용 — fastapi.testclient.TestClient 추정)
- 연관 chain: `category_fixture() → product_fixture(category=...)`

### 다음 단계

1. 사용자 합의 — 시나리오 표 검토 (특히 #6 의 status code 확인 필요: 422 vs 409)
2. (선택) `docs/common/test-data-builders.md` 박는 게 좋음 — Mother 패턴 도입 시 fallback → 구체 컨벤션 전환
3. 구현 (테스트 코드 작성)
4. 구현 후 `code-review` SKILL 로 사후 리뷰
````

## fallback 의 한계

reference 가 있었다면 추가로 잡혔을 가능성:
- Mother chain 컨벤션 명확 (`product_mother(category=category_mother())` 형태)
- API 클라이언트 sub-client (`client.products`) 명세
- 권한 분기 시나리오 (예: HQ vs 지점) — `CLAUDE.md` 권한 어휘 부재 시 누락

→ 사용처 프로젝트가 `docs/common/test-data-builders.md` / `api-clients.md` / `CLAUDE.md` 박으면 자동 로드됨. 분기 ADR 도입 시 [[adr-0002-test-design-to-backend]] §자산 분리 룰 (b) 참조.
