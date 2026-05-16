#!/usr/bin/env bash
# ADR-0006 D-8. 사용자 진입점 메타 (CLAUDE.md / AGENTS.md) 에 medi-docs 안내
# 마커 블록을 박음. SKILL 목록은 .claude/skills/*/SKILL.md 의 frontmatter 에서
# 동적으로 추출 (commands 사장 후 — 자연어 description-trigger 모델).
#
# 마커 형식 (ADR-0006 D-3): <!-- medi-docs-managed:start v={ver} --> ... :end -->
# Idempotent — 마커 블록 *내부만* 갱신, 외부 사용자 내용 절대 변경 X.
# 발견 우선순위 (D-6): CLAUDE.md → AGENTS.md → 부재 시 CLAUDE.md 신규.
#
# Usage: medi-claude-md-augment.sh [project-dir]
# 본 스크립트는 .claude/scripts/ 에서 실행됨 (init.sh 가 복사).

set -euo pipefail

PROJECT_DIR="${1:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"
CLAUDE_DIR="$PROJECT_DIR/.claude"
SKILLS_DIR="$CLAUDE_DIR/skills"

# Snippet template 발견 — plugin cache 에서 찾기
SNIPPET=$(find ~/.claude/plugins -name 'CLAUDE.md.snippet' -path '*/medi-docs-templates/*' 2>/dev/null | head -1)
[[ -f "$SNIPPET" ]] || { echo "snippet template 부재 (plugin 재설치 필요)" >&2; exit 1; }

# Plugin version
VERSION=$(find ~/.claude/plugins -name 'plugin.json' -path '*/harness/*' 2>/dev/null | head -1 \
          | xargs -I {} grep -E '"version"' {} 2>/dev/null \
          | head -1 | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' || true)
[[ -z "$VERSION" ]] && VERSION='0.0'

TMP=$(mktemp)
trap "rm -f $TMP" EXIT

# 1. snippet 복사 + version 갱신
sed "s/medi-docs-managed:start v=[^ ]* /medi-docs-managed:start v=$VERSION /" "$SNIPPET" > "$TMP"

# 2. SKILL 목록 동적 추출 — .claude/skills/*/SKILL.md 의 name + description 첫 문장
SKILL_LINES=""
if [[ -d "$SKILLS_DIR" ]]; then
  for skill_dir in $(ls -d "$SKILLS_DIR"/*/ 2>/dev/null | sort); do
    [[ -d "$skill_dir" ]] || continue
    skill_md="$skill_dir/SKILL.md"
    [[ -f "$skill_md" ]] || continue

    name=$(awk '/^---$/{c++; if(c==2) exit; next} c==1 && /^name:/{sub(/^name:[[:space:]]*/,""); print; exit}' "$skill_md" || true)
    [[ -z "$name" ]] && name=$(basename "$skill_dir")

    desc=$(awk '/^---$/{c++; if(c==2) exit; next} c==1 && /^description:/{sub(/^description:[[:space:]]*/,""); print; exit}' "$skill_md" || true)
    desc_short=$(echo "$desc" | sed -E 's/([.。].*)//; s/^(.{80}).*/\1.../')
    [[ -z "$desc_short" ]] && desc_short="(no description)"

    SKILL_LINES+="- \`$name\` — $desc_short"$'\n'
  done
fi

# 3. skill-list 마커 사이에 SKILL_LINES 삽입
if [[ -n "$SKILL_LINES" ]]; then
  SKILL_FILE=$(mktemp)
  printf '%s' "$SKILL_LINES" > "$SKILL_FILE"
  awk -v skill_file="$SKILL_FILE" -v end_marker="medi-docs-managed:skill-list:end" '
    index($0, end_marker) {
      while ((getline rl < skill_file) > 0) print rl
      close(skill_file)
    }
    { print }
  ' "$TMP" > "$TMP.2" && mv "$TMP.2" "$TMP"
  rm -f "$SKILL_FILE"
fi

# 4. 사용자 진입점 메타 발견 (D-6)
TARGETS=()
[[ -f "$PROJECT_DIR/CLAUDE.md" ]] && TARGETS+=("$PROJECT_DIR/CLAUDE.md")
[[ -f "$PROJECT_DIR/AGENTS.md" ]] && TARGETS+=("$PROJECT_DIR/AGENTS.md")
if (( ${#TARGETS[@]} == 0 )); then
  TARGETS+=("$PROJECT_DIR/CLAUDE.md")
  touch "$PROJECT_DIR/CLAUDE.md"
fi

# 5. 각 target 에 마커 블록 idempotent 박기
for target in "${TARGETS[@]}"; do
  if grep -q '<!-- medi-docs-managed:start' "$target" 2>/dev/null; then
    awk -v new_block_file="$TMP" '
      BEGIN { skip = 0 }
      /<!-- medi-docs-managed:start/ {
        while ((getline line < new_block_file) > 0) print line
        close(new_block_file)
        skip = 1
        next
      }
      /<!-- medi-docs-managed:end/ && skip { skip = 0; next }
      !skip { print }
    ' "$target" > "$target.tmp" && mv "$target.tmp" "$target"
  else
    [[ -s "$target" ]] && tail -c1 "$target" | grep -q '^$' || echo "" >> "$target"
    cat "$TMP" >> "$target"
  fi
  echo "augmented: $target"
done

exit 0
