---
id: spec-07
type: spec
title: 데모 UI WS 프로토콜 — json 이벤트 스키마 + 클라이언트 책임
status: draft
created: 2026-05-20
updated: 2026-05-20
sources:
  - "[[planning-02-speaker-engine]]"
  - "[[planning-03-demo-v04]]"
tags: [spec, websocket, json-schema, demo-ui, protocol, pcm16]
---

# 데모 UI WS 프로토콜 — json 이벤트 스키마 + 클라이언트 책임

## Summary

`examples/fastapi_ws_demo.py` 의 WS 핸들러(lines 50-121)를 정식화한 문서. 바이너리 입력(PCM16) / 텍스트 출력(JSON) 계약 + 클라이언트 PCM 변환 가이드 + 종료 프로토콜.

---

## §1 WS Endpoint 계약

```
ws://host/audio/{visit_id}
```

| 방향 | 포맷 | 내용 |
|---|---|---|
| 클라이언트 → 서버 | 바이너리 | PCM 16-bit signed LE, 16kHz, mono |
| 클라이언트 → 서버 | 텍스트 JSON | `{"type":"eof"}` — 종료 시그널 (선택, 권장) |
| 서버 → 클라이언트 | 텍스트 JSON | 4종 이벤트 (`utterance`, `relabel`, `done`, `error`) |

`{visit_id}` — 세션 식별자 (임의 문자열, URL-safe). 현재 데모는 영속화하지 않음 (`memory://` 스토어).

---

## §2 클라이언트 → 서버 (오디오 전송)

### PCM 포맷 요구사항

| 항목 | 값 | 근거 |
|---|---|---|
| 샘플 포맷 | PCM 16-bit signed LE | spec-03 §2 + engine 입력 계약 |
| 샘플레이트 | 16kHz | spec-03 §2 (diart 입력 제약) |
| 채널 | mono (1ch) | adr-06-mono-only-v1-multichannel-v2 |
| 청크 크기 | 1초 권장 (16,000 samples = 32,000 bytes) | 서버는 다른 청크 크기도 수용 — window 처리는 server-side |

**브라우저 resample 책임**: 서버는 원본 포맷을 변환하지 않는다. 클라이언트가 PCM16 16kHz mono 를 보장 (§5 참조).

### 종료 시그널

- **권장**: 텍스트 프레임으로 `{"type":"eof"}` 송신 후 WS close
- **허용**: WS graceful close 만 (현재 데모 동작 방식) — §7 의 race 조건 주의

---

## §3 서버 → 클라이언트 (JSON 이벤트)

### utterance

발화 단위 라벨 확정 이벤트. `SpeakerSegment` 를 기반으로 STT 텍스트를 결합.

anchor: `fastapi_ws_demo.py:69-79`

```json
{
  "type": "utterance",
  "utterance_id": "string",
  "label": "string",
  "t_start": 0.0,
  "t_end": 0.0,
  "confidence": 0.0,
  "text": "string"
}
```

| 필드 | 타입 | 단위 / 범위 | 설명 |
|---|---|---|---|
| `type` | string | `"utterance"` | 고정값 |
| `utterance_id` | string | UUID4 형식 | 발화 단위 식별자 |
| `label` | string | `"registered:이름"` / `"stored:이름"` / `"auto:A"` | 화자 라벨 — LabelChange 로 소급 변경 가능 |
| `t_start` | float | 초, session-relative (0.0~) | 발화 시작 시각 (세션 시작 기준) |
| `t_end` | float | 초, session-relative | 발화 종료 시각 |
| `confidence` | float | 0.0~1.0 | 클러스터 할당 신뢰도 |
| `text` | string | 한국어 텍스트 | STT 결과. 빈 문자열 가능 (묵음 / 인식 불가) |

### relabel

클러스터 재계산 후 화자 라벨 변경 이벤트. `LabelChange` 기반.

anchor: `fastapi_ws_demo.py:80-90`

