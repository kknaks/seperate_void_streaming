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
                    │     └── adr/adr-02-html-report.md       [accepted]
                    ├── spec/spec-05-datasets-gt.md           [draft]
                    ├── spec/spec-06-metrics.md               [draft]
                    ├── plan/PLAN-V02-001-phase0-env-setup    [draft]
                    ├── plan/PLAN-V02-002-phase1-grid         [draft]
                    └── plan/PLAN-V02-003-phase2-scheduler    [draft]
                            └── retrospective/v02-final.md    [accepted]
                                    └── planning/planning-02-demo.md  [draft]
                                            └── plan/PLAN-V03-001-demo-env.md  [draft]
```

## 문서 목록

### adr/

| id | 파일 | status | 한 줄 |
|----|------|--------|-------|
| adr-01 | adr-01-ablation-centric-design.md | accepted | wrapper 폐기 + ablation-centric 정체성 채택 |
| adr-02 | adr-02-html-report.md | accepted | ablation 결과는 단일 HTML report 로 공유 (offline + 환경 독립) |

### planning/

| id | 파일 | status | 한 줄 |
|----|------|--------|-------|
| planning-01 | planning-01-ablation-study.md | draft | embedding × window × scheduler ablation study Phase 0~2 |
| planning-02 | planning-02-demo.md | draft | v0.2 ablation 최적 조합 기반 실시간 화자 분리 + STT demo (Phase 3) |

### spec/

| id | 파일 | status | 한 줄 |
|----|------|--------|-------|
| spec-01 | spec-01-ablation-grid.md | draft | ablation grid 48 combinations + JSON result schema + CSV 매핑 |
| spec-02 | spec-02-embedding-interface.md | draft | 4 embedding 모델 통일 Protocol + diart 주입 wrap |
| spec-03 | spec-03-eval-ablation-script.md | draft | eval_ablation.py CLI + 실행 흐름 + resume/에러 처리 |
| spec-04 | spec-04-render-report.md | draft | render_report.py + Jinja2 HTML template + Chart.js 차트 |
| spec-05 | spec-05-datasets-gt.md | draft | AMI 4세션 + 한국어 N개 데이터셋 위치 + RTTM 형식 |
| spec-06 | spec-06-metrics.md | draft | DER / latency / 리소스 / cold-load 측정 방법 명세 |

### plan/

| id | 파일 | status | 한 줄 |
|----|------|--------|-------|
| plan-V02-001 | PLAN-V02-001-phase0-env-setup.md | draft | 4 embedding 모델 wrap + 데이터셋 + eval_ablation.py + render_report.py e2e smoke |
| plan-V02-002 | PLAN-V02-002-phase1-grid.md | draft | 48조합 pilot + cross-sample validation → 최적 후보 3~5개 선정 |
| plan-V02-003 | PLAN-V02-003-phase2-scheduler.md | draft | Phase 1 최적 × scheduler 4종 측정 → 최종 최적 조합 결정 |
| plan-V03-001 | PLAN-V03-001-demo-env.md | draft | Phase 3 환경 구축 + legacy 자산 통합 + diart + STT + UI skeleton e2e smoke |

### retrospective/

| id | 파일 | status | 한 줄 |
|----|------|--------|-------|
| retrospective-phase1 | phase1-analysis.md | draft | Phase 1 분석 — pyannote w=2.0 s=0.5 1순위 (DER 0.199, 16s realtime), 북극성 미달, Phase 2 scheduler 시도 |
| retrospective-v02-final | v02-final.md | accepted | **v0.2 최종** — pyannote × w=2.0 × s=0.5 × baseline 채택. scheduler 효과 미미 검증 (wrapper 폐기 결정 검증). Phase 3 demo 별도 plan 으로 |

### test/ runbook/ release-notes/

(미작성 — v0.2 진행 중)
