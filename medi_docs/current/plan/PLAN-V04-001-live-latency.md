---
id: plan-V04-001
type: plan
title: PLAN-V04-001 — 라이브 latency 측정 hook + 실 라이브 ablation
status: draft
created: 2026-05-23
updated: 2026-05-23
sources:
  - "[[planning-03]]"
tags: [plan, v0.4, latency, ablation, hook, measurement]
---

# PLAN-V04-001 — 라이브 latency 측정 hook + 실 라이브 ablation

## 한 줄

demo_v03.py 의 stt_loop / pcm_loop 에 **wall-clock latency hook** 추가 → 2 embedding × 2 sample = 4 row 실 라이브 측정 → HTML report + retrospective.

## 목표

v0.3 ablation 의 latency 측정 한계 해소:
- v0.3: `wallclock_at_emit − audio_t_end_of_window` → audio 재생 전체 길이에 비례하는 음수 도메인 (실용 지표 부적합)
- **v0.4**: PCM 청크 도착 timestamp (`t_recv`) → labeled_phrase emit timestamp (`t_emit`) 진짜 wall-clock 차이

## 실행 단위

| step | 입력 | 출력 | 검증 |
|---|---|---|---|
| 001-1 | demo_v03.py stt_loop / pcm_loop | latency hook 추가 — PCM 청크 도착 `t_recv` + labeled_phrase emit `t_emit` 기록 | mock 시나리오 + 1초 audio chunk → latency 1 row 측정 (p50 계산 가능) |
| 001-2 | 001-1 | 세션 종료 시 JSON 저장 (`eval/ablation/results/v04/live-{visit_id}.json`) — rows + p50/p95 | 세션 종료 후 파일 생성 + p50/p95 계산값 포함 |
| 001-3 | record_1.wav + record_3.wav 자동 재생 + 측정 | 실 라이브 측정 — 2 embedding × 2 sample = 4 row | JSON 4개 생성 (eval/ablation/results/v04/) |
| 001-4 | 001-3 JSON 4개 | HTML report (`eval/ablation/results/v04/v04-live-latency-YYYYMMDD.html`) — latency 분포 chart + v0.3 와 비교 | 차트 포함 HTML 렌더링 확인 |
| 001-5 | 001-4 + 분석 | `retrospective/v04-live-latency.md` 작성 + `_map.md` INDEX 갱신 | 운영 환경 라이브 latency 박제 |

## step 상세

### step 001-1: latency hook

**목적**: PCM 청크 수신 시점(`t_recv`)을 기록하고, 해당 청크에서 파생된 labeled_phrase 가 emit 될 때 `t_emit` 차이를 기록.

```python
# 측정 공식
latency_s = t_emit - t_recv  # 양수 = emit 지연, 음수 = 선행 처리
```

기록 단위: phrase emit 1회당 1 row.

```python
# 컬럼
{
  "visit_id": str,
  "embedding": str,          # "pyannote" | "ecapa-tdnn"
  "sample": str,             # "record_1" | "record_3"
  "t_recv": float,           # time.monotonic() at PCM chunk arrive
  "t_emit": float,           # time.monotonic() at labeled_phrase emit
  "latency_s": float,        # t_emit - t_recv
  "label": str               # "A" | "B" | "unknown"
}
```

> `t_recv` 는 demo_v03 pcm_loop 에서 PCM 청크 도착 즉시 기록. diart 는 슬라이딩 윈도우 기반이므로 `t_recv` = 해당 window 의 마지막 PCM 청크 도착 시점.

### step 001-2: JSON 저장

파일: `eval/ablation/results/v04/live-{visit_id}.json`

```json
{
  "visit_id": "...",
  "embedding": "pyannote",
  "sample": "record_1",
  "p50_s": 0.0,
  "p95_s": 0.0,
  "rows": [...]
}
```

### step 001-3: 실 라이브 측정

측정 grid:

| embedding | sample | 파일 |
|---|---|---|
| pyannote/embedding | record_1.wav (277.5s) | live-pyannote-record1.json |
| pyannote/embedding | record_3.wav (168.2s) | live-pyannote-record3.json |
| ecapa-tdnn | record_1.wav (277.5s) | live-ecapa-record1.json |
| ecapa-tdnn | record_3.wav (168.2s) | live-ecapa-record3.json |

재생: sample audio 자동 재생 (실 WS 라이브 스트리밍 환경).

### step 001-4: HTML report

포함 요소:
- latency 분포 (histogram / box plot)
- p50 / p95 비교 테이블 (2 embedding × 2 sample)
- v0.3 ablation latency 와 비교 (측정 공식 차이 주석 포함)

### step 001-5: retrospective

파일: `retrospective/v04-live-latency.md`

포함:
- 측정 조건 (embedding, sample, hook 공식)
- 4 row 결과 테이블 (p50 / p95)
- v0.3 대비 개선된 측정 공식 해설
- 운영 환경 판단 (latency SLA 달성 여부)
- 후속 PLAN-V04-002 (enrollment) 진입 권고

## DoD

- [ ] demo_v03 latency hook 작동 (1 row 측정값 확인)
- [ ] 4 row 실 라이브 측정 JSON 생성
- [ ] HTML report 렌더링 확인
- [ ] `retrospective/v04-live-latency.md` 작성
- [ ] `_map.md` INDEX 갱신

## 금지

- enrollment 구현 X (PLAN-V04-002 영역)
- UI 변경 X (PLAN-V04-003 영역)
- 코드 리팩터 X (측정 hook 추가만)
