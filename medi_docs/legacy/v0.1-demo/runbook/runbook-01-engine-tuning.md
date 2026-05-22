---
id: runbook-01
type: runbook
title: engine V-01 tuning baseline — DER 측정 결과 + grid sweep + 한계 박제
status: draft
created: 2026-05-19
updated: 2026-05-19
sources:
  - "[[planning-02-speaker-engine]]"
  - "[[spec-05-test-strategy]]"
  - "[[spec-04-clustering-algorithms]]"
  - "[[adr-08-final-recluster-strategy]]"
  - "[[plan-01-speaker-engine]]"
tags: [runbook, speaker-engine, der, baseline, v1, eval]
---

# runbook-01 — engine V-01 tuning baseline

## Summary

V-01 의 DER 측정 baseline + grid tuning 결과 + 한계 박제. v1.1+ 의 재튜닝은 본 runbook 의 기준값 + 발견된 한계 위에서 진행.

---

## §1 목적

V-01 의 본래 목적([[plan-01-speaker-engine]] §2 Phase 6) = "DER 베이스라인 측정 가능 상태 + 첫 숫자 박제 + spec-04/adr-08 default 갱신".

T-023~T-024c 과정을 거쳐 달성한 내용:

- **AMI ES2002a baseline 20.89%** (Bug-B + BUG-FINAL-1 fix 후, pyannote-3.0 reference 19.74% 와 사실상 동등)
- **AMI corpus avg 19.95% ±7.73%p** (4 session) — variance 큼
- **grid sweep best = default** → spec-04/adr-08 default 갱신 **불필요**
- **hungarian_threshold** = pyannote.metrics label-invariance 로 DER eval 영향 무 → OQ-04-2 closure

**SLA <15% 달성 여부는 본 task scope 외**:
- AMI ≠ 의료 도메인 (영어 회의실 4 화자 distant mic vs 한국어 의료 1+1~3 single mic)
- customer SLA 의 정확한 DER 정의 (collar/skip_overlap/dataset/평균 방식) 미확인
- 진짜 SLA 평가는 도메인 audio 측정 후 가능

---

## §2 측정 환경

| 항목 | 값 |
|---|---|
| **session** | AMI ES2002a / ES2003a / ES2008a / IS1000a (4 session) |
| **audio** | diarizers-community/ami IHM-mix (= pyannote 벤치 IHM-mix 와 동일 stream) |
| **DER kwargs** | `collar=0.25, skip_overlap=True` (pyannote 표준) |
| **pipeline** | speaker_engine baseline (`delta_new=1.0, hungarian_threshold=0.5, hdbscan_epsilon=0.3`) |
| **reference (manual)** | pyannote-3.0 manual annotation |
| **reference (official)** | pyannote/speaker-diarization-3.1 inference |
| **측정 도구** | `speaker_engine/eval/der.py` + `pyannote.metrics` |
| **환경** | `.venv-py311` (Python 3.11) + HF_TOKEN (auto-load via `.env`) |
| **seed** | 42 (고정) |

---

## §3 측정 결과

### §3-1. ES2002a baseline 변천

| 단계 | DER | 변화 |
|---|---|---|
| T-023 (harness 최초) | 70.78% | 기준 |
| T-023e (Bug-B fix: per-run segment) | 27.62% | Δ−42.58%p |
| T-023f (BUG-FINAL-1 fix: adaptive min_cluster_size) | 20.89% | Δ−6.73%p |
| pyannote-3.0 manual reference | 19.74% | +1.15%p 격차 |
| pyannote-3.1 official reference | 16.68% | +4.21%p 격차 |

### §3-2. multi-session corpus

| session | duration | ref 화자 | 우리 DER | pyannote-3.1 DER | n_spk detected (p3.1) | 격차 |
|---|---|---|---|---|---|---|
| ES2002a | 1272.6s | 4 | 20.89% | 16.68% | 4 | +4.21%p |
| ES2003a | 1139.8s | 4 | 17.19% | **8.12%** | 4 | +9.07%p |
| ES2008a | 1043.4s | 4 | **10.16%** | **8.49%** | 5 | +1.67%p |
| IS1000a | 1582.7s | 4 | **31.55%** | 18.26% | 5 | +13.29%p |
| **corpus avg** | — | — | **19.95% ±7.73%p** | **12.89%** | — | **+7.06%p** |

**outcome 분기 (ε)** — 우리 corpus avg 19.95% (≈20%) + pyannote-3.1 corpus avg **12.89% ≤ SLA 15% 통과**.
→ pyannote-3.1 wrap 전환 (DiartAdapter 교체) 으로 SLA 달성 가능 (AMI 기준, 이론상).
→ ES2002a 만 봤을 때 (16.68%) 결론과 다름 — multi-session corpus avg 가 더 좋음. 단일 session 단정의 위험성 확인.

