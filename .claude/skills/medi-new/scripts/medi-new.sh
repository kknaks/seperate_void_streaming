#!/usr/bin/env bash
# /medi:new 슬래시의 동작 본판.
# 카테고리 + slug 받아 medi_docs/current/<cat>/<cat>-NN-<slug>.md 생성.
# template.md 시드 + frontmatter id 자동 NN 채움.
#
# Usage: medi-new.sh <category> <slug> [project-dir]

set -euo pipefail

CAT="${1:-}"
SLUG="${2:-}"
PROJECT_DIR="${3:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"

VALID_CATS="planning plan spec policy adr runbook test release-notes retrospective"

if [[ -z "$CAT" || -z "$SLUG" ]]; then
  echo "usage: $0 <category> <slug> [project-dir]" >&2
  echo "  category: $VALID_CATS" >&2
  exit 1
fi

if ! grep -qw "$CAT" <<< "$VALID_CATS"; then
  echo "category 오류: '$CAT'. 허용: $VALID_CATS" >&2
  exit 1
fi

if [[ ! "$SLUG" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
  echo "slug 형식 오류 (kebab-case): '$SLUG'" >&2
  exit 1
fi

CAT_DIR="$PROJECT_DIR/medi_docs/current/$CAT"
TEMPLATE="$CAT_DIR/template.md"

[[ -d "$CAT_DIR" ]] || { echo "$CAT_DIR 부재 — 먼저 scaffold 필요" >&2; exit 1; }
[[ -f "$TEMPLATE" ]] || { echo "$TEMPLATE 부재" >&2; exit 1; }

# 다음 NN 결정
LAST=0
for f in "$CAT_DIR"/$CAT-[0-9][0-9]-*.md; do
  [[ -f "$f" ]] || continue
  bn=$(basename "$f")
  n=$(echo "$bn" | sed -E "s/^${CAT}-([0-9]+)-.*/\1/")
  [[ "$n" =~ ^[0-9]+$ ]] || continue
  (( 10#$n > LAST )) && LAST=10#$n
done
NN=$(printf "%02d" $((LAST + 1)))
OUT="$CAT_DIR/$CAT-$NN-$SLUG.md"

# template 복사 + frontmatter id 갱신 + created/updated 갱신
TODAY=$(date +%Y-%m-%d)
sed -e "s/^id: .*/id: $CAT-$NN/" \
    -e "s/^created: .*/created: $TODAY/" \
    -e "s/^updated: .*/updated: $TODAY/" \
    "$TEMPLATE" > "$OUT"

echo "created: $OUT"
echo "  - frontmatter id = $CAT-$NN"
echo "  - 다음: title 채움 + sources: 링크 + 본문 작성"
[[ "$CAT" != "planning" ]] && echo "  - D4 강제: sources: 최소 1개 필요 (없으면 H1 hook 이 차단)"

exit 0
