# Example: Refactor Layered — fallback (no reference)

> reference 부재 → role-generic fallback case. `sample-with-reference.md` 와 짝.

## 트리거

```
/refactor-layered product
```

## reference 로드 결과

```
plan/refactor/re*-*.md     : 없음 (트래커 부재)
CLAUDE.md                  : 없음
사용처 디렉토리             : 자동 탐색
  - 발견: app/{routers,services,repositories,schemas}/  (FastAPI 추정)
→ fallback (role-generic) 작동 + 사용자 확인 필요
  ✓ 사용자 확인: FastAPI / 4계층 / Pydantic v2
```

## 출력

````markdown
## Refactor Layered 작업 보고

### 대상
- 라우터: `product`
- reference: fallback (role-generic). FastAPI 디렉토리 자동 추정 + 사용자 확인.

### 사전 스캔 (위반 카운트)
- Router DB 직접 호출: 3 (line 23, 45, 78)
- Service SQLAlchemy 직접: 5 (services/product.py)
- Response DTO 누락: 1 (DELETE endpoint)

### Schema 정렬
- `app/schemas/product.py` 박기 — `ProductRequest`, `ProductResponse`, `ProductCreateRequest`
- ORM 모델 import 제거 (`from app.models.product import Product` 삭제)
- `model_validate(product)` 변환 추가

### Service 정렬
- `app/services/product.py` — `select(Product).where(...)` 등 5건 → `self.repo.list_by_*()` 위임
- `data: dict` 파라미터 → `ProductCreateRequest` 로 변경
- `Product` 모델 반환 → `ProductResponse.model_validate(...)` 변환

### Repository 정렬
- `app/repositories/product.py` — `BaseRepository[Product]` 상속 박기
- 도메인 쿼리 `list_by_category(category_id)` 확장 메서드 추가

### Router 정렬
- 3 건 DB 직접 호출 모두 Service 경유로
- `response_model=ProductResponse` 모든 endpoint 추가
- DELETE endpoint 의 `response_model=None` 명시

### 사후 검증
- Router DB 호출: 0 ✓
- Service SQLAlchemy 직접: 0 ✓
- Response DTO 누락: 0 ✓
- 회귀 테스트: 12/12 pass (baseline 동일)

### 다음 단계
1. (선택) `/code-review app/routers/product.py app/services/product.py` — 사후 검토
2. (사용자) plan/refactor 트래커가 있다면 진행 상태 갱신
````

## fallback 의 한계

reference 가 있었다면:
- 디렉토리 위치 자동 (사용자 확인 단계 skip)
- 허용 예외 영역 (시드 / 마이그레이션 / WebSocket) 자동 인식
- 진행 트래커 자동 갱신
- Repository 룰 (`get_by_xxx` 추가 금지 등) 정확 적용

→ 사용처가 reference 박으면 다음 호출부터 자동 로드.