```json
{
  "type": "relabel",
  "old_label": "string",
  "new_label": "string",
  "reason": "string",
  "affected_count": 0,
  "affected_utterance_ids": ["string"]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | string | `"relabel"` |
| `old_label` | string | 변경 전 라벨 |
| `new_label` | string | 변경 후 라벨 |
| `reason` | string | `"recluster"` / `"stored_match"` / `"persist"` |
| `affected_count` | integer | 영향 받는 발화 수 |
| `affected_utterance_ids` | array[string] | 소급 업데이트해야 할 utterance_id 목록 |

클라이언트는 수신 시 `affected_utterance_ids` 에 해당하는 기존 발화 로그의 라벨을 `new_label` 로 시각 업데이트해야 한다.

### done

세션 종료 + 최종 화자 후보 목록.

anchor: `fastapi_ws_demo.py:93-107`

```json
{
  "type": "done",
  "visit_id": "string",
  "speaker_count": 0,
  "candidates": [
    {
      "auto_id": "string",
      "utterance_count": 0,
      "total_duration": 0.0
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | string | `"done"` |
| `visit_id` | string | 요청 시 path param 으로 받은 visit_id 반향 |
| `speaker_count` | integer | 세션 내 화자 후보 수 |
| `candidates[].auto_id` | string | `"auto:A"` 형식의 화자 식별자 |
| `candidates[].utterance_count` | integer | 해당 화자의 발화 횟수 |
| `candidates[].total_duration` | float | 해당 화자의 총 발화 시간 (초) |

### error

WS 핸들러 내 미처리 예외 발생 시.

anchor: `fastapi_ws_demo.py:114`

```json
{
  "type": "error",
  "message": "string"
}
```

`error` 이벤트 후 서버는 WS를 close 한다.

---

## §4 라이브 UI 요구사항

| 기능 | 상세 |
|---|---|
| 파일 업로드 인풋 | `<input type="file" accept=".wav,.mp3,.m4a">` |
| 재생 컨트롤 | 원본 오디오 재생 (업로드된 파일 기준) — 선택사항 |
| 발화 로그 | 화자별 색상 구분 + 시간(t_start-t_end) + 텍스트 표시 |
| relabel 소급 업데이트 | `relabel` 이벤트 수신 시 기존 발화 로그의 라벨·색상 즉시 갱신 |
| 종료 시 candidates 요약 | `done` 이벤트 수신 시 화자별 발화 수 + 총 시간 표 표시 |
| 에러 표시 | `error` 이벤트 또는 WS 끊김 시 사용자에게 메시지 표시 |

---

## §5 브라우저 측 PCM16 변환 가이드

파일 업로드 → PCM16 16kHz mono 변환 → 1초 청크 WS 전송 흐름. 구현은 `demo-ui` 워커 책임.

```javascript
// 1. 파일 → ArrayBuffer
const arrayBuffer = await file.arrayBuffer();

// 2. Web Audio API 로 디코드
const audioCtx = new AudioContext();
const decoded = await audioCtx.decodeAudioData(arrayBuffer);

// 3. mono mixdown + 16kHz resample (OfflineAudioContext)
const offlineCtx = new OfflineAudioContext(
  1,                           // channels: mono
  Math.ceil(decoded.duration * 16000),
  16000                        // sampleRate: 16kHz
);
const src = offlineCtx.createBufferSource();
src.buffer = decoded;
src.connect(offlineCtx.destination);
src.start(0);
const resampled = await offlineCtx.startRendering();

// 4. Float32 → Int16 변환
const float32 = resampled.getChannelData(0);
const int16 = new Int16Array(float32.length);
for (let i = 0; i < float32.length; i++) {
  const s = Math.max(-1, Math.min(1, float32[i]));
  int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
}

// 5. 1초 청크 분할 + WS 전송
const CHUNK_SAMPLES = 16000;  // 1초
const ws = new WebSocket(`ws://host/audio/${visitId}`);
for (let offset = 0; offset < int16.length; offset += CHUNK_SAMPLES) {
  const chunk = int16.slice(offset, offset + CHUNK_SAMPLES);
  ws.send(chunk.buffer);
}
// 6. 종료 시그널
ws.send(JSON.stringify({ type: "eof" }));
ws.close();
```

---

## §6 마이크 실시간 입력 (v0.2 보류)

마이크 입력은 **out of scope** (planning-03 §2). v0.2 검토 방향만 메모:

- `AudioWorklet` + `SharedArrayBuffer` 로 실시간 PCM16 추출
- `MediaRecorder` API 는 WebM/Ogg 로 인코딩되어 PCM 직접 추출 불가 — AudioWorklet 필요
- 16kHz resample 은 `AudioContext.sampleRate` 와 다를 수 있으므로 `OfflineAudioContext` resample 유지

---

## §7 Graceful Close 프로토콜

### 현재 데모의 한계 (fastapi_ws_demo.py)

클라이언트가 WS 를 바로 close 하는 경우, 서버의 `from_websocket` generator 가 중단되어 `engine.finalize()` → `ws.send_json({"type":"done",...})` 을 전송하려는 순간 WebSocketDisconnect 가 발생한다. 결과적으로 `done` 이벤트가 전달되지 않을 수 있다.

```
클라이언트 close
  ↓
from_websocket StopAsyncIteration
  ↓
async for event in engine.stream(tee()): 루프 종료
  ↓
candidates = await engine.finalize()   ← 이 시점 WS 이미 closed
  ↓
await ws.send_json({type:"done"})      ← WebSocketDisconnect 또는 무시
```

### 권장 Fix

**클라이언트가 `{"type":"eof"}` 텍스트 프레임을 전송한 뒤 WS close 를 대기**한다. 서버는 `eof` 수신 시 `from_websocket` 에서 generator 를 정상 종료 → `done` 전송 후 서버 측 close.

서버 구현 변경 방향 (구현은 `realtime-api` 워커):
1. `from_websocket` 또는 WS 핸들러에서 텍스트 프레임 `{"type":"eof"}` 를 catch → generator stop
2. `done` 전송 완료 후 `await ws.close()`
3. 클라이언트는 `done` 수신 후 WS close

이 변경 전까지 클라이언트는 `done` 수신을 보장받지 못한다.
