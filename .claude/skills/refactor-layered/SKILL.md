---
name: refactor-layered
description: 라우터 1 개 단위 4 계층 (Router/Service/Repository/Schema) 정렬 리팩토링. 책임·금지 표 + 정렬 절차 + grep 위반 검출 자동화
allowed_tools: [Read, Edit, Bash]
---

# Refactor Layered

라우터 1 개 단위 *4 계층 아키텍처* 정렬 리팩토링. 각 계층의 책임·금지 + grep 위반 검출 자동화. wiki-04 (tdd-cycle) 의 Refactor 단계 도구 + wiki-01 (code-review) 의 사후 검토 grep 공유. 4 계층 가정이 *모든 백엔드* 적용 X — hexagonal / clean architecture 변형 사용처는 분기 ADR 후보 (ADR-0005 §Cons).

## When to use

- `/refactor-layered <router>` — 단일 라우터 4 계층 정렬
- `/tdd-cycle` 의 Refactor 단계에서 호출됨
- 새 라우터 추가 시 *작업 전 정렬* 원칙 적용

## How to invoke

```
/refactor-layered <router-name>     # 단일 라우터 정렬
/refactor-layered <router-name> scan  # 사전 스캔만 (grep 위반 카운트)
```

후속:
1. **reference 로드** — `plan/refactor/re*-*.md` (도메인별 진행 트래커), `CLAUDE.md`, 사용처 4 계층 디렉토리 위치.
2. **사전 스캔** — grep 으로 현재 위반 N 측정.
3. **5 단계 정렬** — Schema → Service → Repository → Router → 사후 검증.
4. **회귀 테스트** — 정렬 후 100% pass 확인.

자세한 4 계층 책임표·정렬 절차·grep 명령은 [`rules.md`](rules.md). 운영 절차 [`checklist.md`](checklist.md). sample [`examples/`](examples/).

## 보안 고려사항

- `allow_commands` — grep 명령 (read-only). 코드 수정은 사용자 손.
- 동적 입력 (라우터명·디렉토리 path) 처리: `printf %q` 또는 quoted expansion. 라우터명은 디렉토리 존재 검증 후 사용.
- 시크릿 차단 + 출력 마스킹 — 아래 패턴은 read 대상에서 제외하고, 출력에 잡히면 `***` 으로 마스킹.

| 카테고리 | 경로/이름 패턴 | 정규식 (예) |
|----------|----------------|-------------|
| dotenv | `.env`, `.env.*` (`.local`, `.production` 등) | `(^|/)\.env(\..+)?$` |
| 시크릿 디렉토리 | `secrets/`, `secret/`, `credentials/` | `(^|/)(secrets?|credentials)/` |
| 토큰 파일 | `*token*`, `*apikey*`, `*api_key*` | `(token|api[_-]?key)` (대소문자 무시) |
| 키 자료 | `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*` | `\.(pem|key|p12|pfx)$\|^id_rsa` |
| 인증 헤더값 | `Authorization: Bearer ...`, `x-api-key: ...` | `(Bearer\s+\S+|x-api-key:\s*\S+)` |

- 위 패턴 매치 시: 입력 거부 (read 단계) + 출력 발견 시 `***` 치환.
