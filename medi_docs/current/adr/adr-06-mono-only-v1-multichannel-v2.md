---
id: adr-06
type: adr
title: v1 입력 mono 1ch 강제 — Multi-Channel Diarization 은 v2
status: accepted
created: 2026-05-14
updated: 2026-05-14
sources:
  - "[[planning-02-speaker-engine]]"
  - "[[reference-01-pyannote-segmentation-3]]"
  - "[[adr-01-diart-wrapping-strategy]]"
tags: [adr, decision, speaker-engine, audio-channel, roadmap]
---

# v1 입력 mono 1ch 강제 — Multi-Channel Diarization 은 v2

## Context

실회의·콜센터·의료 상담 환경에서 다중 마이크(어레이 마이크, 자리별 헤드셋 등) 입력이 일반적이다. 멀티 채널 diarization 을 v1 에 바로 도입할지, 아니면 mono 1ch 만 지원하고 사용처에게 전처리를 위임할지 결정이 필요하다.

[[reference-01-pyannote-segmentation-3]] §1 에 따르면 `pyannote/segmentation-3.0` 은 mono 16kHz 학습 데이터 기반이며, [[adr-01-diart-wrapping-strategy]] 에서 채택한 diart blocks(`SpeakerSegmentation`, `OverlapAwareSpeakerEmbedding`, `OnlineSpeakerClustering`) 도 동일 생태계.

## Decision

**v1 = engine 입력 mono 1ch only 강제. 멀티 채널 audio 는 사용처 전처리 책임 (mixdown / beamforming / 채널 선택). Multi-Channel Diarization 모델 도입은 v2.**

사용처 전처리 패턴 (사용처 선택):

| 패턴 | 처리 방법 | 적합 환경 |
|---|---|---|
| mono mixdown | 채널 평균/합산 → mono 1ch | 채널 차이 작은 환경 (홈 회의실 등), 가장 단순 |
| beamforming → mono | DSP (delay-and-sum / MVDR / GEV) → mono. `pyroomacoustics` 등 활용 | 회의실 천장 어레이, in-car, 노이즈 환경 |
| 채널 선택 | 가장 SNR 높은 채널 1개 선택 → mono | 마이크 1개가 화자에 가깝고 나머지는 배경 |
| 다중 인스턴스 | 디바이스/자리마다 engine 인스턴스 분리, SpeakerStore 공유 | 콜센터 N석, 자리별 헤드셋 |

## Why

1. **모델 학습 한계**: `pyannote/segmentation-3.0` 은 mono 16kHz 학습 — multi-channel 입력 시 정확도 미보장 [[reference-01-pyannote-segmentation-3]] §1.
2. **pretrained open-weight 부재**: Multi-Channel Diarization 검증 모델(TS-VAD / EEND-multich / NeMo Multi-Channel)이 모두 연구 코드 + 도메인 fine-tune 필요. 프로덕션 즉시 투입 불가.
3. **diart 생태계 충돌**: [[adr-01-diart-wrapping-strategy]] 에서 결정한 diart blocks 래핑 전략과 정면 충돌 — 별도 model framework adapter 필요, 의존성 트리 분기.
4. **학습 데이터 비용**: multi-channel labeled diarization 데이터셋은 별도로 확보해야 하며, 현재 보유 없음.
5. **GPU 의존도**: mono × N channels 방식 시 GPU 부담 × N 배.
6. **마이크 geometry 입력 일반화 어려움**: 환경별 마이크 배치 변동이 크고, 범용 모델로 일반화가 어려움.
7. **v1 우선 목표**: 검증된 mono 생태계로 빠르게 출시 → 실운영 KPI 측정 → v2 에 데이터 기반 모델 도입.

## Alternatives Considered

| 대안 | 거부 사유 |
|---|---|
| (a) v1 에 multi-channel 모델 직접 도입 | 시간 ↑↑, 검증 부담, 의존성 트리 분기. pretrained open-weight 부재 |
| (b) v1 에 beamforming 헬퍼 (`speaker_engine.audio.from_multichannel_mixdown` 등) | 부분 채택 검토 중 — admin 후속 결정 대기. `pyroomacoustics` 등 의존성 추가 필요 |
| (c) v1 안 만들고 사용처가 multi-channel 직접 처리 | 라이브러리 가치(3-tier 식별 + SpeakerStore + Pattern B 이벤트 체인) 를 사용처가 누리지 못함 |

## Consequences

**긍정**
- v1 엔진 코드베이스 단순화 — multi-channel 분기 없음.
- diart 생태계 단일 의존 유지 ([[adr-01-diart-wrapping-strategy]] 일관성).
- 검증된 mono 생태계로 v1 출시 가속.

**부정/중립**
- 강한 cross-talk 환경(식사 회식, 시끄러운 회의실)에서 v1 정확도 ↓.
- 사용처가 멀티 채널 → mono 전처리 책임을 직접 부담 (코드 5~20줄 추가).
- v2 트리거 조건:
  - (a) pyannote/diart 생태계 안에 multi-channel pretrained 출시
  - (b) v1 운영 KPI 가 어레이 환경에서 목표 미달
  - (c) 도메인 데이터셋 확보 + fine-tune 인프라 준비

v2 후속 검토 항목:
- Multi-Channel Diarization 모델 도입 (TS-VAD / EEND-multich / NeMo 등 pretrained 검토)
- beamforming layer 엔진 내부 옵션 (`SpeakerEngine(input_channels=4, beamforming="mvdr")`)
- 멀티 디바이스 통합 헬퍼 (`speaker_engine.multi.MergedStream`)

## Related

- [[planning-02-speaker-engine]] §7 멀티 채널 정책 + §10 비기능 요구 (v1 mono 강제)
- [[reference-01-pyannote-segmentation-3]] §1 mono 학습 한계
- [[adr-01-diart-wrapping-strategy]] — multi-channel 모델 도입 시 충돌 영역
