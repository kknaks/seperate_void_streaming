---
id: spec-08
type: spec
title: 데모 서버 Docker 패키징 + docker-compose 단일 서비스
status: draft
created: 2026-05-20
updated: 2026-05-20
sources:
  - "[[planning-03-demo-v04]]"
  - "[[spec-06-stt-adapter]]"
  - "[[spec-07-demo-ui-protocol]]"
tags: [spec, docker, compose, deployment, v04]
---

# 데모 서버 Docker 패키징 + docker-compose 단일 서비스

## Summary

V-04 데모 서버를 단일 Docker 컨테이너로 패키징. uvicorn + speaker_engine + ElevenLabsSTT 클라이언트 + `web/` 정적 파일 일체 포함. mac/x86 CPU 환경 가정, GPU 미사용. STT 는 ElevenLabs API 외부 호출이므로 컨테이너 내 STT 모델 없음. pyannote/diart 모델만 volume runtime cache.

---

## §1 컨테이너 구조

### 베이스 이미지

```
python:3.11-slim
```

- Python 3.13 호환 안 함 — pyannote 3.1.1 + torch 2.1.* 핀 (T-001 결정)
- `python:3.11-bookworm-slim` 도 선택 가능 (glibc 안정성)

### 작업 디렉토리

```
/app
```

### 설치 패키지

| 종류 | 패키지 |
|---|---|
| Python | `speaker_engine[stt-elevenlabs]` |
| 시스템 | `ffmpeg` (wav 변환 예비), `libsndfile1` (soundfile 의존) |

### 레이아웃

```
/app/
  speaker_engine/    ← 라이브러리 소스
  server/            ← FastAPI realtime-api + stt/
  web/               ← 정적 파일 (demo-ui)
  requirements.txt   ← 워커가 결정
```

---

## §2 빌드 + 실행

### Dockerfile 위치

루트 (`/`) 권장. 워커(T-012)가 최종 결정.

### 빌드 명령

```bash
docker build -t void-streaming-demo:0.1.0 .
```

### 단독 run

```bash
docker run \
  -p 8000:8000 \
  --env-file .env \
  -v hf_cache:/root/.cache/huggingface \
  void-streaming-demo:0.1.0
```

---

## §3 docker-compose.yml (명세)

```yaml
# 이하는 spec 명세 — 실 파일은 T-012 워커가 생성
version: "3.9"

services:
  server:
    image: void-streaming-demo:0.1.0
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - hf_cache:/root/.cache/huggingface
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  hf_cache:
```

### §OQ-08-1 포트 선택 (resolved 2026-05-20)

> **Decision**: **B) 8000** (uvicorn default + FastAPI 표준 + nginx reverse proxy 연동 편의).
>
> admin smoke 스크립트 (`/tmp/ws_smoke.py`) 의 8765 는 admin 로컬 환경 변수 — 컨테이너 host 포트 매핑과 무관 (`docker run -p 8765:8000` 으로 admin 측 자유 매핑 가능). compose 의 표준 mapping 은 `8000:8000`.

---

## §4 환경 변수 계약

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `HF_TOKEN` | **필수** | — | pyannote 모델 다운로드 인증 |
| `ELEVENLABS_API_KEY` | **필수** | — | ElevenLabs streaming STT 인증 (spec-06) |
| `SPEAKER_ENGINE_STORAGE_URL` | 선택 | `memory://` | 스토어 백엔드 (영속화 안 함, v0.2 검토) |

**폐기 변수 (박지 말 것)**:
- `WHISPER_MODEL_SIZE` — T-008 에서 WhisperSTT 폐기
- `WHISPER_LANGUAGE` — 동일

### .env.example (내용 명세)

```dotenv
# void-streaming-demo 환경 변수 예시
# 실제 값으로 교체 후 .env 로 복사 (절대 저장소에 커밋 금지)

HF_TOKEN=
ELEVENLABS_API_KEY=
SPEAKER_ENGINE_STORAGE_URL=memory://
```

---

## §5 모델 다운로드 전략 (volume mount runtime cache)

| 단계 | 동작 |
|---|---|
| image 빌드 | 모델 baked 안 함 — image 경량화 |
| 컨테이너 첫 기동 | lifespan 안에서 pyannote 모델 다운로드 (~1.5 GB) → `~/.cache/huggingface` volume 캐시 |
| 재기동 | volume cache hit → 다운로드 skip |
| 오프라인 시연 전처리 | 인터넷 연결 상태에서 1회 기동 후 종료 → cache 채워두기 |

**이유**: image 경량화 우선 (v0.1.0 데모 환경). offline-first baked image는 v0.2 out-of-scope.

---

## §6 보안 / .env 정책

| 규칙 | 설명 |
|---|---|
| `.env` 저장소 포함 금지 | `.dockerignore` 와 `.gitignore` 모두 등록 (T-012 워커 책임) |
| `.env.example` 만 저장소 포함 | 키 빈 칸 + 주석 (§4 명세) |
| API 키 주입 경로 | host .env → compose `env_file` 만 허용. 이미지 layer 에 절대 baked 금지 |
| `HF_TOKEN` 취급 | 동일 — env_file 로만 주입 |

---

## §7 KPI / 검증

| 지표 | 어림 목표 | 측정 주체 |
|---|---|---|
| 빌드 시간 | — | T-012 워커 측정 후 보고 |
| image 크기 | — | T-012 워커 측정 후 보고 |
| cold start → ready (cache hit) | < 30s | T-012 워커 측정 |
| WS e2e (AMI 2분 wav → `done` 수신) | 통과 | T-012 워커 smoke 테스트 |

> WS 엔드포인트 형식은 spec-07 §3 기준.

---

## §8 Out of Scope (v0.2 검토)

| 항목 | 이유 |
|---|---|
| 다중 인스턴스 (k8s, scale) | v0.1.0 단일 데모 |
| GPU image variant | mac/x86 CPU 전용 |
| pgvector DB compose 서비스 | DB 영속화 시점 미결 |
| reverse proxy (nginx / traefik) | 데모 범위 초과 |
| HTTPS / wss | 데모 범위 초과 |
| 모델 baked image (offline-first) | image 경량화 우선 |
