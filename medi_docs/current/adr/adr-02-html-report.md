---
id: adr-02
type: adr
title: Ablation 결과는 단일 HTML report 로 공유
status: accepted
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[planning-01-ablation-study]]"
  - "[[spec-04-render-report]]"
tags: [adr, v0.2, report, html, sharing]
---

# adr-02 — Ablation 결과는 단일 HTML report 로 공유

## Status

Accepted (2026-05-22)

## Context

Phase 1~2 ablation 결과 (48 combinations × N samples × metrics) 를 팀과 공유 + 의사결정 input 으로 활용해야 함.

옵션 후보:
- Jupyter notebook (`.ipynb`)
- Streamlit / Gradio (서버 형식)
- 단일 정적 HTML (Jinja2 template + Chart.js inline)
- CSV / JSON raw 만

## Decision

**단일 정적 HTML report 채택** (Jinja2 + Chart.js inline).

`scripts/render_report.py` 가 JSON 결과 → HTML 1 파일 생성.

## Why

**공유 가치 우선**:
- HTML 1 파일 = 어떤 사용자/기기에도 offline 으로 열림
- 의사결정자 (admin / 사용자 / 후속 plan 작성자) 가 환경 설치 없이 결과 검토 가능
- 협업 도구 (Slack / 이메일 / 클라우드 드라이브) 로 단순 첨부 공유

**환경 독립**:
- Jupyter notebook → kernel 실행 환경 필요, nbviewer 의존
- Streamlit/Gradio → 서버 띄워야, 인터넷 환경 필요
- HTML → 브라우저 1개로 충분

**개발 비용**:
- Jinja2 + Bootstrap CSS + Chart.js CDN inline → 단순
- template 재사용 가능 (Phase 2, 후속 plan)

## Alternatives Considered

| 옵션 | 거부 사유 |
|---|---|
| Jupyter notebook | kernel/환경 의존, nbviewer 없으면 공유 어려움 |
| Streamlit / Gradio | 서버 띄우는 부담, offline 공유 불가 |
| CSV / JSON raw 만 | 의사결정자 직접 분석 부담, chart 부재 |

## Consequences

**(+)**:
- 결과 공유 즉시 가능 (브라우저 1개)
- offline 가능 (Chart.js inline 또는 CDN)
- 후속 plan / 다른 ablation 에도 template 재사용

**(−)**:
- interactive 분석은 불가 (sortable table 정도만)
- chart 추가/변경 시 template 수정 필요
- 큰 결과 (100+ row) 시 HTML 파일 크기 ↑ (단 1MB 미만 예상)

## Related

- spec-01 — result JSON schema (HTML 입력)
- spec-04 — render_report.py + Jinja2 template 구체 명세
- planning-01 — Phase 0 환경 준비에 본 결정 반영
