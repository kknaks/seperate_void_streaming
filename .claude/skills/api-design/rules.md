# API Design Rules

> 스킬이 강제하는 룰셋. SKILL.md 가 trigger 시 로드 → 본 rules.md 는 실제 룰 적용 시 지연 로드 ([[adr-0007-skill-authoring-rules]] §1).
>
> **rules.md 의 책임 (본질·SSOT)**: *무엇을 강제하는가 / 왜 / 위반 시*. 운영 절차는 `checklist.md` SSOT.

## 5 단계 절차

| 단계 | 시간 (가이드) | 본질 (강제) | 산출 |
|------|---------------|-------------|------|
| 1. 충돌 점검 | 5–10분 | 기존 API 문서·엔드포인트와 중복·일관성 검증 | "충돌 0" 또는 충돌 리스트 |
| 2. ERD / DB 룰 정합 | 5–15분 | 엔티티·관계·필드 타입·FK·소프트 딜리트 부합 | 컨벤션 위반 0 |
| 3. Request 스키마 | 10–30분 | 입력 DTO + 필드·타입·필수·검증 | `*Request` 클래스 또는 schema |
| 4. Response 스키마 + 에러 | 10–30분 | 출력 DTO + 상태 코드별 응답 + 에러 enum | `*Response` + 에러 표 |
| 5. 도메인 문서 갱신 | 5–10분 | 결정을 사용처의 API 문서에 박는다 | `<api-docs>/<domain>.md` 갱신 |

**컬럼 구분** — *시간 (가이드)* 는 가이드라인. *본질 (강제)* 는 강제 (skip 시 차단).

## REST 컨벤션 (공용 골격)

**URL 규칙**:
- 복수형 명사: `/issues`, `/projects`
- 계층: `/projects/{id}/tickets`
- 행위: `/issues/{id}/accept`

**Method 의미 강제**:
- GET: 조회 (소프트 딜리트 자동 필터)
- POST: 생성 (PK 자동 생성)
- PATCH: 부분 수정
- DELETE: 소프트 딜리트 (`deleted_at = now()`)

**응답 코드**:
- 200 (조회·수정) / 201 (생성) / 204 (삭제) / 400 / 401 / 403 / 404 / 422

## 산출 포맷

도메인 문서 작성 형식:

```markdown
### POST /resource
설명

**Request:**
| 필드 | 타입 | 필수 | 설명 |

**Response (201):**
| 필드 | 타입 | 설명 |

**Error:**
| 코드 | 상황 |
```

## reference 로드 모델

| 우선순위 | 경로 | 슬롯 |
|---------|------|------|
| 1 | `plan/api/<domain>.md`, `plan/api/overview.md` | 기존 endpoint / 응답 컨벤션 |
| 2 | `plan/erd/database-rules.md`, `plan/erd/table-design.md` | DB 룰 / 모델 패턴 |
| 3 | `CLAUDE.md` | 프로젝트 가이드라인·도메인 어휘 |
| 4 (fallback) | role-generic | REST 표준·UUID PK·multi-tenancy 사용자 주입 |

**충돌 룰** — 우선순위 낮은 번호 우선. 충돌 자체를 §맥락 에 박는다.

**리포트 출처 강제** — 결정 모든 항목에 *어느 reference 의 어느 §* 인지 명시 (`plan/api/issues.md §POST /issues` 처럼).

## Don't

- 5 단계 순서 위반 (Request 전에 ERD 점검 없이 들어가면 DB 룰 위반 사후 검출).
- 도메인 문서 갱신 누락 — 결정만 하고 박지 않으면 다음 작업 시 충돌 재발.
- 본 SKILL 본문에 NEXUS / Spring 등 특정 컨벤션 박기 ([[adr-0003-api-design-to-backend]] §자산 분리 룰 §금지).
- 사용자 코드 (구현 본문) 직접 작성 — 본 SKILL 은 *설계 합의 + 도메인 문서 갱신 안내* 만.
