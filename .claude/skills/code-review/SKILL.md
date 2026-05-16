---
name: code-review
description: 백엔드 변경분의 컨벤션 준수 + 설계 적정성 + 줄단위 보안/성능 점검을 4단계로 검토하고 심각도 5분류 (🔴blocking/🟡important/🟢nit/💡suggestion/🎉praise) 마크다운 리포트를 작성한다. 사용처 프로젝트의 `docs/common/*.md` + `CLAUDE.md` 를 trigger 시 reference 로 로드, 부재 시 role-generic fallback (MVC/계층화 일반 원칙) 으로 동작. PR 생성 전·새 도메인 구현 후·`/review` 슬래시 명령 호출 시 사용.
allowed_tools: [Read, Edit, Bash]
---

# Code Review

백엔드 코드 변경에 대한 *4단계 점검 → 심각도 분류 → 정형 리포트* 산출. 공용 골격 (어떤 백엔드 프로젝트든 적용) 과 프로젝트 컨벤션 (사용처에서 reference 로 로드) 을 분리해 동작.

## When to use

- `/review` 슬래시 명령
- PR 생성 전 코드 품질 자가 점검
- 새 도메인 구현 후 일관성 확인
- 변경 규모가 큰 작업의 분할·우선순위 판단

## How to invoke

```
/review                        # git diff 기반 변경 파일
/review path/to/file.py        # 특정 파일
/review {domain}               # 도메인 디렉토리 전체
```

후속:
1. **reference 로드** — 사용처 프로젝트의 `docs/common/*.md` + `CLAUDE.md` 가 있으면 컨벤션 슬롯 채움. 없으면 role-generic fallback (계층 분리·역방향 의존 금지·일반 보안/성능) 으로 진행.
2. **4단계 점검** — 맥락 파악 → 높은 수준 검토 → 줄단위 검토 → 요약 (자세한 phase 별 본질·시간 가이드는 `rules.md`).
3. **심각도 5분류 + 마크다운 리포트** — 이슈 ID (🔴 B-NNN / 🟡 I-NNN / 🟢 N-NNN) + Convention 출처 + Before/After. 🎉 praise 1건 이상 필수.

자세한 룰셋·심각도 기준·리포트 포맷·금지 사항은 [`rules.md`](rules.md). 운영 체크리스트는 [`checklist.md`](checklist.md). 실제 리포트 sample 은 [`examples/`](examples/).

## 보안 고려사항

- `allow_commands` 선언 이유: (위험 명령 호출 시 — 없으면 "X — read/write only")
- 동적 입력 ($VAR / CLI 인자 / 파일 경로) 처리: `source ../scripts/sanitize.sh` 또는 인용 규칙 (`"$VAR"`/`printf %q`).
- 시크릿 차단 + 출력 마스킹 — 아래 패턴은 read 대상에서 제외하고, 출력에 잡히면 `***` 으로 마스킹.

| 카테고리 | 경로/이름 패턴 | 정규식 (예) |
|----------|----------------|-------------|
| dotenv | `.env`, `.env.*` (`.local`, `.production` 등) | `(^|/)\.env(\..+)?$` |
| 시크릿 디렉토리 | `secrets/`, `secret/`, `credentials/` | `(^|/)(secrets?|credentials)/` |
| 토큰 파일 | `*token*`, `*apikey*`, `*api_key*` | `(token|api[_-]?key)` (대소문자 무시) |
| 키 자료 | `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*` | `\.(pem|key|p12|pfx)$\|^id_rsa` |
| 인증 헤더값 | `Authorization: Bearer ...`, `x-api-key: ...` | `(Bearer\s+\S+|x-api-key:\s*\S+)` |

- 위 패턴 매치 시: 입력 거부 (read 단계) + 출력 발견 시 `***` 치환. 사용처 환경별 추가 패턴은 본 § 에 보강.
