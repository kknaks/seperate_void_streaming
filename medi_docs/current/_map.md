# medi_docs/current 인덱스

v0.2 — 2026-05-22

legacy: `medi_docs/legacy/v0.1-demo/`

---

## lineage 그래프

```
legacy/v0.1-demo/LEGACY_NOTE.md
    └── adr/adr-01-ablation-centric-design.md   [accepted]
            └── planning/planning-01-ablation-study.md  [draft]
                    ├── spec/spec-01-ablation-grid.md         [draft]
                    ├── spec/spec-02-embedding-interface.md   [draft]
                    ├── spec/spec-03-eval-ablation-script.md  [draft]
                    ├── spec/spec-04-render-report.md         [draft]
                    ├── spec/spec-05-datasets-gt.md           [draft]
                    └── spec/spec-06-metrics.md               [draft]
```

## 문서 목록

### adr/

| id | 파일 | status | 한 줄 |
|----|------|--------|-------|
| adr-01 | adr-01-ablation-centric-design.md | accepted | wrapper 폐기 + ablation-centric 정체성 채택 |

### planning/

| id | 파일 | status | 한 줄 |
|----|------|--------|-------|
| planning-01 | planning-01-ablation-study.md | draft | embedding × window × scheduler ablation study Phase 0~2 |

### spec/

| id | 파일 | status | 한 줄 |
|----|------|--------|-------|
| spec-01 | spec-01-ablation-grid.md | draft | ablation grid 48 combinations + JSON result schema + CSV 매핑 |
| spec-02 | spec-02-embedding-interface.md | draft | 4 embedding 모델 통일 Protocol + diart 주입 wrap |
| spec-03 | spec-03-eval-ablation-script.md | draft | eval_ablation.py CLI + 실행 흐름 + resume/에러 처리 |
| spec-04 | spec-04-render-report.md | draft | render_report.py + Jinja2 HTML template + Chart.js 차트 |
| spec-05 | spec-05-datasets-gt.md | draft | AMI 4세션 + 한국어 N개 데이터셋 위치 + RTTM 형식 |
| spec-06 | spec-06-metrics.md | draft | DER / latency / 리소스 / cold-load 측정 방법 명세 |

### plan/ test/ runbook/ release-notes/ retrospective/

(미작성 — v0.2 진행 중)
