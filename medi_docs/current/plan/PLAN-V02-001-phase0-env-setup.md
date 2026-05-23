---
id: plan-V02-001
type: plan
title: PLAN-V02-001 — Phase 0: 환경 구축
status: draft
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[planning-01-ablation-study]]"
  - "[[spec-02-embedding-interface]]"
  - "[[spec-03-eval-ablation-script]]"
  - "[[spec-04-render-report]]"
  - "[[spec-05-datasets-gt]]"
  - "[[spec-06-metrics]]"
tags: [plan, v0.2, ablation, phase0, env-setup]
---

# PLAN-V02-001 — Phase 0: 환경 구축

## 한 줄

4개 embedding 모델 설치 + 데이터셋 정리 + eval_ablation.py + render_report.py 구현으로 e2e smoke 통과.

## 목표

Phase 1 grid 실행을 위한 모든 인프라 준비. 코드 0 line 변경 없이 e2e smoke (1 row JSON → HTML) 통과가 DoD.

## 실행 단위 (step별)

| step | 입력 | 출력 | 검증 | 의존 |
|------|------|------|------|------|
| 001-1 | spec-02 | 4 embedding 모델 install + Python wrap (`eval/embeddings/*.py`) | 각 모델 `extract(audio)` smoke 통과 | spec-02 |
| 001-2 | spec-05 + 사용자 보유 audio | `eval/data/` 데이터셋 정리 + ground truth RTTM | sample 1개 RTTM 파일 존재 | spec-05 |
| 001-3 | spec-03 + spec-06 | `scripts/eval_ablation.py` 구현 | smoke (모델 1 × sample 1 × 조합 1) 1 row JSON 출력 | spec-03, spec-06 |
| 001-4 | spec-04 + spec-01 schema | `scripts/render_report.py` + `templates/ablation_report.html` 구현 | smoke (1 row JSON → HTML 1 chart) | spec-04, spec-01 |
| 001-5 | step 001-1~4 | e2e smoke: pyannote × record_1.wav × 1 조합 → HTML 1 row | HTML 열림 + chart 렌더 | 모든 step |

## step별 상세

### step 001-1: embedding 모델 wrap

**목적**: 4 모델을 동일 Protocol 로 추상화 (spec-02)

```
eval/embeddings/
    __init__.py
    base.py         # EmbeddingProtocol ABC
    pyannote.py     # PyannoteEmbedding
    ecapa.py        # ECAPAEmbedding (SpeechBrain)
    wespeaker.py    # WeSpeakerEmbedding
    titanet.py      # TitaNetEmbedding (NeMo)
```

검증: `python -c "from eval.embeddings.pyannote import PyannoteEmbedding; e = PyannoteEmbedding(); print(e.extract(audio).shape)"`

### step 001-2: 데이터셋 정리

**목적**: AMI 4 session + 한국어 N sample → RTTM 형식 (spec-05)

```
eval/data/
    ami/
        ES2002a.wav, ES2002a.rttm
        ES2002b.wav, ES2002b.rttm
        ES2002c.wav, ES2002c.rttm
        ES2002d.wav, ES2002d.rttm
    korean/
        record_1.wav, record_1.rttm
        ...
```

### step 001-3: eval_ablation.py 구현

**목적**: 단일 조합 1회 측정 → JSON 1 row (spec-03)

CLI: `python scripts/eval_ablation.py --model pyannote --window 5.0 --step 0.5 --audio eval/data/ami/ES2002a.wav`

출력 schema (spec-01):
```json
{
  "model": "pyannote",
  "window_s": 5.0,
  "step_s": 0.5,
  "scheduler": "baseline",
  "sample": "ES2002a",
  "der": 0.142,
  "latency_cluster_s": 8.3,
  "latency_label_s": 0.8,
  "cpu_peak_pct": 42.1,
  "ram_peak_mb": 1024,
  "cold_load_s": 3.2,
  "total_runtime_s": 187.4
}
```

### step 001-4: render_report.py 구현

**목적**: JSON → HTML (Chart.js, spec-04)

CLI: `python scripts/render_report.py --input results/run_001.json --output reports/ablation_001.html`

### step 001-5: e2e smoke

```bash
# 1개 조합 전체 파이프라인
python scripts/eval_ablation.py --model pyannote --window 5.0 --step 0.5 \
  --audio eval/data/ami/ES2002a.wav --output results/smoke.json

python scripts/render_report.py --input results/smoke.json --output reports/smoke.html

# HTML 열어서 chart 확인
open reports/smoke.html
```

## DoD

- [ ] 4 embedding wrap `extract()` smoke 통과
- [ ] 데이터셋: AMI 4 session + 한국어 최소 1개 RTTM 정리 완료
- [ ] `eval_ablation.py` 1 row JSON 출력 가능
- [ ] `render_report.py` HTML 출력 가능
- [ ] e2e smoke (pyannote × ES2002a.wav × 1 조합 → HTML) 성공

## 금지

- GPU 연산 (device="cpu" 강제)
- Phase 1 grid 실행 (→ PLAN-V02-002)
- spec 변경 (이미 박힘)

## 후속 plan

→ PLAN-V02-002-phase1-grid.md (Phase 1 grid 실행)

## 참조

- spec-01: ablation grid schema
- spec-02: embedding interface protocol
- spec-03: eval_ablation.py spec
- spec-04: render_report.py spec
- spec-05: datasets + ground truth
- spec-06: metrics 측정 방법
