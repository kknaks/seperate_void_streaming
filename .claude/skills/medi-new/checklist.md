# medi-new 사용자 체크

새 문서 박은 직후 사용자가 확인할 항목:

- [ ] 파일명: `<cat>-NN-<slug>.md` 형식 맞는가
- [ ] frontmatter `id` 자동 채워짐 (`<cat>-NN`)
- [ ] frontmatter `title` 채움 (`<Title>` placeholder 갈아끼움)
- [ ] (비-planning) `sources:` 최소 1개 채움 — `[[planning-NN-...]]` 또는 상위 카테고리 위키링크
- [ ] 본문 1줄 Summary 채움
- [ ] 저장 시 H1 hook 이 검증 통과 (stderr 위반 메시지 없는지)

## D4 위반 시

H1 hook 이 차단 (exit 2). stderr 메시지 예:
```
medi-validate: 1 위반
  - medi_docs/current/spec/spec-01-foo.md: D4 위반 — `sources:` 최소 1개 필요 (cat=spec)
```

→ 해당 파일 frontmatter `sources:` 채우고 재저장.
