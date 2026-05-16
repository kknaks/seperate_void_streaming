#!/usr/bin/env bash
# /medi:version-cut 슬래시의 동작 본판.
# ADR-0008 §3 cut 동작 + ADR-0006 D-4 cut 시 R4 동기화.
#
# 1. 사전 단계: D-8 R4 collector 재실행 (medi-claude-md-augment.sh)
# 2. D1 강제 검증 (medi-validate.sh) — 실패 시 박제 차단
# 3. current/ 전체 → v{label}/ 복사 (read-only 마크)
# 4. _map.md 함께 박제 (그 시점 관계 그래프 동결)
#
# Usage: medi-version-cut.sh <label> [project-dir]

set -euo pipefail

LABEL="${1:-}"
PROJECT_DIR="${2:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"
PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$LABEL" ]]; then
  echo "usage: $0 <label> [project-dir]" >&2
  echo "  label = v1.0 / 2026Q2 / release-2026-04 ... (사용자 자유, semver 강제 X)" >&2
  exit 1
fi

# label 형식 — 파일시스템 안전 문자만
if [[ ! "$LABEL" =~ ^[a-zA-Z0-9._-]+$ ]]; then
  echo "label 형식 오류: '$LABEL' — 영숫자 + . _ - 만 허용" >&2
  exit 1
fi

CURRENT="$PROJECT_DIR/medi_docs/current"
TARGET="$PROJECT_DIR/medi_docs/$LABEL"

[[ -d "$CURRENT" ]] || { echo "medi_docs/current/ 부재 — 먼저 scaffold 필요" >&2; exit 1; }
[[ -e "$TARGET" ]] && { echo "이미 존재: $TARGET — 다른 라벨 사용" >&2; exit 2; }

echo "[1/4] R4 collector 재실행 (cut 시점 plugin 풍경 동결)..."
bash "$PLUGIN_ROOT/scripts/medi-claude-md-augment.sh" "$PROJECT_DIR" || {
  echo "R4 collector 실패 — cut 차단 (ADR-0006 D-4)" >&2
  exit 3
}

echo "[2/4] D1 강제 검증 (medi-validate.sh)..."
CLAUDE_PROJECT_DIR="$PROJECT_DIR" bash "$PLUGIN_ROOT/scripts/medi-validate.sh" || {
  echo "D1 검증 실패 — cut 차단 (ADR-0008 §6 D1)" >&2
  exit 4
}

echo "[3/4] $CURRENT → $TARGET 박제 중..."
cp -R "$CURRENT" "$TARGET"

echo "[4/4] _map.md 동결 + read-only 마크..."
chmod -R a-w "$TARGET" 2>/dev/null || true

cat <<EOF

[harness/medi-docs] cut 완료.
  - 라벨: $LABEL
  - 위치: $TARGET (read-only)
  - current/ 그대로 유지 (carry-forward — ADR-0008 §2)
  - diff -r medi_docs/<prev>/ medi_docs/$LABEL/ 로 정책 변화 추적 가능
EOF

exit 0
