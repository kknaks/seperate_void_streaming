---
id: plan-V03-001
type: plan
title: PLAN-V03-001 — Phase 3 환경 구축 + legacy 자산 통합
status: draft
created: 2026-05-23
updated: 2026-05-23
sources:
  - "[[planning-02-demo]]"
tags: [plan, v0.3, demo, env-setup, skeleton]
---

# PLAN-V03-001 — Phase 3 환경 구축 + legacy 자산 통합

## 한 줄

v0.2 산출 + legacy 자산으로 `examples/demo_v03.py` skeleton 신설 — diart + STT + 빈 mapping + UI 4-panel 연결 e2e smoke 통과.

## 목표

PLAN-V03-002 (server WS audio_ws chain) 실행을 위한 인프라 준비. 코드 신규 구현 최소화, legacy 자산 재활용 중심. e2e smoke (WS open + 4-panel 표시) 가 DoD.

> 실시간 라벨링 매핑은 **미구현** (PLAN-V03-002 영역). 본 plan 은 skeleton + 연결성 검증만.

---

## 실행 단위

| step | 입력 | 출력 | 검증 |
|------|------|------|------|
| 001-1 | v0.2 산출 + legacy 자산 | `examples/demo_v03.py` skeleton — diart + STT + 빈 mapping skeleton, WS `/audio/{visit_id}` | `uvicorn ... /audio/{visit_id}` 접속 + WS open 확인 |
| 001-2 | 001-1 | diart streaming inference 통합 — `pyannote/embedding`, w=2.0, s=0.5, baseline scheduler | mock PCM 1초 → segment emit (server log) |
| 001-3 | 001-2 | ElevenLabs Realtime STT 통합 — legacy `server/stt/elevenlabs.py` 그대로 재활용 | mock 또는 실 audio → STT partial/final emit (server log) |
| 001-4 | 001-1 | UI 4-panel 연결 — legacy `web/index.html` 재활용, WS 이벤트 핸들러 그대로 | 브라우저 접속 → 4-panel 표시 (음파/RMS, STT 자막, 라벨링, final_grouped) |
| 001-5 | 모든 step | e2e smoke — mock PCM 또는 record_1.wav 1분 슬라이스 → 모든 wire 정상 작동 | 우상 STT / 우중 labeled_phrase wire (빈) / 우하 final 표시 |

---

## step 상세

### step 001-1: demo_v03.py skeleton

**목적**: WS endpoint `/audio/{visit_id}` 신설. PCM 수신 + diart / STT 양쪽에 fan-out 예약.

```python
# examples/demo_v03.py (skeleton)
# FastAPI + WebSocket endpoint
# /audio/{visit_id}  — PCM binary 수신 → fan-out placeholder
# /  — web/index.html 서빙
```

재활용:
- `server/audio/ringbuffer.py` (PcmRingBuffer)
- `docker-compose.yml` (서비스 정의 참조)

검증: `curl -s http://localhost:8000/` → index.html 응답, `wscat -c ws://localhost:8000/audio/test` → WS open 유지

### step 001-2: diart streaming inference 통합

**목적**: WS PCM stream → diart `StreamingInference` → `SpeakerSegment` emit.

설정 고정:
```python
embedding = "pyannote/embedding"  # v0.2 최적
window_s  = 2.0
step_s    = 0.5
scheduler = None  # baseline (diart 기본)
```

검증: mock 1초 PCM `np.zeros((16000,), dtype=np.float32)` → server log 에 `segment(speaker=..., t_start=..., t_end=...)` 출력

### step 001-3: ElevenLabs Realtime STT 통합

**목적**: WS PCM fan-out → `server/stt/elevenlabs.py` 재활용 → `partial` / `final` STT emit.

legacy 재활용 그대로:
```python
from server.stt.elevenlabs import ElevenLabsSTT  # legacy 그대로
from server.stt.vad import ServerVAD              # legacy 그대로
```

설정:
```python
commit_strategy = "manual"  # 또는 vad
```

환경: `ELEVENLABS_API_KEY` env 필요 (`.env` 또는 shell export)

검증: mock 또는 실 audio 100ms chunk → server log 에 `stt.partial: ...` 또는 `stt.final: ...` 출력

### step 001-4: UI 4-panel 연결

**목적**: legacy `web/index.html` WS 이벤트 핸들러 재활용 → 4-panel grid 표시.

4-panel 구성 (legacy 그대로):
| panel | 위치 | 내용 |
|-------|------|------|
| 음파/RMS | 좌상 | AudioWorklet 실시간 waveform |
| STT 자막 | 우상 | ElevenLabs partial/final |
| 라벨링 (빈) | 우중 | labeled_phrase — 001-5 에서 비어도 OK |
| final_grouped | 우하 | 최종 화자-텍스트 그루핑 |

재활용: `web/worklet-processor.js` (AudioWorklet PCM capture)

검증: `http://localhost:8000/` 브라우저 접속 → 4-panel grid 렌더링 + 오류 없음

### step 001-5: e2e smoke

**목적**: 모든 wire 연결 검증 — 빈 labeled_phrase 로도 정상 동작 확인.

```bash
# 환경 시작
uvicorn examples.demo_v03:app --host 0.0.0.0 --port 8000

# 브라우저 접속
open http://localhost:8000/

# 또는 mock PCM (record_1.wav 1분 슬라이스)
python scripts/smoke_v03.py --audio eval/data/korean/record_1.wav --duration 60
```

성공 기준:
- WS open + 유지 (연결 끊김 없음)
- diart segment emit (server log)
- STT partial/final emit (server log)
- 브라우저 4-panel 표시 (음파 + STT 자막 — labeled_phrase 는 비어도 OK)

---

## 의존성

```
diart==0.9.2
pyannote.audio==3.1.1
torch==2.1.*
fastapi
uvicorn
websockets
python-dotenv
ELEVENLABS_API_KEY  (env)
```

> GPU 필요 없음 — `device="cpu"` 강제.

---

## DoD

- [ ] `examples/demo_v03.py` 동작 (WS endpoint + diart + STT + UI 서빙)
- [ ] diart segment emit 확인 (server log)
- [ ] STT partial/final emit 확인 (server log)
- [ ] 브라우저 4-panel 표시 확인
- [ ] e2e smoke 성공 (mock 또는 record_1.wav 1분)

## 금지

- 실시간 라벨링 매핑 구현 X (→ PLAN-V03-002)
- `speaker_engine/` wrapper 코드 신규 사용 X (adr-01 폐기 결정)
- PLAN-V03-002 / 003 / 004 구현 X
- legacy 자산 (server/, web/) 코드 리팩토링 X (재활용만)

## 후속 plan

→ PLAN-V03-002: server WS audio_ws chain — diart SpeakerSegment ↔ STT phrase 시간 overlap mapping → labeled_phrase wire 구현.
