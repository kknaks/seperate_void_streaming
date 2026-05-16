---
id: adr-07
type: adr
title: v1 오디오 입력 헬퍼 범위 — mixdown + MultiDeviceMerge + beamforming 3종 채택
status: accepted
created: 2026-05-14
updated: 2026-05-14
sources:
  - "[[planning-02-speaker-engine]]"
  - "[[spec-01-speaker-engine-api]]"
  - "[[adr-06-mono-only-v1-multichannel-v2]]"
tags: [adr, decision, speaker-engine, helpers, audio-input]
---

# v1 오디오 입력 헬퍼 범위 — mixdown + MultiDeviceMerge + beamforming 3종 채택

## Context

[[adr-06-mono-only-v1-multichannel-v2]] 에서 v1 engine 입력은 mono 1ch 강제로 결정했다. 동시에 사용처 전처리 패턴(mono mixdown / beamforming / 다중 인스턴스)을 열거했으나, 어느 패턴을 **엔진 패키지 헬퍼로 제공할지** 는 미결(`Alternatives (b)` — admin 후속 결정 대기)로 남아 있었다.

v1 1순위 미결 사항으로 올라온 3건: (1) 헬퍼 범위, (2) 오류 처리 정책, (3) GPU/CPU 디바이스 선택. 이 ADR 은 (1) 헬퍼 범위를 박제한다. (2), (3)은 [[spec-01-speaker-engine-api]] §5, §2 에 정정.

---

## Decision

**v1 에 오디오 입력 헬퍼 3종 모두 박는다. 우선순위: mixdown(1) → MultiDeviceMerge(2) → beamforming(3).**

| 헬퍼 | 의존성 | 시그니처 요약 |
|---|---|---|
| `from_multichannel_mixdown(stream, channels, method="mean")` | 코어 (numpy) | `AsyncIterator[bytes]` (multi-channel raw) → `AsyncIterator[bytes]` (mono 16kHz PCM) |
| `MultiDeviceMerge(engines: list[SpeakerEngine])` | 코어 (의존성 0) | N engine 의 `SpeakerSegment` 시간 기준 merge stream. label namespace 자동 prefix |
| `from_beamforming(stream, channels, geometry, method="mvdr")` | extras `[beamforming]` (pyroomacoustics) | multi-channel raw → 화자 방향 추정 + spatial filtering → mono |

전체 시그니처 + 사용 예시는 [[spec-01-speaker-engine-api]] §2 참조.

---

## Why

1. **환경별 시나리오 cover**: mixdown(일반 멀티채널 단순 처리) / MultiDeviceMerge(헤드셋 N명 다중 인스턴스) / beamforming(어레이 정확도 우선) — 3가지 패턴이 상호 배타적 환경을 커버.
2. **의존성 분리로 코어 가벼움 유지**: beamforming 은 `pyroomacoustics` 를 extras `[beamforming]` 으로 격리 — 기본 설치에 영향 없음.
3. **MultiDeviceMerge 의존성 제로**: 복수 engine 인스턴스의 `SpeakerSegment` 를 시간 기준 merge 하는 것뿐 — 신규 패키지 의존 없음.
4. **사용처 부담 제거**: [[adr-06-mono-only-v1-multichannel-v2]] 에서 "사용처 책임"으로 넘긴 전처리를 라이브러리가 보조 — 라이브러리 가치 ↑.

---

## Alternatives Considered

| 대안 | 거부 사유 |
|---|---|
| (a) mixdown 만 (beamforming / MultiDeviceMerge 제외) | 다중 디바이스·어레이 환경 사용처 불편. 헬퍼 부재 시 사용처가 직접 구현 부담 |
| (b) beamforming 우선 | 특정 환경(어레이)만 대상 + `pyroomacoustics` + geometry 입력 부담. 범용성 낮음 |
| (c) v2 로 전부 이관 | 핵심 사용 시나리오(헤드셋 N명, 멀티채널 회의실)를 v1 에서 커버 불가 — 채택 장벽 |

---

## Consequences

**긍정**
- 단일 디바이스 멀티채널 / 다중 디바이스 / 어레이 3가지 시나리오 모두 v1 에서 지원.
- extras 분리로 기본 설치 의존성 트리 변화 없음.

**부정/중립**
- `pyproject.toml` extras `[beamforming]` 추가 (`pyroomacoustics`).
- 구현 공수 ~3–4일 (워커 분배) / ~1주 (단독).
- `MultiDeviceMerge` 사용 시 사용처가 SpeakerStore 공유 책임 (cross-device embedding 매칭).
- `from_beamforming` 은 `geometry` (마이크 배치) 입력 필요 — 사용처가 환경별 geometry 제공 책임.

---

## Related

- [[adr-06-mono-only-v1-multichannel-v2]] — mono 1ch 강제 결정 + v2 후속 로드맵 (이 ADR 의 전제)
- [[spec-01-speaker-engine-api]] §2 — 3종 헬퍼 전체 시그니처 + 사용 예시 (이 결정의 구현 명세)
- [[planning-02-speaker-engine]] §7 — 멀티 채널 시나리오 분리 + 패턴 표
