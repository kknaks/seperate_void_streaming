# void_streaming v0.4 — 검토 자료

> 한국어 회의 화자 분리 + 실시간 STT 자막 + 라이브 화자 라벨링 demo의 운영 가이드 + ablation 측정 결과.

## 시작 — INDEX

브라우저로 [`INDEX.html`](INDEX.html) 열기. 모든 측정 결과 + 운영 가이드 link.

## 핵심 결론

| 항목 | 값 |
|---|---|
| **embedding** | `pyannote/embedding` (512-dim) |
| **window / step / scheduler** | `2.0s / 0.5s / baseline` |
| **device** | CPU (GPU 불필요, 38× realtime headroom) |
| **Azure VM 권장** | **Standard B2s** (2 vCPU, 4GB RAM, ~$30/월) |
| **라이브 라벨링 SLA** | p50 **1.5s** / p95 **2.4s** |
| **STT 자막 지연** | ~0.5s |
| **화자 분리 DER** | 0.20 (한국어 회의 sample) |

## 산출물

| 파일 | 설명 |
|---|---|
| ⭐ [v04-operational-guide.html](v04-operational-guide.html) | **운영 가이드 (Azure 배포 권장값)** |
| [v02-final.html](v02-final.html) | v0.2 ablation 최종 종합 (최적 조합 박제) |
| [phase1-full-20260522.html](phase1-full-20260522.html) | embedding × window × step grid (72 rows) |
| [phase2-final-20260522.html](phase2-final-20260522.html) | scheduler ablation 8 variant 비교 (32 rows) |
| [v03-realtime-20260523.html](v03-realtime-20260523.html) | 라이브 환경 재측정 (4 rows) |
| [v04-live-latency.html](v04-live-latency.html) | 진짜 wall-clock latency 측정 |
| [phase1-analysis.html](phase1-analysis.html) | Phase 1 분석 보고서 |
| `_raw/` | 측정 raw JSON / CSV (Phase 1/2/v03/v04) |

## Phase 흐름

```
Phase 0~1: embedding × window × step grid (72 rows, offline)
   ↓
Phase 2: scheduler ablation 8 variant (32 rows, baseline 채택)
   ↓
Phase 3: 라이브 매핑 검증 (demo_v03 시연, 매핑 작동 ✓)
   ↓
Phase 4: 라이브 wall-clock latency + 운영 가이드 (배포 가능 수준)
```

## 측정 환경

- Python 3.11 + diart 0.9.2 + pyannote.audio 3.1.1
- 한국어 회의 sample 2개 (record_1.wav 277s, record_3.wav 168s)
- ground truth RTTM (pyannote 자동 생성 + 사용자 검토)
- Mac M3 Max, CPU 강제 (Azure CPU instance 가정)
