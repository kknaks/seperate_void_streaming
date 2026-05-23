# medi_docs/current 인덱스

v0.4 — 2026-05-23

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
                                            ├── plan/PLAN-V03-001-demo-env.md  [draft]
                                            └── retrospective/v03-realtime.md  [done]
                                                    └── planning/planning-03-operational.md  [draft]
                                                            └── plan/PLAN-V04-001-live-latency.md  [draft]
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
| planning-03 | planning-03-operational.md | draft | v0.3 demo 의 운영 수준 완성 — enrollment + 라이브 측정 + UI + docs (Phase 4) |

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
| plan-V04-001 | PLAN-V04-001-live-latency.md | draft | 라이브 latency hook + 2 embedding × 2 sample 실 측정 + HTML report |

### retrospective/

| id | 파일 | status | 한 줄 |
|----|------|--------|-------|
| retrospective-phase1 | phase1-analysis.md | draft | Phase 1 분석 — pyannote w=2.0 s=0.5 1순위 (DER 0.199, 16s realtime), 북극성 미달, Phase 2 scheduler 시도 |
| retrospective-v02-final | v02-final.md | accepted | **v0.2 최종** — pyannote × w=2.0 × s=0.5 × baseline 채택. scheduler 효과 미미 검증 (wrapper 폐기 결정 검증). Phase 3 demo 별도 plan 으로 |
| retro-v03-realtime | v03-realtime.md | done | **v0.3 Phase 3** — pyannote 1순위 재확인 (live DER avg 0.224). 라이브 매핑 검증. latency 측정 공식 한계 노출 → Phase 4 개선 필요 |
| retrospective-v04-live-latency | v04-live-latency.md | draft | **v0.4 라이브 latency** — pyannote 진짜 wall-clock p50 1.5s / p95 2.4s. v0.3 음수 공식 보정. 운영 SLA 평가 |

### release-notes/

| id | 파일 | status | 한 줄 |
|----|------|--------|-------|
| release-v04-operational-guide | v04-operational-guide.md | accepted | **v0.4 운영 가이드** — pyannote w=2.0 s=0.5 baseline + Azure B2s + SLA 박제 (배포 가능 수준 확정) |

### test/ runbook/

(미작성)
