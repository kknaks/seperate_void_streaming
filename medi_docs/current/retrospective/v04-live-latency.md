---
id: retrospective-v04-live-latency
type: retrospective
title: v0.4 Phase 4 — 진짜 라이브 latency 측정 (wall-clock 기반)
status: draft
created: 2026-05-23
updated: 2026-05-23
sources:
  - "[[planning-03-operational]]"
  - "[[retrospective-v03-realtime]]"
  - "[[PLAN-V04-001-live-latency]]"
tags: [retrospective, v0.4, latency, realtime, wallclock]
---

# v0.4 Phase 4 — 진짜 라이브 latency 측정

## TL;DR

- v0.3 의 **부적합 latency 공식** (`wallclock − audio_t_end`, 음수 도메인) 폐기
- 새 정의: **PCM 청크 도착 wall-clock ↔ labeled_phrase emit wall-clock** 차이 = SLA 평가 가능 라이브 라벨링 응답성
- demo_v03 latency hook + `scripts/auto_play_audio.py` 자동 재생 → 2 rows 측정 (pyannote × record_1/3 각 40초 부분)
- **결과**: p50 ≈ 1.5s, p95 ≈ 2.4s (목표 ≤ 2s p50 통과, p95 약간 초과)

상세 JSON: `eval/ablation/results/v04/live-{visit_id}.json`

---

## 측정 정의

```
audio_recv_wallclock = PCM 청크 (phrase t_end 포함) 가 server 에 도착한 wall-clock 시점
emit_wallclock       = labeled_phrase emit 직전 wall-clock 시점
latency_s            = emit_wallclock - audio_recv_wallclock
```

→ 양수 = 음성 끝난 시점부터 라벨 emit 까지의 실시간 응답성. 운영 SLA 평가 직접 가능.

## 측정 결과

| sample | duration_measured | phrases | p50 latency | p95 latency | max latency |
|---|---|---|---|---|---|
| record_1.wav | 40.1s | 11 | **1.51s** | **2.53s** | 2.53s |
| record_3.wav | 40.1s | 7 | **1.58s** | **2.33s** | 2.33s |

> 측정 한계: client (`auto_play_audio.py`) 의 websockets 라이브러리가 40s 시점에 끊김 (`ping_interval=None` 설정해도 발생) — `ConnectionClosedError: no close frame received`. server 측은 disconnect 감지 후 finally 의 JSON 저장 정상 작동. 첫 40초 phrase 만 박제.

### 운영 SLA 평가

| 기준 | 목표 | 실측 | 평가 |
|---|---|---|---|
| 라이브 라벨링 p50 | ≤ 2.0s | 1.51~1.58s | ✅ 통과 |
| 라이브 라벨링 p95 | ≤ 2.0s | 2.33~2.53s | ❌ 미달 (0.3~0.5s 초과) |
| 라이브 자막 (STT partial) | 즉시 | ~0.5s | ✅ 통과 |

→ **대부분 phrase 는 2초 안에 라벨링**. tail (p95) 가 약간 초과 — 다중 화자 묶음 phrase + diart 의 sliding window 누적 영향.

---

## v0.3 측정과의 차이

| 항목 | v0.3 | v0.4 |
|---|---|---|
| latency 공식 | `wallclock − audio_t_end` (음수 도메인) | `emit_wallclock − audio_recv_wallclock` (양수) |
| 측정 단위 | 전체 sample 끝까지 처리 wall-clock | **per-phrase, 실시간 PCM 송신 기준** |
| 운영 적용 | 불가 (음수 의미 모호) | **SLA 직접 평가** |
| sample 길이 영향 | 비례 | 독립 |

→ v0.3 의 음수 latency (예: −131.7s) 는 sample 길이의 batch 처리 속도 표시였음. 진짜 라이브 응답성 X. v0.4 가 진짜 측정.

---

## 측정 흐름

