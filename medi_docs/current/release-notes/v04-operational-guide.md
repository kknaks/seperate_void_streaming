---
id: release-v04-operational-guide
type: release-notes
title: void_streaming v0.4 — 운영 가이드 (Azure 배포 권장값)
status: accepted
created: 2026-05-24
updated: 2026-05-24
sources:
  - "[[retrospective-v02-final]]"
  - "[[retrospective-v03-realtime]]"
  - "[[retrospective-v04-live-latency]]"
tags: [release-notes, v0.4, operational, azure, sla]
---

# void_streaming v0.4 — 운영 가이드

> **한 줄**: 한국어 회의 화자 분리 + 실시간 STT 자막 + 라이브 화자 라벨링 demo 운영 가이드. Azure CPU instance 가정.

---

## TL;DR

| 항목 | 권장 |
|---|---|
| **embedding** | `pyannote/embedding` (512-dim) |
| **window** | 2.0초 |
| **step** | 0.5초 |
| **scheduler** | baseline (diart `OnlineSpeakerClustering` 기본) |
| **device** | CPU 강제 (GPU 불필요) |
| **STT** | ElevenLabs Realtime (`commit_strategy=manual` + server VAD silence 250ms) |
| **매핑** | diart segment ↔ STT phrase 시간 overlap → dominant speaker |
| **Azure VM** | **B2s** (2 vCPU, 4GB RAM) — 권장 / B2ms (2 vCPU, 8GB) 여유 시 |

**SLA**:
- STT 자막 즉시 (~0.5s)
- 화자 라벨링 p50 **1.5초** / p95 **2.4초**
- 초기 cluster 형성 50초 (이후 stable)
- 화자 분리 정확도 ~80% (DER 0.20, 한국어 회의)

---

## 1. 권장 설정값 (확정)

### 1.1 화자 분리 (diart)

```python
from diart import OnlineSpeakerDiarization, PipelineConfig
from pyannote.audio import Model

embedding = Model.from_pretrained("pyannote/embedding", use_auth_token=HF_TOKEN)

config = PipelineConfig(
    duration=2.0,           # window
    step=0.5,               # step
    tau_active=0.6,         # baseline scheduler (변경 금지)
    rho_update=0.3,         # baseline
    delta_new=1.0,          # baseline
    device="cpu",           # CPU 강제 (GPU 불필요)
)
```

| 파라미터 | 값 | 변경 시 영향 |
|---|---|---|
| `window_s` | **2.0** | 1.0/3.0/5.0 시도 → 2.0 이 전 모델 최적 (Phase 1 ablation) |
| `step_s` | **0.5** | 0.1/0.25 시도 → 둘 다 DER 0.85+ (실용 불가). 0.5 만 사용 가능 |
| scheduler | **baseline** | decay-A/B + HDBSCAN on/off + legacy adaptive/final/both 측정 → 어떤 variant 도 ≥2pp 개선 못함 |

### 1.2 STT (ElevenLabs Realtime)

```python
from server.stt import ElevenLabsSTT

stt = ElevenLabsSTT(
    language="ko",
    commit_strategy="manual",      # vad 모드 한국어 회의 부적합 (legacy 검증)
    use_server_vad=True,           # webrtcvad
    vad_silence_ms=250,            # 한국어 발화 silence 평균 < 1s, 250ms 권장
    vad_aggressiveness=3,          # 0~3 중 적극적 silence 검출
)
```

### 1.3 시간 overlap 매핑

```python
def resolve_label(phrase_start, phrase_end, segments):
    """dominant overlap segment 의 speaker 반환."""
    overlaps = {}
    for seg in segments:
        ov = max(0.0, min(phrase_end, seg.t_end) - max(phrase_start, seg.t_start))
        if ov > 0:
            overlaps[seg.speaker] = overlaps.get(seg.speaker, 0.0) + ov
    if not overlaps:
        return "unknown"  # fallback
    return max(overlaps.items(), key=lambda x: x[1])[0]
```