### §3-3. grid sweep 결과

격자 구성: `delta_new {0.4, 0.6, 0.8, 1.0}` × `hungarian_threshold {0.3, 0.5, 0.7}` × `hdbscan_epsilon {0.1, 0.3, 0.5}` = 36점

| sweep | train 구간 | best params | full session DER |
|---|---|---|---|
| T-024 | 0–300s | (1.0, 0.5, 0.5) | 20.89% |
| T-024b | 60–360s (speech-dense) | (0.4, 0.3, 0.1) | 21.25% |

두 sweep 모두 full session DER ~20–21% 수렴 — **grid tuning 으로 추가 개선 한계** 확인.

**결론: best = default → spec-04/adr-08 default 파라미터 변경 불필요.**

---

## §4 발견된 한계

1. **단일 session 분포 불충분**: variance ±7.73%p. ES2008a 10% / IS1000a 32% — session 도메인 특성에 강한 의존. 단일 session 결과로 일반화 불가.

2. **300s proxy split unreliable**: T-024 (0–300s train) 과 T-024b (60–360s speech-dense train) 의 best params ranking 완전 역전. AMI 1 session 의 임의 300s 구간 = grid tuning proxy 로 부적합.

3. **hungarian_threshold label-invariance**: pyannote.metrics 가 optimal speaker-alignment 자동 적용(Hungarian matching) → 라벨 변경이 DER 에 무영향. eval grid 에서 무의미한 파라미터. 단, 실시간 streaming label consistency (사용처 DB 안정성) 에는 유효한 파라미터.

4. **AMI ≠ 우리 의료 도메인**: AMI = 영어 회의실 4 화자 distant mic. 우리 대상 = 한국어 의료 상담 1+1~3 화자 single mic. 환경/언어/화자 수 모두 다름 — 점수 일반화 보장 X.

---

## §5 후속 작업 (v1.1+ 또는 별도 plan)

- **도메인 audio 측정 환경**: 실 의료 상담 sample 확보 (또는 자체 녹음) + 라벨링 + DER 측정 (AMI 점수와 비교)
- **customer SLA 정의 확인**: collar / skip_overlap / dataset / 평균 방식 명확화 (현 가정: pyannote 표준)
- **multi-session corpus tuning**: 단일 session proxy 한계 명확 → 도메인 corpus 확보 후 grid 재실행
- **구조 fix 후보** (도메인 측정으로 정당화될 경우):
  - Bug-A: pyannote segmentation onset/offset 조정 또는 VAD layer 추가 — 실시간 호환 (chunk-by-chunk 유지)
  - 새 모델 (재학습 또는 다른 backbone) — 실시간 호환 확인 필요

> **pyannote-3.1 official pipeline 전환 옵션 폐기 (2026-05-19)**: T-024c 측정 결과 corpus avg 12.89% 도달 가능하나, **offline batch pipeline** 으로 elapsed 2475s vs audio 1272s (1.94× real-time) — 우리 KPI "실시간 지연 < 2초" 위반. streaming 호환 X 라 wrap 전환 자체 불가능. 정확도 개선 후보에서 제외.

---

## §6 정합 박제

| OQ | 내용 | 상태 | 근거 |
|---|---|---|---|
| OQ-04-2 (spec-04) | hungarian_threshold 도메인 임계 결정 | **closed (V-01)** | §3-3 + §4-(3): pyannote.metrics label-invariance 로 DER eval 무의미. streaming label consistency 에는 유효. label-fixed DER 도입 시 v1.1 재논의 |
| OQ-04-1 (spec-04) | delta_new 도메인 임계 결정 | **deferred (v1.1)** | §5: 도메인 audio 측정 후 재튜닝 |
| OQ-08-1 (adr-08) | hdbscan_epsilon 도메인 임계 결정 | **deferred (v1.1)** | §5: 도메인 audio 측정 후 재튜닝 |

spec-05 §3-2 dataset (AMI 1 session) → 본 runbook 데이터로 확장 (4 session) 박제.

---

## §7 재현

모든 측정은 다음 스크립트로 재현 가능:

```bash
# single session baseline
python scripts/measure_p31_single.py

# multi-session corpus
python scripts/run_p31_all.py

# grid sweep (0-300s train)
python scripts/run_grid_sweep.py

# grid sweep (60-360s speech-dense train)
python scripts/run_grid_sweep_v2.py

# unit test baseline
pytest tests/eval/test_der_baseline.py
```

JSONL 누적 결과: `tests/eval/results.jsonl` (`.gitignore` 포함, 커밋 X).  
seed=42 고정.
