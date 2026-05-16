# docs-validate 룰

## frontmatter 필수 키 (D1)

비-README/template/_map 문서는 frontmatter `--- ... ---` 안에 다음 키 필수:
- `id` (예: `planning-01`, `spec-03`)
- `type` (카테고리명과 일치, 예: `planning`, `spec`)
- `title`

누락 시 → stderr 위반 + exit 2 (H1 차단).

운영 누적 후 추가될 권장 키 (현재 권장):
- `status` (`draft / accepted / superseded`)
- `created`, `updated` (ISO 날짜)
- `tags` (리스트)

## D4 lineage 필수 (ADR-0008 §6)

비-`planning` 문서는 `sources:` 최소 1개 필수.

```yaml
sources:
  - "[[planning-01-customer-onboarding]]"
```

빈 리스트 (`sources: []`) → 차단.
`sources` 키 자체 없음 → 차단.
placeholder (`[[<upstream>]]`) 도 *현재* 통과 (운영 누적 후 placeholder 검증 추가 검토).

`retrospective` 만 다수 cross-cutting (여러 sources) 권장.

## skip 대상

- `README.md`
- `template.md`
- `_map.md` (자동 생성물)

## _map.md 자동 갱신

위반 0개 시 `_map.md` 재생성:
- 총 문서 카운트 + 카테고리별 카운트
- 카테고리별 문서 인덱스

운영 누적 후 합성:
- planning-root lineage 트리 뷰
- 관계 4종 (`sources / related_to / supersedes / depends_on`) 그래프

## H1 hook 통합

`hooks.json` 의 H1 (`PostToolUse(Write|Edit) on medi_docs/current/**`) 가 본 SKILL 의 `scripts/medi-validate.sh` 호출. exit 2 = Claude Code 가 *차단* 으로 인식.

## 보안

- read/write 만 — destructive 동작 X
- stdin JSON (Claude Code hook 표준) 무시 — path filter 만 신뢰
- find 로 medi_docs/current/ 내부만 순회 (외부 파일 절대 안 건드림)
