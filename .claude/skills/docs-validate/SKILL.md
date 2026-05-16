---
name: docs-validate
description: medi_docs/current/ 의 frontmatter (R4-R9 최소셋) + 관계 (D4 lineage 필수) 검증 + _map.md 자동 갱신. H1 hook (PostToolUse Write|Edit) 의 호출 대상이자 medi-version-cut 의 D1 사전 검증. 사용 예 — "검증해줘", "_map.md 갱신해줘".
allowed_tools: [Bash, Read]
runs_scripts:
  - "[[scripts/medi-validate.sh]]"
---

# docs-validate

medi_docs 사용자 배포본 검증·인덱싱. 메인테이너용 `.claude/skills/docs-validate` 와 별도 (spec-12 §50 — 권한·범위 분리).

## When to use

- H1 hook 자동 발동 (Write|Edit on `medi_docs/current/**`)
- 사용자 명시 호출 — "검증해줘", "_map.md 갱신해줘"
- medi-version-cut 의 D1 사전 검증 (cut 직전 강제)

## How to invoke

자동 (H1 hook):
```
medi_docs/current/spec/spec-01-foo.md 저장
  → H1 발동 → docs-validate/scripts/medi-validate.sh 자동 실행
```

수동:
```bash
bash "${CLAUDE_PROJECT_DIR}/.claude/skills/docs-validate/scripts/medi-validate.sh"
```

## What it does

1. `medi_docs/current/<cat>/*.md` 순회 (README/template/_map 제외)
2. **D1 검증** — frontmatter 추출 + 필수 키 (`id`, `type`, `title`) 존재 확인
3. **D4 검증** — 비-`planning` 문서는 `sources:` 최소 1개 필수
4. 위반 시 stderr + exit 2 (H1 차단)
5. 통과 시 `_map.md` 자동 갱신 — 카테고리별 카운트 + 문서 인덱스

## 보안 / 룰셋

자세한 룰셋 (R4-R9·D1·D4·_map.md 형식) 은 [`rules.md`](rules.md), 사용자 체크리스트는 [`checklist.md`](checklist.md), 위반 패턴 예는 [`examples/`](examples/).
