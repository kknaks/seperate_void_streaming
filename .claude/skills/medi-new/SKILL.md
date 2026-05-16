---
name: medi-new
description: medi_docs/current/ 의 9 카테고리 중 하나에 새 문서를 박는다. template.md 시드 + frontmatter id 자동 채움 (NN). 비-planning 문서는 sources 최소 1개 필수 (D4 강제). 사용 예 — "spec 에 customer-onboarding 박아줘", "새 ADR 만들어줘".
allowed_tools: [Bash, Read]
runs_scripts:
  - "[[scripts/medi-new.sh]]"
reads_files:
  - "[[../../../medi_docs/current/<cat>/template.md]]"
---

# medi-new

medi_docs 안에 새 문서 시드를 박는 SKILL. 카테고리 선택 + slug → `<cat>-NN-<slug>.md` 생성.

## When to use

- 사용자가 "새 spec/planning/adr/... 박아줘" 류 요청
- `/medi:new` 가 사장된 후 자연어 진입점

## How to invoke

자연어로 카테고리 + slug 받기:
- "planning 에 customer-onboarding"
- "spec api-foo 새로 박아줘"

명령 실행:
```bash
bash "${CLAUDE_PROJECT_DIR}/.claude/skills/medi-new/scripts/medi-new.sh" <category> <slug>
```

카테고리: `planning / plan / spec / policy / adr / runbook / test / release-notes / retrospective`
slug: kebab-case (예: `customer-onboarding`).

## What it does

1. `medi_docs/current/<cat>/template.md` 시드로 복사
2. 다음 NN 자동 채움 (`<cat>-NN-<slug>.md`)
3. frontmatter `id`, `created`, `updated` 자동 갱신
4. 사용자가 `title` + `sources:` + 본문 채움 → H1 hook 이 D4 검증

## 보안 / 룰셋

자세한 룰은 [`rules.md`](rules.md), 사용자 작성 체크리스트는 [`checklist.md`](checklist.md), 사용 예는 [`examples/`](examples/).
