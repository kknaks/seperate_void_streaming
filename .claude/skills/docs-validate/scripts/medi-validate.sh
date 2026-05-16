#!/usr/bin/env bash
# H1 hook 호출 대상. medi_docs/current/** 변경 시 발동.
# ADR-0008 §6 D1 (frontmatter 통과) + D4 (lineage 필수) 검증.
# ADR-0006 D-1 의 R3 자산 — 사용자 배포본 중 최소 동작 (skill 본판은 base/skills/docs-validate/).
#
# Hook input: stdin 으로 JSON (Claude Code hook 표준). 여기서는 path filter 만 신뢰.
# Output: 0 = OK / 1 = warning / 2 = block (D1·D4 위반).
#
# 본 스크립트는 *최소 동작* — 운영 누적 후 skills/docs-validate/ 로 합성·확장.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
TARGET="$PROJECT_DIR/medi_docs/current"

[[ -d "$TARGET" ]] || exit 0  # medi_docs 부재면 H2 가 안내 — 이쪽은 silent

violations=()
warnings=()

# bash 3.2 호환 — globstar 회피, find 사용
while IFS= read -r f; do
  [[ -f "$f" ]] || continue
  bn=$(basename "$f")
  cat=$(basename "$(dirname "$f")")

  # README.md / template.md / _map.md 는 skip
  case "$bn" in
    README.md|template.md|_map.md) continue ;;
  esac

  # frontmatter 추출 (--- 사이)
  fm=$(awk '/^---$/{c++; if(c==2) exit; next} c==1' "$f" 2>/dev/null || true)
  [[ -z "$fm" ]] && { violations+=("$f: frontmatter 부재 (D1)"); continue; }

  # 필수 키: id, type, title (R4-R9 최소셋)
  for k in id type title; do
    grep -qE "^${k}:" <<< "$fm" || violations+=("$f: frontmatter \`${k}:\` 부재 (D1)")
  done

  # D4: 비-planning 문서는 sources: 최소 1개. retrospective 만 cross-cutting 허용.
  if [[ "$cat" != "planning" ]]; then
    # sources: 다음에 - "[[..." 한 줄이라도 있어야 함
    has_src=$(awk '/^sources:/{flag=1; next} flag && /^[a-z_]+:/{flag=0} flag && /^[[:space:]]*-[[:space:]]/{print; exit}' <<< "$fm" || true)
    if [[ -z "$has_src" ]]; then
      violations+=("$f: D4 위반 — \`sources:\` 최소 1개 필요 (cat=$cat)")
    fi
  fi
done < <(find "$TARGET" -type f -name '*.md' 2>/dev/null)

if (( ${#violations[@]} > 0 )); then
  printf 'medi-validate: %d 위반\n' "${#violations[@]}" >&2
  printf '  - %s\n' "${violations[@]}" >&2
  exit 2
fi

# _map.md 자동 갱신 — 최소 카운트 박제 (운영 누적 후 트리 뷰 합성).
# bash 3.2 호환 — assoc array 회피, 함수로 1회 카운트.
MAP="$TARGET/_map.md"
CATS="planning plan spec policy adr runbook test release-notes retrospective"

count_cat() {
  find "$TARGET/$1" -maxdepth 1 -type f -name '*.md' \
      ! -name 'README.md' ! -name 'template.md' 2>/dev/null | wc -l | tr -d ' '
}

total=0
for cat in $CATS; do
  total=$((total + $(count_cat "$cat")))
done

{
  printf '# medi_docs/_map.md\n\n'
  printf '> 자동 생성 (medi-validate.sh, %s).\n\n' "$(date +%Y-%m-%d)"
  printf '_총 %d 문서 (' "$total"
  sep=''
  for cat in $CATS; do
    printf '%s%s %d' "$sep" "$cat" "$(count_cat "$cat")"
    sep=' / '
  done
  printf ')_\n\n'
  printf '## 카테고리별\n\n'
  for cat in $CATS; do
    n=$(count_cat "$cat")
    [[ "$n" -gt 0 ]] || continue
    printf '### %s — %d\n\n' "$cat" "$n"
    find "$TARGET/$cat" -maxdepth 1 -type f -name '*.md' \
        ! -name 'README.md' ! -name 'template.md' 2>/dev/null | sort \
        | while read -r f; do
      bn=$(basename "$f")
      printf -- '- `%s`\n' "$bn"
    done
    printf '\n'
  done
} > "$MAP"

exit 0
