---
name: test-design
description: 백엔드 신규 도메인·API 의 테스트 설계 단계 (구현 전) 산출물을 합의 가능한 정형 리포트로 만든다 — 의도 표현 원칙·3계층 docstring·Mother 패턴·시나리오 4분류·리포트 포맷 5요소. 사용처 프로젝트의 Mother 위치 / API 클라이언트 / 도메인 어휘 3 reference 슬롯을 trigger 시 로드, 부재 시 role-generic fallback (자동 탐색·주입 안내) 으로 동작. PR 작성 전·새 도메인 시작 시·/test-design 슬래시 명령 호출 시 사용.
allowed_tools: [Read, Edit, Bash]
---

# Test Design

백엔드 신규 도메인·API 의 *구현 전* 테스트 설계 단계 산출. 공용 골격 (의도 표현 / 3계층 docstring / Mother 패턴 / 시나리오 4분류 / 설계 리포트) 과 프로젝트 의존 슬롯 (Mother 위치·API 클라이언트·도메인 어휘) 을 분리해 동작. 자매 SKILL [`code-review`](../code-review/) 와 같은 분리 패턴 — *사전 설계* (test-design) vs *사후 리뷰* (code-review).

## When to use

- `/test-design` 슬래시 명령
- 새 도메인·API 구현 시작 직전 — 시나리오 합의 + 파일 구조 사전 확정 (TDD)
- PR 작성 전 — 시나리오 누락 자가 점검 (4분류 cover)
- 변경 규모가 큰 작업의 시나리오 분할·우선순위 판단

## How to invoke

```
/test-design                       # 마지막 변경된 도메인
/test-design {domain}              # 도메인 디렉토리 (예: branch, manager)
/test-design path/to/spec.md       # 기획서·요구사항 문서 입력
```

후속:
1. **reference 로드** — 사용처 프로젝트의 `docs/common/test-data-builders.md` / `docs/common/api-clients.md` / `CLAUDE.md` 가 있으면 Mother 위치·API 클라이언트·도메인 어휘 슬롯 채움. 부재 시 role-generic fallback (Mother 자동 탐색 + 도메인 어휘 주입 안내).
2. **5요소 점검** — 의도 표현 → 3계층 docstring → Mother → 시나리오 4분류 → 리포트 포맷 (자세한 본질·구조는 `rules.md`).
3. **테스트 설계 리포트** — 클래스 구조 (기획 요구사항 6항목) + 시나리오 표 (#·시나리오·유형·Given·When·Then) + 생성할 파일 + 필요 Mother/Fixture + 다음 단계 (구현 SKILL 인계).

자세한 룰셋·시나리오 4분류·리포트 포맷·금지 사항은 [`rules.md`](rules.md). 운영 체크리스트는 [`checklist.md`](checklist.md). 실제 리포트 sample 은 [`examples/`](examples/).

## 보안 고려사항

- `allow_commands` 필요 X — read 만 (기획서·기존 테스트·컨벤션 reference 읽기). 테스트 코드 작성은 사용자 손에 남김 (본 SKILL 은 *설계 리포트* 만 산출).
- 동적 입력 (도메인 slug / 파일 경로 / 기획서 path) 처리: `printf %q` 또는 quoted expansion (`"$VAR"`). `../` 탈출 / 절대 경로 / 심볼릭 검증.
- 시크릿 차단 + 출력 마스킹 — 아래 패턴은 read 대상에서 제외하고, 출력에 잡히면 `***` 으로 마스킹.

| 카테고리 | 경로/이름 패턴 | 정규식 (예) |
|----------|----------------|-------------|
| dotenv | `.env`, `.env.*` (`.local`, `.production` 등) | `(^|/)\.env(\..+)?$` |
| 시크릿 디렉토리 | `secrets/`, `secret/`, `credentials/` | `(^|/)(secrets?|credentials)/` |
| 토큰 파일 | `*token*`, `*apikey*`, `*api_key*` | `(token|api[_-]?key)` (대소문자 무시) |
| 키 자료 | `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*` | `\.(pem|key|p12|pfx)$\|^id_rsa` |
| 인증 헤더값 | `Authorization: Bearer ...`, `x-api-key: ...` | `(Bearer\s+\S+|x-api-key:\s*\S+)` |

- 위 패턴 매치 시: 입력 거부 (read 단계) + 출력 발견 시 `***` 치환. 사용처 환경별 추가 패턴은 본 § 에 보강.
