---
name: medi-version-cut
description: medi_docs/current/ 전체를 v{label}/ 으로 박제 (read-only 스냅샷). 사전에 R4 collector 재실행 (CLAUDE.md 동기화) + D1 강제 검증 통과 시에만 박제. 사용 예 — "v1.0 으로 cut", "2026Q2 박제해줘".
allowed_tools: [Bash, Read]
runs_scripts:
  - "[[scripts/medi-version-cut.sh]]"
  - "[[../../scripts/medi-claude-md-augment.sh]]"
  - "[[../docs-validate/scripts/medi-validate.sh]]"
---

# medi-version-cut

medi_docs 의 시점 박제 (carry-forward 모델 — ADR-0008 §2·§3).

## When to use

- 마일스톤 도달 — "v1.0 / 2026Q2 / release-2026-04 으로 박제"
- 정책·계획 변화 추적 시점 동결 (`diff -r v1.0/ v1.1/`)

## How to invoke

자연어로 라벨 받기:
- "v1.0 으로 cut"
- "release-2026-04 박제해줘"

명령:
```bash
bash "${CLAUDE_PROJECT_DIR}/.claude/skills/medi-version-cut/scripts/medi-version-cut.sh" <label>
```

라벨: 사용자 자유. semver 강제 X. 영숫자 + `.` `_` `-` 만 허용.

## What it does

1. **R4 collector 재실행** — CLAUDE.md 마커 블록 재합성 (cut 시점 plugin 풍경 동결, ADR-0006 D-4)
2. **D1 강제 검증** — `current/` 전체 frontmatter + 관계 통과 필수, 실패 시 cut 차단
3. **`current/` → `v{label}/` 복사** — `_map.md` 함께 박제 (관계 그래프 동결)
4. **read-only 마크** — `chmod -R a-w v{label}/`
5. `current/` 그대로 유지 (carry-forward)

## 보안 / 룰셋

자세한 룰은 [`rules.md`](rules.md), 사용자 체크리스트는 [`checklist.md`](checklist.md), 사용 예는 [`examples/`](examples/).
