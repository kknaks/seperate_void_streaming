# docs-validate 사용자 체크

## 통과 결과 확인

- [ ] exit 0 (위반 0개)
- [ ] `_map.md` 갱신 시각 확인 (`stat medi_docs/current/_map.md`)
- [ ] 카운트가 실제 파일 수와 일치

## 위반 시 대응

stderr 메시지 패턴:
```
medi-validate: N 위반
  - <path>: frontmatter 부재 (D1)
  - <path>: frontmatter `id:` 부재 (D1)
  - <path>: D4 위반 — `sources:` 최소 1개 필요 (cat=spec)
```

대응:
- frontmatter 부재 → `--- ... ---` 블록 추가
- 필수 키 부재 → 해당 키 채움
- D4 위반 → `sources:` 에 위키링크 최소 1개 추가

## H1 hook 동작 확인

새 파일 박은 후:
- [ ] 저장 직후 stderr 출력 없는지 (위반 0개)
- [ ] 위반 시 H1 차단 메시지 보이는지

## 메인테이너 도구와 구분

본 SKILL = **사용자 배포본** (medi_docs 검증 only). harness 메인테이너 docs (`docs/`, `content/`) 검증은 `.claude/skills/docs-validate/` (메인테이너용) 가 처리 — 별 도구.
