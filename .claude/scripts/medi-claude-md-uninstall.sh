#!/usr/bin/env bash
# ADR-0006 D-5. base plugin uninstall 시 사용자 진입점 메타에서 medi-docs-managed
# 마커 블록 제거. 외부 사용자 내용 보존. medi_docs/ 디렉토리는 사용자 자산이라
# 남김 (uninstall 안내 메시지 §5).
#
# Usage: medi-claude-md-uninstall.sh [project-dir]

set -euo pipefail

PROJECT_DIR="${1:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"

removed_count=0
for target in "$PROJECT_DIR/CLAUDE.md" "$PROJECT_DIR/AGENTS.md"; do
  [[ -f "$target" ]] || continue
  grep -q '<!-- medi-docs-managed:start' "$target" || continue

  awk '
    /<!-- medi-docs-managed:start/ { skip = 1; next }
    /<!-- medi-docs-managed:end/ && skip { skip = 0; next }
    !skip { print }
  ' "$target" > "$target.tmp" && mv "$target.tmp" "$target"

  removed_count=$((removed_count + 1))
  echo "removed marker block: $target"
done

if (( removed_count > 0 )); then
  cat <<EOF

[harness/medi-docs] uninstall 완료.
  - 사용자 진입점 메타 (CLAUDE.md / AGENTS.md) 의 medi-docs 안내 섹션 ${removed_count}개 제거됨.
  - medi_docs/ 디렉토리는 사용자 자산이라 보존됩니다. 필요 시 직접 삭제하세요.
EOF
fi

exit 0
