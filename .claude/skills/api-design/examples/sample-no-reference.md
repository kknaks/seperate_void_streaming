# Example: API Design — fallback (no reference)

> reference 부재 → role-generic fallback case. `sample-with-reference.md` 와 짝.

## 트리거

```
/api-design product
```

## reference 로드 결과

```
plan/api/*.md              : 없음
plan/erd/*.md              : 없음
CLAUDE.md                  : 없음
→ fallback (role-generic) 작동
  - REST 표준 컨벤션 (URL/Method/응답 코드)
  - 사용자 주입 요청: "product 도메인 어휘 (id, sku, name, price), 권한 분기 없음, 멀티테넌시 X"
```

## 출력

````markdown
## API Design 작업 보고

### 대상
- 도메인: `product`
- reference: fallback (role-generic). 도메인 어휘 사용자 주입.

### 1. 충돌 점검
- 충돌 0 (기존 도메인 문서 부재)

### 2. ERD / DB 룰
- PK: UUID 권장 (사용자 fallback)
- 소프트 딜리트: 권장 (사용자 확인 필요)

### 3-4. Endpoint 설계

| Method | Path | Request | Response | Error |
|--------|------|---------|----------|-------|
| POST | `/products` | `{name, sku?, price, category_id}` | 201 + Product | 422 (price≤0), 404 (category) |
| GET | `/products` | (페이지네이션) | 200 + Page[Product] | — |
| GET | `/products/{id}` | — | 200 + Product | 404 |
| PATCH | `/products/{id}` | partial | 200 + Product | 404, 422 |
| DELETE | `/products/{id}` | — | 204 | 404 |

### 5. 도메인 문서 갱신 (사용자 손)
- 위치: 사용처 결정 (예: `docs/api/product.md` 신규)

### 다음 단계
1. `/test-design product` — 시나리오 합의
2. `/tdd-cycle product` — Red 시작
````

## fallback 의 한계

reference 가 있었다면:
- 기존 endpoint 와 충돌 자동 검출
- DB 룰·모델 패턴 자동 적용
- 도메인 문서 위치 / 형식 자동 결정

→ 사용처가 reference 박으면 다음 호출부터 자동 로드.