→ STT phrase 가 emit 될 때 `audio_ws` 의 `segment_log` 에서 lookup.

---

## 2. Azure VM 권장

### 2.1 측정 기반 추정

| 자원 | peak 실측 | avg 실측 | VM 권장 |
|---|---|---|---|
| CPU | ~200% (2 core 사용) | ~162% | 2 vCPU |
| RAM | 778MB (pyannote) | 292MB | 2~4GB |
| GPU | 사용 X | — | 불필요 |
| 처리 속도 | 16초 / 277초 audio | 0.06× realtime | **38× headroom** |
| disk | ~3GB (모델 cache) | — | 30GB 표준 |

### 2.2 추천 SKU

| 시나리오 | VM | 비용 (KR Central) | 비고 |
|---|---|---|---|
| **권장** | **Standard B2s** (2 vCPU, 4GB) | ~$30/월 | 동시 1~2 세션 |
| 여유 | Standard B2ms (2 vCPU, 8GB) | ~$60/월 | 다중 세션 시 RAM 여유 |
| 다중 동시 | Standard B4ms (4 vCPU, 16GB) | ~$120/월 | 4+ 동시 세션 |
| 비추천 | D-series (premium) | — | overspec, GPU 불필요 |

> CPU instance burst (B-series) 충분 — peak burst 후 idle 시간 길어 baseline credit 확보.

### 2.3 의존성 install

```bash
# Python 3.11 + venv
pip install diart==0.9.2 pyannote.audio==3.1.1 torch==2.1.* torchaudio==2.1.*
pip install 'huggingface_hub<0.20'  # pyannote 3.1.1 호환
pip install fastapi 'uvicorn[standard]' websockets webrtcvad

# 모델 cache (~/.cache/huggingface)
export HF_TOKEN=hf_xxxxx           # pyannote.audio 모델 download
export ELEVENLABS_API_KEY=sk_xxxxx
```

### 2.4 systemd unit (예시)

