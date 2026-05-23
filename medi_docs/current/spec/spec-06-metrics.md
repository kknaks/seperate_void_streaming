---
id: spec-06
type: spec
title: Metric 측정 방법 명세
status: draft
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[planning-01-ablation-study]]"
  - "[[spec-01-ablation-grid]]"
  - "[[spec-03-eval-ablation-script]]"
tags: [spec, v0.2, metric, der, latency, resource]
---

# spec-06 — Metric 측정 방법 명세

## Summary

ablation 에서 측정하는 모든 metric 의 정의, 측정 도구, 계산 방법, 허용 오차를 명세한다. `eval_ablation.py` 는 이 명세를 구현 기준으로 삼는다.

---

## Metric 목록

### 1. DER (Diarization Error Rate)

| 항목 | 값 |
|------|---|
| 도구 | `pyannote.metrics.diarization.DiarizationErrorRate` |
| 입력 | predicted `Annotation` + ground truth `Annotation` |
| 허용 오차 | 0.25s (pyannote 기본값 — 변경 금지) |
| 범위 | 0 ~ ∞ (100% 초과 가능, 낮을수록 좋음) |
| 주 KPI | **북극성 목표: DER ≤ 0.15** |

```python
from pyannote.metrics.diarization import DiarizationErrorRate

metric = DiarizationErrorRate(collar=0.25)
der_score = metric(reference, hypothesis)
```

`reference` / `hypothesis`: `pyannote.core.Annotation` 객체.  
diart 의 label emit → `pyannote.core.Annotation` 변환 필요.

---

### 2. 초기 Cluster 형성 Latency

| 항목 | 값 |
|------|---|
| 정의 | distinct speaker ≥ 2인 cluster 가 처음 emit된 시점 |
| 측정 | 오디오 시작 타임스탬프 vs 첫 stable cluster emit 타임스탬프 |
| 단위 | 초 (s) |
| 목표 | ≤ 20s (북극성) |

```python
initial_cluster_latency_s = None
for segment, track, label in diarization.itertracks(yield_label=True):
    if len(set(current_labels)) >= 2 and initial_cluster_latency_s is None:
        initial_cluster_latency_s = time.perf_counter() - stream_start_time
```

---

### 3. 라벨링 지연 (p50 / p95)

| 항목 | 값 |
|------|---|
| 정의 | PCM 청크 입력 타임스탬프 → 해당 구간의 label emit 타임스탬프 |
| 측정 단위 | 초 (s) |
| 집계 | 전체 emit 리스트 → `np.percentile(delays, [50, 95])` |
| 목표 | p50 ≤ 3s (북극성) |

```python
delays = []
for chunk_ts, emit_ts in zip(chunk_timestamps, emit_timestamps):
    delays.append(emit_ts - chunk_ts)

p50 = float(np.percentile(delays, 50))
p95 = float(np.percentile(delays, 95))
```

---

### 4. 라벨 일관성

| 항목 | 값 |
|------|---|
| 정의 | 동일 화자(ground truth)에 예측된 label 중 최빈값의 비율 |
| 범위 | 0 ~ 1 (높을수록 좋음) |
| 수식 | `consistency = max_count / total_segments_for_speaker` |

```python
from collections import Counter

def label_consistency(reference: Annotation, hypothesis: Annotation) -> float:
    speaker_label_counts = defaultdict(Counter)
    for segment, _, ref_speaker in reference.itertracks(yield_label=True):
        pred_labels = hypothesis.crop(segment).labels()
        for lbl in pred_labels:
            speaker_label_counts[ref_speaker][lbl] += 1
    
    consistencies = []
    for counter in speaker_label_counts.values():
        total = sum(counter.values())
        if total > 0:
            consistencies.append(counter.most_common(1)[0][1] / total)
    
    return float(np.mean(consistencies)) if consistencies else 0.0
```

---

### 5. CPU 사용률

| 항목 | 값 |
|------|---|
| 도구 | `psutil.Process(os.getpid()).cpu_percent()` |
| 폴링 간격 | 1초 |
| 집계 | peak (최대값), avg (평균) |
| 단위 | % (CPU 코어 수 × 100% 기준) |

```python
proc = psutil.Process(os.getpid())
cpu_samples = []
# monitoring thread 에서:
cpu_samples.append(proc.cpu_percent(interval=None))
time.sleep(1)

cpu_peak_pct = max(cpu_samples)
cpu_avg_pct = float(np.mean(cpu_samples))
```

---

### 6. RAM 사용량

| 항목 | 값 |
|------|---|
| 도구 | `psutil.Process().memory_info().rss` |
| 폴링 간격 | 1초 |
| 집계 | peak (최대), avg (평균) |
| 단위 | MB |

```python
ram_mb = proc.memory_info().rss / 1e6
```

---

### 7. ~~GPU 사용률 + GPU 메모리~~ (제외)

**제외 결정 (2026-05-22)** — Azure CPU instance 운영 가정. 모든 모델 `device="cpu"` 강제로 일관 측정. GPU instance 채택 시 deployment 단계에서 별도 측정.

ablation 결과 JSON schema 에서 `gpu_*` 필드 제외.

---

### 8. 모델 Cold-Load 시간

| 항목 | 값 |
|------|---|
| 정의 | `EmbeddingModel.load()` 시작 ~ 종료 |
| 단위 | 초 (s) |
| 측정 | `time.perf_counter()` |
| 비고 | 배치 내 첫 번째 combination 만 측정 (이미 로드된 경우 0) |

```python
t0 = time.perf_counter()
model.load(device)
cold_load_s = time.perf_counter() - t0
```

---

### 9. Total Runtime

| 항목 | 값 |
|------|---|
| 정의 | 1 combination × 1 sample 전체 처리 시간 |
| 단위 | 초 (s) |
| 측정 | `time.perf_counter()` — combination 시작~종료 |

---

## Metric 요약표

| metric | 도구 | 목표 | 단위 |
|--------|------|------|------|
| DER | pyannote.metrics | ≤ 0.15 | ratio |
| 초기 cluster latency | 자체 | ≤ 20s | s |
| 라벨링 지연 p50 | 자체 | ≤ 3s | s |
| 라벨링 지연 p95 | 자체 | — | s |
| 라벨 일관성 | 자체 | 높을수록 | 0~1 |
| CPU peak/avg | psutil | — | % |
| RAM peak/avg | psutil | — | MB |
| cold-load | perf_counter | — | s |
| total runtime | perf_counter | — | s |

> **GPU 측정 제외** (2026-05-22): Azure CPU instance 운영 가정. 자세한 사유는 본 spec §7.
