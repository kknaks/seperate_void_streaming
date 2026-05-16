# medi-version-cut 사용자 체크

cut 호출 직전:

- [ ] `medi_docs/current/` 의 모든 문서 frontmatter + sources 채워졌는가
- [ ] 미완성 draft 문서 정리 (남겨두면 D1 차단)
- [ ] 라벨 결정 (`v1.0` / `2026Q2` / `release-2026-04` 등)
- [ ] 동일 라벨 `v{label}/` 이미 존재 X 확인
- [ ] CLAUDE.md 외부 사용자 본문 정리 (cut 시 마커 블록만 재합성, 외부는 보존되지만 한번 점검)

cut 후:

- [ ] `medi_docs/v{label}/` 디렉토리 박힘 + read-only (`ls -la` 확인)
- [ ] `_map.md` 동결됨
- [ ] CLAUDE.md 마커 블록 갱신됨 (`v=` 버전 + 슬래시 목록)
- [ ] git commit `medi_docs/v{label}/` (팀 공유)

## 차단 시

D1 검증 실패 → stderr 위반 메시지 → 해당 파일 수정 후 재시도.

R4 augment 실패 → CLAUDE.md 권한·마커 충돌 확인 후 재시도.
