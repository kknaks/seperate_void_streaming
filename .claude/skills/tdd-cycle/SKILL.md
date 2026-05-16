---
name: tdd-cycle
description: 테스트 주도 개발 Red→Green→Refactor 3 단계 루프. test-design (시나리오) + api-design (스펙) 의 후속, refactor-layered (4계층 정렬) 의 직전. 단계 순서 강제
allowed_tools: [Read, Edit, Bash]
---

# TDD Cycle

Red → Green → Refactor *루프* 안내. wiki-02 (test-design, 시나리오) + wiki-03 (api-design, endpoint) 의 후속. 각 단계 강제 순서 — Red 없이 Green / Green 없이 Refactor 금지. wiki-05 (refactor-layered) 의 grep 도구 활용.

## When to use

- `/tdd-cycle <domain>` — 새 도메인 또는 endpoint 구현
- 단일 단계 호출도 가능 (예: 이미 Red 박혀있고 Green 만 진행)

## How to invoke

```
/tdd-cycle <domain>           # 전체 루프 (Red → Green → Refactor)
/tdd-cycle <domain> red       # Red 단계만
/tdd-cycle <domain> green     # Green 단계만 (Red 박혀있다는 가정)
/tdd-cycle <domain> refactor  # Refactor 단계만 (Green 통과 가정)
```

후속:
1. **reference 로드** — `plan/design-standards/testing-strategy.md`, `tests/mothers/`, `CLAUDE.md`. 부재 시 fallback (pytest 가정).
2. **단계 진행** — Red (테스트 작성·실패 확인) → Green (최소 구현·통과) → Refactor (정리·통과 유지).
3. **인계** — Refactor 끝나면 `/code-review` SKILL 로 사후 검토 권고.

자세한 본질은 [`rules.md`](rules.md). 운영 절차 [`checklist.md`](checklist.md). sample [`examples/`](examples/).

## 보안 고려사항

- `allow_commands` — 테스트 실행 시 사용처 명령 (예: `pytest`, `docker compose exec`) — 사용처 환경 지시. 본 SKILL 자체는 명령 안 박음.
- 동적 입력 (도메인·라우터명) 처리: `printf %q` 또는 quoted expansion.
- 시크릿 차단 + 출력 마스킹 — 아래 패턴은 read 대상에서 제외하고, 출력에 잡히면 `***` 으로 마스킹.

| 카테고리 | 경로/이름 패턴 | 정규식 (예) |
|----------|----------------|-------------|
| dotenv | `.env`, `.env.*` (`.local`, `.production` 등) | `(^|/)\.env(\..+)?$` |
| 시크릿 디렉토리 | `secrets/`, `secret/`, `credentials/` | `(^|/)(secrets?|credentials)/` |
| 토큰 파일 | `*token*`, `*apikey*`, `*api_key*` | `(token|api[_-]?key)` (대소문자 무시) |
| 키 자료 | `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*` | `\.(pem|key|p12|pfx)$\|^id_rsa` |
| 인증 헤더값 | `Authorization: Bearer ...`, `x-api-key: ...` | `(Bearer\s+\S+|x-api-key:\s*\S+)` |

- 위 패턴 매치 시: 입력 거부 (read 단계) + 출력 발견 시 `***` 치환.
