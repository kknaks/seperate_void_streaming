# 위반 예 — D4 lineage 누락

## 위반 파일

`medi_docs/current/spec/spec-01-foo.md`:
```yaml
---
id: spec-01
type: spec
title: Foo Service API
status: draft
sources: []          # ← 빈 리스트, D4 위반
tags: [spec]
---
```

## H1 hook 출력 (저장 시)

```
medi-validate: 1 위반
  - medi_docs/current/spec/spec-01-foo.md: D4 위반 — `sources:` 최소 1개 필요 (cat=spec)
```

exit 2 → Claude Code 가 차단.

## 수정

```yaml
sources:
  - "[[planning-01-customer-onboarding]]"
```

저장 → 통과 → `_map.md` 자동 갱신.

## planning 카테고리는 예외

`planning/` 은 root 라 `sources:` 비워도 OK (외부 RFP/비전 등만 가리킬 수 있음).

```yaml
# planning-01-customer-onboarding.md
---
id: planning-01
type: planning
title: Customer Onboarding
sources: []          # ← OK (planning 은 root)
---
```
