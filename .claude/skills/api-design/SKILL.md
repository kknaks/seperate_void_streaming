---
name: api-design
description: 신규·수정 API 엔드포인트의 *구현 전* 설계 합의 — 5 단계 절차 (충돌 점검 → ERD/DB 정합 → Request/Response → 에러 케이스 → 도메인 문서 갱신) + REST 컨벤션 + 산출 포맷
allowed_tools: [Read, Edit, Bash]
---

# API Design

신규·수정 API 엔드포인트의 *구현 전* 설계 합의. 사용처 프로젝트의 reference (`plan/api/*.md`, `plan/erd/*.md`, `CLAUDE.md`) 를 trigger 시 로드, 부재 시 role-generic fallback (REST 표준·디렉토리 자동 추정·도메인 어휘 사용자 주입). wiki-02 (test-design, 시나리오) 의 *직전* + wiki-04 (tdd-cycle, Red→Green) 의 *입력*.

## When to use

- `/api-design <domain>` — 새 도메인의 엔드포인트 설계
- 기존 도메인에 endpoint 추가·수정 — `plan/api/<domain>.md` 갱신
- ERD / DB 룰과의 정합 검증

## How to invoke

```
/api-design <domain>          # 새 도메인 설계
/api-design <existing-domain> # 추가·수정
```

후속:
1. **reference 로드** — `plan/api/`, `plan/erd/`, `CLAUDE.md` 가 있으면 컨벤션 슬롯 채움. 부재 시 fallback (`rules.md`).
2. **5 단계 절차 진행** — 충돌 점검 → ERD/DB 정합 → Request 스키마 → Response/에러 → 도메인 문서 갱신.
3. **산출 보고** — endpoint 표 + Request/Response 표 + 에러 코드 표 + 갱신할 도메인 문서 path.

자세한 5 단계 본질·REST 컨벤션·산출 포맷은 [`rules.md`](rules.md). 운영 체크리스트 [`checklist.md`](checklist.md). sample [`examples/`](examples/).

## 보안 고려사항

- `allow_commands` 필요 X — read 만 (사용처 reference + 기존 API 문서 읽기). 도메인 문서 갱신은 사용자 손.
- 동적 입력 (도메인 slug) 처리: `printf %q` 또는 quoted expansion.
- 시크릿 차단 + 출력 마스킹 — 아래 패턴은 read 대상에서 제외하고, 출력에 잡히면 `***` 으로 마스킹.

| 카테고리 | 경로/이름 패턴 | 정규식 (예) |
|----------|----------------|-------------|
| dotenv | `.env`, `.env.*` (`.local`, `.production` 등) | `(^|/)\.env(\..+)?$` |
| 시크릿 디렉토리 | `secrets/`, `secret/`, `credentials/` | `(^|/)(secrets?|credentials)/` |
| 토큰 파일 | `*token*`, `*apikey*`, `*api_key*` | `(token|api[_-]?key)` (대소문자 무시) |
| 키 자료 | `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*` | `\.(pem|key|p12|pfx)$\|^id_rsa` |
| 인증 헤더값 | `Authorization: Bearer ...`, `x-api-key: ...` | `(Bearer\s+\S+|x-api-key:\s*\S+)` |

- 위 패턴 매치 시: 입력 거부 (read 단계) + 출력 발견 시 `***` 치환. 사용처 환경별 추가 패턴은 본 § 에 보강.