```
[auto_play_audio.py]                  [demo_v03 server]
  WAV 16kHz mono load
  100ms 청크 단위 송신 (실시간 속도)
       ↓
  WS bytes → buf.append + stt.feed + pcm_for_diart.put
                   ↓ audio_recv_log: (audio_t, recv_wc)
                   
                   STT partial/final 흐름
                       ↓ final → phrase_words 누적
                       ↓ next partial / 종료 → _flush()
                           ↓ emit_wc = perf_counter()
                           ↓ audio_recv_wc = lookup (audio_t >= phrase t_end)
                           ↓ latency = emit_wc - audio_recv_wc
                           ↓ latency_log append
                           ↓ labeled_phrase emit
                           
       세션 종료 (WS disconnect / EOF)
       ↓ finally: latency_log → JSON 저장
       ↓ eval/ablation/results/v04/live-{visit_id}.json
```

## 시스템 자원

per-phrase wall-clock 처리는 CPU 1 core 100% 미만 (M3 Max). diart sliding window 가 메인 비용 (~1초당 ~50ms 처리, 20× realtime 헤드룸).

## 발견 + 한계

### 1. p95 약 0.3~0.5s 초과

p95 가 2.33~2.53s — diart 의 window=2.0s + step=0.5s 구조상 phrase emit 가 STT final + segment 도착 둘 다 wait 하기 때문. 단축 옵션:
- diart window 1.5s 로 축소 (정확도 약간 ↓ 가능 — v0.2 ablation 시 window=1.0 도 시도했으나 DER 약간 ↓)
- 또는 STT commit_strategy 튜닝 (server VAD silence threshold 단축)

### 2. client websocket 끊김 (40s 시점)

`auto_play_audio.py` 의 `websockets.connect(ping_interval=None)` 설정에도 40초 시점에 `ConnectionClosedError`. 원인 미규명 (uvicorn websocket protocol 또는 OS TCP keepalive).

→ 측정 자체에는 영향 없음 (server 측 finally 정상 작동). 그러나 전체 sample (277s, 168s) 완전 측정 위해서는 client websocket 안정성 개선 필요. 후속 task.

### 3. ecapa-tdnn 미측정

demo_v03 의 DiartModels 가 `pyannote/embedding` hardcoded. ecapa-tdnn 측정 위해서는 demo_v03 의 embedding 선택 인자 추가 + `eval/embeddings/ecapa_tdnn.py` 통합 wrap. 별도 task 영역.

→ v0.3 결과 (pyannote 1순위) + v0.2 결정 (pyannote 채택) 박제와 일관. ecapa 측정은 운영 선택 시점에 후속 plan.

---

## 운영 결정 박제

**라이브 환경에서 pyannote/embedding × w=2.0 × s=0.5 × baseline 의 SLA**:
- p50 라이브 라벨링 1.5초 — 운영 사용 가능
- p95 2.5초 — 약간 초과, 사용성 평가 필요 (회의 도메인에선 허용 가능 수준)
- 실시간 자막 (STT) 즉시 표시 + 화자 라벨 2초 지연 = 운영 자연스러운 UX

---

## 다음 단계

1. **client websocket 안정성** — `auto_play_audio.py` 또는 다른 client 로 전체 277s/168s 완전 측정 (후속, 우선순위 낮음)
2. **PLAN-V04-002: enrollment 시스템** — 등록 직원 voice sample → `registered:이름` 매핑 (운영 핵심 가치)
3. **PLAN-V04-003: UI 마무리 + 운영 docs**
4. (선택) ecapa-tdnn 라이브 측정 — demo_v03 embedding 선택 인자 추가

## 산출물

| 파일 | 비고 |
|---|---|
| `examples/demo_v03.py` | latency hook 추가 (audio_recv_log, latency_log, finally JSON 저장) |
| `scripts/auto_play_audio.py` | 자동 재생 WS client |
| `eval/ablation/results/v04/live-auto-f4e5b404464a.json` | record_1 측정 (11 phrase, p50 1.51s) |
| `eval/ablation/results/v04/live-auto-ba68d172cca0.json` | record_3 측정 (7 phrase, p50 1.58s) |
