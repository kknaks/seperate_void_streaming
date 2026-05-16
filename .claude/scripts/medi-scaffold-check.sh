#!/usr/bin/env bash
# H2 hook 호출 대상. SessionStart 시 발동. medi_docs/ 부재면 안내 + scaffold 권유.
# ADR-0008 §4 install hook 강제 X — silent suggestion only.
# ADR-0006 D-1 R2 자산.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# medi_docs/ 존재하면 silent
if [[ -d "$PROJECT_DIR/medi_docs" ]]; then
  exit 0
fi

# 안내만 — 자동 scaffold 안 함 (사용자 통제권 보존)
cat <<'EOF'
[harness/medi-docs] medi_docs/ 디렉토리가 없습니다.

이 프로젝트에 정형화된 docs 구조 (9 카테고리 + lineage + 자동 검증) 를 박으려면:
  /harness scaffold-medi-docs
또는 직접:
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold-medi-docs.sh"

(scaffold 시 CLAUDE.md 에도 medi-docs 안내 섹션이 마커 블록으로 박힙니다.
 외부 내용은 절대 안 건드립니다. ADR-0006 D-3.)

원치 않으면 무시하세요. 이 안내는 매 세션마다 1회 출력됩니다.
EOF

exit 0
