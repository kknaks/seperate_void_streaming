# 사용 예 — planning 카테고리에 customer-onboarding 박기

자연어 호출:
> "planning 에 customer-onboarding 박아줘"

또는 직접:
```bash
bash .claude/skills/medi-new/scripts/medi-new.sh planning customer-onboarding
```

산출:
```
medi_docs/current/planning/planning-01-customer-onboarding.md
```

내용 (template.md 시드 + id 자동):
```yaml
---
id: planning-01
type: planning
title: <Title>            # ← 사용자가 채움
status: draft
created: 2026-05-01
updated: 2026-05-01
sources:
  - "[[<upstream>]]"      # ← planning 은 root 라 외부 (RFP 등) 또는 비워도 됨
tags: [planning]
---

# <Title>
...
```

## 후속 단계

1. `<Title>` 채움
2. `sources:` 외부 (RFP / 비전 문서) 가리키거나 비움 (planning 은 root)
3. 본문 작성
4. 저장 → H1 hook 통과 → `_map.md` 자동 갱신
