# examples/

`speaker_engine` 사용 시나리오별 예제 스크립트.

## 공통 준비

```bash
export HF_TOKEN=hf_xxxxx
export SPEAKER_ENGINE_STORAGE_URL=memory://
```

---

## basic_chunk_stream.py

파일 → SpeakerEngine → SpeakerSegment / LabelChange 콘솔 출력 + finalize.

```bash
python examples/basic_chunk_stream.py samples/meeting.wav
```

- `samples/meeting.wav` — 16kHz mono 16-bit WAV 파일 직접 준비
- audio 파일 없으면 `FileNotFoundError` 까지 OK (import 정합성 확인 가능)

---

## persist_workflow.py

1차 세션(auto 분리) → persist → 2차 세션(stored 재인식).

```bash
# SQLite 백엔드 권장 (memory:// 는 프로세스 종료 시 휘발)
export SPEAKER_ENGINE_STORAGE_URL=sqlite:///speaker_data.db

python examples/persist_workflow.py samples/first.wav samples/second.wav
```

- 두 파일 모두 동일 화자가 포함된 WAV 권장
- 1차 완료 후 `speaker_data.db` 에 화자 정보 저장됨

---

## fastapi_ws_demo.py

FastAPI WebSocket 핸들러 + Pattern B STT fan-out.

```bash
# fastapi 별도 설치 필요 (코어 의존성 아님)
pip install fastapi uvicorn

uvicorn examples.fastapi_ws_demo:app --reload
```

WebSocket 연결: `ws://localhost:8000/audio/{visit_id}`
- 바이너리 메시지로 PCM 16kHz mono 16-bit bytes 전송
- 이벤트 응답: `utterance` / `relabel` / `done` / `error` JSON
