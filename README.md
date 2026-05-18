# speaker_engine

diart 기반 실시간 화자 분리 라이브러리. 다인 대화 환경에서 PCM 오디오 스트림을 받아 라벨링된 발화 이벤트(`SpeakerSegment` / `LabelChange`)를 yield한다.

---

## 핵심 기능

- **3-tier 화자 라벨** — `registered:이름` (사전 등록) / `stored:이름` (이전 세션 학습) / `auto:A` (세션 내 자동 분리)
- **5종 입력 소스** — WebSocket / 파일 / 마이크 / 멀티채널 mixdown / 다중 디바이스 merge
- **3종 스토리지 백엔드** — `memory://` / `sqlite:///path.db` / `postgresql://...` — URL 하나로 선택
- **세션 종료 시 HDBSCAN 정밀 재정렬** — 온라인 클러스터 결과를 사후 정제

---

## 설치

```bash
# 기본 (memory 스토리지만)
pip install "speaker_engine @ git+ssh://git@github.com/kknaks/seperate_void_streaming.git@v0.1.0"

# SQLite 벡터 스토리지 포함
pip install "speaker_engine[sqlite] @ git+ssh://git@github.com/kknaks/seperate_void_streaming.git@v0.1.0"

# pgvector 포함
pip install "speaker_engine[pgvector] @ git+ssh://git@github.com/kknaks/seperate_void_streaming.git@v0.1.0"

# beamforming + 마이크 포함
pip install "speaker_engine[beamforming,microphone] @ git+ssh://git@github.com/kknaks/seperate_void_streaming.git@v0.1.0"

# 개발 환경 전체
pip install -e ".[sqlite,pgvector,beamforming,microphone,dev]"
```

> **pyannote 모델 사용 동의 필수** — [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) 및 [pyannote/embedding](https://huggingface.co/pyannote/embedding) 에서 HuggingFace 사용 동의 후 `HF_TOKEN` 설정.

---

## 환경 변수

| 변수 | 설명 | 예시 |
|---|---|---|
| `HF_TOKEN` | pyannote 모델 인증 토큰 (필수) | `hf_xxxxx` |
| `SPEAKER_ENGINE_STORAGE_URL` | 스토리지 백엔드 선택 (필수) | `memory://` / `sqlite:///data/speakers.db` / `postgresql://user:pass@host/db` |

---

## 30초 Quickstart

```python
import asyncio
from speaker_engine import SpeakerEngine, from_file, SpeakerSegment, LabelChange

async def main():
    engine = SpeakerEngine()  # env: HF_TOKEN + SPEAKER_ENGINE_STORAGE_URL=memory://

    async with engine:
        async for event in engine.stream(from_file("samples/meeting.wav")):
            if isinstance(event, SpeakerSegment):
                print(f"[{event.label}] {event.t_start:.2f}s–{event.t_end:.2f}s")
            elif isinstance(event, LabelChange):
                print(f"  → 라벨 변경: {event.old_label} → {event.new_label} ({event.reason})")

        candidates = await engine.finalize()
        print(f"\n세션 화자 수: {len(candidates)}")
        for c in candidates:
            print(f"  {c.auto_id}: {c.utterance_count}발화 / {c.total_duration:.1f}s")

asyncio.run(main())
```

---

## 사용 시나리오

| 시나리오 | 예제 파일 |
|---|---|
| 파일 배치 처리 + 콘솔 출력 | [`examples/basic_chunk_stream.py`](examples/basic_chunk_stream.py) |
| 영속화 + 2차 세션 재인식 | [`examples/persist_workflow.py`](examples/persist_workflow.py) |
| FastAPI WebSocket 실시간 스트리밍 | [`examples/fastapi_ws_demo.py`](examples/fastapi_ws_demo.py) |

---

## 라이프사이클

```
async with engine:          # 모델 로드 + 스토리지 연결
    engine.stream(source)   # PCM 스트림 → SpeakerSegment / LabelChange yield
    engine.finalize()       # drain + HDBSCAN 재정렬 → list[SpeakerCandidate]
    engine.persist(mappings) # auto:* → 이름 매핑 → SpeakerStore 저장 → list[Speaker]
```

- **첫 세션**: `auto:A`, `auto:B`, ... 로 자동 분리
- **persist() 후**: `stored:이지영`, `stored:김환자` 등으로 스토리지에 저장
- **다음 세션**: 동일 화자 embedding 매칭 → `stored:이름` 자동 인식

---

## 공개 API

### 클래스

| 이름 | 설명 |
|---|---|
| `SpeakerEngine` | 오케스트레이터 — `stream` / `finalize` / `persist` / `set_alias` / `merge_speakers` / `delete_speaker` |
| `MultiDeviceMerge` | N개 독립 엔진 이벤트를 시간 기준으로 merge |

### 소스 헬퍼 함수

| 이름 | 설명 |
|---|---|
| `from_websocket(ws)` | FastAPI/Starlette WebSocket → PCM 스트림 |
| `from_file(path)` | 로컬 WAV/PCM 파일 → 스트림 (테스트/배치) |
| `from_microphone(device)` | sounddevice 마이크 → 스트림 (로컬 데모) |
| `from_multichannel_mixdown(stream, channels)` | 멀티채널 PCM → mono mixdown |
| `from_beamforming(stream, channels, geometry)` | 멀티채널 PCM + 어레이 배치 → beamforming mono |
| `from_url(url)` | URL 문자열로 SpeakerStore 백엔드 생성 |

### dataclass 타입

| 이름 | 설명 |
|---|---|
| `SpeakerSegment` | 발화 단위 이벤트 — `label` / `t_start` / `t_end` / `utterance_id` / `embedding` |
| `LabelChange` | 라벨 소급 변경 이벤트 — `old_label` / `new_label` / `affected_utterance_ids` / `reason` |
| `SpeakerCandidate` | `finalize()` 반환 — `auto_id` / `utterance_ids` / `representative_embedding` / `total_duration` |
| `Speaker` | 영속 화자 레코드 — `id` / `name` / `origin` / `first_seen` / `last_seen` |
| `PersistMapping` | `persist()` 인자 — `auto_id` + `name` |
| `MicrophoneGeometry` | 마이크 어레이 물리 배치 (beamforming 용) |
| `BeamformingConfig` | beamforming 알고리즘 설정 |

### 예외

| 이름 | 발생 조건 |
|---|---|
| `ModelLoadError` | pyannote 모델 로드 실패 |
| `StorageError` | 스토리지 연결/IO 실패 |
| `IntegrityError` | 스토리지 무결성 위반 |

---

## 개발 / 테스트

```bash
# 단위 테스트 (HF_TOKEN 불필요)
pytest tests/unit/ -q

# 통합 테스트 (HF_TOKEN + pyannote 모델 필요)
pytest tests/integration/ -m integration -q

# 릴리스 직전 live 테스트 (pgvector 등 외부 서비스 필요)
pytest tests/live/ -m live -q
```

---

## 참조

- `medi_docs/current/` — 내부 설계 문서 (planning / spec / adr / plan)
- [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) — 화자 세그멘테이션 모델 (HF 동의 필수)
- [pyannote/embedding](https://huggingface.co/pyannote/embedding) — 화자 임베딩 모델 (HF 동의 필수)
- [diart](https://github.com/juanmc2005/diart) — 온라인 화자 분리 파이프라인

---

## 라이선스

이 프로젝트는 내부 연구/개발용입니다. pyannote 모델 사용 시 해당 모델의 라이선스 및 HuggingFace 사용 동의 정책을 준수해야 합니다.