```ini
[Unit]
Description=void_streaming demo_v03
After=network.target

[Service]
Type=exec
WorkingDirectory=/opt/void_streaming
EnvironmentFile=/opt/void_streaming/.env
ExecStart=/opt/void_streaming/.venv/bin/uvicorn examples.demo_v03:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

---

## 3. 예상 SLA

### 3.1 응답성

| 단계 | latency | 측정 근거 |
|---|---|---|
| STT 자막 (partial) | **~0.5s** | ElevenLabs Realtime, legacy v0.1 검증 |
| 화자 라벨링 (p50) | **1.5s** | v0.4 실측 (pyannote, record_1/3) |
| 화자 라벨링 (p95) | **2.4s** | v0.4 실측 — 일부 tail 케이스 |
| 초기 cluster 형성 | **50초** | diart 본질, 50s 후 stable |

### 3.2 정확도

| metric | 값 | 근거 |
|---|---|---|
| DER (offline) | **0.199** | v0.2 ablation, pyannote w=2.0 s=0.5 baseline |
| DER (라이브) | **0.224** | v0.3 ablation, 실시간 환경 추가 |
| 라이브 매핑 정확도 | **stable 50s 후 ~95%** | v0.3 시연 검증, 81 phrase A=고객/B=상담사 일관 |

### 3.3 알려진 한계

| 한계 | 영향 | 완화 |
|---|---|---|
| 초기 50초 cluster 형성 불안정 | 첫 1~2분 라벨링 잘못 가능 | retroactive 라벨 갱신 옵션 (후속 plan) 또는 사용자 UI 안내 |
| record_3 DER 높음 (0.288) | 짧은 audio + 화자 turn-taking 빠름 → 정확도 ↓ | 운영 시 모니터링, sample 길이 ≥ 3분 권장 |
| p95 latency 2.4s | 일부 phrase 2초 초과 라벨링 | UI 에 "라벨링 중..." 인디케이터 |
| client websocket 40s 끊김 (auto_play 측정) | demo 외부 영향 0 | 실 브라우저 client 는 안정 (시연 검증) |
| 한국어 외 언어 | 미검증 | language="ko" 외 별도 측정 |
| 등록 직원 매핑 (registered:이름) | 미구현 | Phase 4 후속 plan (out of v0.4 scope) |

---

## 4. 운영 체크리스트

### 4.1 배포 전

- [ ] Azure VM B2s+ 프로비저닝
- [ ] Python 3.11 + venv 구성
- [ ] HF_TOKEN + ELEVENLABS_API_KEY 환경 변수 설정
- [ ] diart + pyannote.audio 모델 cache pre-load (`scripts/render_index.py` 같은 dry-run)
- [ ] firewall: 8000 (또는 443 + reverse proxy)
- [ ] systemd unit 또는 docker compose 등록

### 4.2 운영 모니터링

| metric | 도구 | 임계 |
|---|---|---|
| CPU 사용률 | Azure Monitor / `psutil` | > 80% 지속 시 인스턴스 size up |
| RAM | Azure Monitor | > 80% 시 size up |
| WS 연결 수 | server log | 동시 세션 수 |
| 라이브 latency | demo_v03 `latency_log` (DEMO_V03_LATENCY_LOG=1) | p95 > 3s 시 조사 |
| ElevenLabs API 응답 | server log | 5xx / 401 alert |
| diart 모델 load 시간 | startup log | > 30s 시 cache 확인 |

### 4.3 장애 대응

| 증상 | 조치 |
|---|---|
| 첫 WS 연결 30s+ 지연 | diart 모델 lazy-load — startup 시 pre-load 변경 |
| 라벨링 안 됨 | server log [PHRASE] 확인, ElevenLabs API 401 가능 |
| 모든 phrase 한 라벨 | diart 초기 50초 cluster 형성 단계 정상 — 1~2분 대기 |
| 자막 안 흐름 | ElevenLabs WS 연결 실패 — API key 확인 |
| CPU 100% 지속 | 동시 세션 수 + VM size 검토 |

---

## 5. 산출물 위치

```
/opt/void_streaming/
├── examples/demo_v03.py           # WS 서버 + diart + STT + 매핑
├── eval/embeddings/pyannote_emb.py # embedding wrap (Phase 1 ablation 자산)
├── server/stt/elevenlabs.py        # ElevenLabs Realtime 어댑터
├── server/stt/vad.py               # webrtcvad ServerVAD
├── server/audio/ringbuffer.py      # PcmRingBuffer
├── web/index.html                  # 4-panel UI
├── web/worklet-processor.js        # AudioWorklet PCM capture
└── scripts/
    ├── auto_play_audio.py          # 자동 재생 (측정용)
    ├── eval_ablation.py            # offline ablation 측정
    ├── realtime_ablation.py        # 라이브 ablation 측정 (v0.3)
    ├── render_report.py            # ablation HTML report
    └── render_index.py             # INDEX HTML 생성
```

---

## 6. 후속 개선 (out of v0.4)

- **enrollment**: 등록 직원 voice sample → `registered:이름` 매핑 (운영 핵심 가치)
- **wespeaker GPU 측정**: DER 0.176 (CPU 비실용, GPU instance 평가)
- **embedding fine-tuning**: 한국어 회의 도메인 특화
- **record_3 RTTM 수동 정제**: ground truth 정확도 향상
- **retroactive 라벨 갱신**: 초기 50초 phrase 의 사후 정정

---

## 7. 참조

- [INDEX (전체 산출물)](INDEX.html)
- [v0.2 ablation 최종](v02-final.html)
- [v0.3 라이브 매핑](v03-realtime-20260523.html)
- [v0.4 라이브 latency](v04-live-latency.html)
- [Phase 1 grid (72 rows)](phase1-full-20260522.html)
- [Phase 2 scheduler (32 rows)](phase2-final-20260522.html)
