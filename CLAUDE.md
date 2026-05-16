
<!-- medi-docs-managed:start v=0.1.2 -->
## medi_docs/ (harness plugin)

이 프로젝트의 docs 는 `medi_docs/current/` 의 9 카테고리에 정형화되어있다.

**진입점**: `medi_docs/planning/` 부터 읽고 frontmatter `sources:` 그래프 따라 내려간다. 관계 그래프는 `medi_docs/current/_map.md`.

**9 카테고리**: `planning` (무엇을) → `plan` (언제·어떻게) → `spec/policy` (명세·정책) → `adr` (결정) → `runbook` `test` `release-notes` `retrospective`.

**버전 모델**: `current/` = 살아있는 작업 + `v{label}/` = cut 시점 박제 (read-only).

**SKILLs (자연어 호출 — description-trigger)**:
<!-- medi-docs-managed:skill-list:start -->
- `api-design` — 신규·수정 API 엔드포인트의 *구현 전* 설계 합의 — 5 단계 절차 (충돌 점검 → ERD/DB 정합 → Request/Response → ...
- `code-review` — 백엔드 변경분의 컨벤션 준수 + 설계 적정성 + 줄단위 보안/성능 점검을 4단계로 검토하고 심각도 5분류 (🔴blocking/🟡important...
- `docs-validate` — medi_docs/current/ 의 frontmatter (R4-R9 최소셋) + 관계 (D4 lineage 필수) 검증 + _map
- `medi-new` — medi_docs/current/ 의 9 카테고리 중 하나에 새 문서를 박는다
- `medi-version-cut` — medi_docs/current/ 전체를 v{label}/ 으로 박제 (read-only 스냅샷)
- `refactor-layered` — 라우터 1 개 단위 4 계층 (Router/Service/Repository/Schema) 정렬 리팩토링
- `tdd-cycle` — 테스트 주도 개발 Red→Green→Refactor 3 단계 루프
- `test-design` — 백엔드 신규 도메인·API 의 테스트 설계 단계 (구현 전) 산출물을 합의 가능한 정형 리포트로 만든다 — 의도 표현 원칙·3계층 docstri...
<!-- medi-docs-managed:skill-list:end -->

**자동 hook**:
- `medi_docs/current/**` 변경 시 frontmatter + 관계 자동 검증 (H1).
- 신규 세션 진입 시 `medi_docs/` 부재면 scaffold 안내 (H2).

**강제 룰**:
- D1 (cut 직전 검증) — `current/` 전체가 frontmatter 통과해야 cut 가능.
- D4 (lineage 필수) — 비-`planning` 문서는 `sources:` 최소 1개 필수.

(이 섹션은 harness plugin 이 자동 박음 + 갱신. 마커 외부 내용은 보존됨.)
<!-- medi-docs-managed:end -->
