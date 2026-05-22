---
id: adr-10
type: adr
title: STT-driven Sequential Chain 채택 — STT phrase boundary SSOT (Pattern B 폐기)
status: accepted
created: 2026-05-21
updated: 2026-05-21
sources:
  - "[[planning-03-demo-v04]]"
  - "[[adr-02-pattern-b-fanout-chain]]"
  - "[[spec-04-clustering-algorithms]]"
  - "[[spec-06-stt-adapter]]"
  - "[[spec-07-demo-ui-protocol]]"
supersedes: "[[adr-02-pattern-b-fanout-chain]]"
tags: [adr, decision, stt, speaker-engine, sequential-chain, plan-006]
---

# STT-driven Sequential Chain 채택 — STT phrase boundary SSOT (Pattern B 폐기)

## Summary

PLAN-005 실측 (streaming raw DER 19.40% ≈ finalize DER 19.73%) + boundary 불일치 본질 확인으로 adr-02 Pattern B 폐기. STT phrase boundary 를 SSOT 로 삼고, engine 이 STT 의 phrase PCM slice 를 receive → 화자 라벨 반환하는 sequential chain 을 채택.

## Context

### 배경 — PLAN-005 시연 한계

PLAN-005 (adr-09 서버 live grouping layer, `labeled_word` / `final_grouped` 이벤트) 시연 확인:
- 우-중 매핑 자체는 일부 동작 ([auto:A] / [auto:B] / [auto:A])
- **boundary 불일치로 라벨링이 발화 끝나야 도착** — "엄청 느림"
- **긴 발화 (~30초) 가 한 줄에 다 누적** — 문장 단위 표시 불가

### PLAN-005 실측 결과 (2026-05-20, AMI 4 세션)

| session | duration | ref 화자 | streaming raw DER | finalize DER |
|---|---|---|---|---|
| ES2002a | 28min | 4 | 23.76% | 21.25% |
| ES2003a | 28min | 4 | 12.74% | 16.75% |
| ES2008a | 28min | 4 | 11.21% | 10.16% |
| IS1000a | 26min | 4 | 29.88% | 30.75% |
| **avg** | — | — | **19.40%** | **19.73%** |

**핵심**: streaming raw ≈ finalize. 매핑 layer(PLAN-005)나 label 안정화 layer(가정안)로도 같은 한계.

### 근본 원인 — boundary 불일치

| 항목 | engine (pyannote+diart) | STT (ElevenLabs Scribe) |
|---|---|---|
| boundary 정의 | 화자 변경 시점 | 단어/phrase 끝 |
| 출력 단위 | SpeakerSegment (sliding window 점진 확장) | partial / committed transcript |
| 시간 좌표 | 자기 sliding window 기준 | 자기 누적 PCM 기준 |
| emit 타이밍 | 발화 종료/화자 변경 | phrase 끝 (commit 시) |

두 모델이 **서로 다른 이벤트 boundary** 를 자기 시간축으로 emit → 사용처가 시간 매칭 시도하면 본질적 어긋남. PLAN-005 의 `attribute_word` / `flush_pending_for` 가 이 문제를 그대로 노출.

## Decision

**STT-driven Sequential Chain 채택. STT phrase boundary 가 SSOT. engine 은 STT 의 final phrase 에 대응하는 PCM slice 를 receive → 화자 라벨 1건 반환.**

새 서버 흐름:

```
PCM 입력 → STT.feed (continuous)
  ↓
  partial → ws.send_json({"type":"stt", ...})           # 즉시 우-상 자막
  ↓
  final (phrase 끝) → Transcript(t_start, t_end, text)
  ↓
  phrase PCM slice 추출 (server audio buffer)
  ↓
  engine.identify_phrase(pcm_slice) → label              # 신규 인터페이스 (spec-04 §9)
  ↓
  ws.send_json({"type":"labeled_phrase", label, t_start, t_end, text})  # 우-중
```

**UI 이벤트 변화 (spec-07)**:

| 이벤트 | 변화 | 사유 |
|---|---|---|
| `segment` | 폐기 | Chain 구조에서 engine 이 phrase label 만 반환 — segment 개념 무의미 |
| `labeled_word` | 폐기 | Chain 은 phrase 단위 — 단어별 attach 불필요 |
| `relabel` | 폐기 | phrase 결정 시점에 라벨 확정 — 소급 변경 이벤트 불필요 |
| `labeled_phrase` | **신규** | `{ type, label, t_start, t_end, text }` — phrase 단위 라벨 attach 결과 |
| `stt` | 유지 | 우-상 자막용 partial/final |
| `final_grouped` | 유지 | utterance 단위 최종 결과 |
| `done`, `error` | 유지 | 세션 종료 / 에러 |

## Why

1. **boundary 일치 강제**: STT phrase 끝이 identify 트리거 → boundary 어긋남 원천 제거
2. **engine 알고리즘 변경 0**: clustering / embedding 컴포넌트 재사용 (V-01 closed 자산 보존)
3. **라이브 지연 예측 가능**: phrase 길이 (~2~5초) + engine identify (~수백ms) = 명확한 지연 모델
4. **매핑 layer 제거**: adr-09 live grouping layer 폐기 → 단순한 서버 구조

## Alternatives Considered

| 대안 | 거부 사유 |
|---|---|
| (a) adr-02 Pattern B 유지 + 매핑 안정화 강화 | boundary 불일치 본질 미해결. PLAN-005 실측으로 layer 추가의 한계 확인 |
| (b) STT-engine sync barrier 구현 | 두 채널 독립 emit 유지하면서 sync 맞추기 = 동일 boundary 불일치 + 복잡도 폭증 |

## Consequences

**긍정**
- phrase boundary 일치 강제 → 라이브 매핑 정확도 향상
- engine clustering / embedding 알고리즘 변경 0 (V-01 closed 자산 보존)
- server live grouping layer (adr-09) 제거 → 서버 구조 단순화

**부정/위험**
- engine streaming context (sliding window) 활용 X — 매번 짧은 phrase PCM slice 단위 호출
- 짧은 phrase (~1~2초) embedding noise 위험 → 대응 옵션 [[spec-04-clustering-algorithms]] §9 참조 (구현 선택은 T-002)
- ElevenLabs `commit_strategy=vad` 실제 지원 여부 + 한국어 phrase 정확도 검증 필요 → T-003

## Related

- [[adr-02-pattern-b-fanout-chain]] — 폐기 대상 (본 결정으로 Superseded)
- [[adr-09-server-live-grouping]] — live grouping layer — Chain 전환 후 서버 구조에서 제거
- [[spec-04-clustering-algorithms]] — §9 Phrase-level Identification 인터페이스 명세
- [[spec-06-stt-adapter]] — commit_strategy vad 전환 결정
- [[spec-07-demo-ui-protocol]] — labeled_phrase 신규 이벤트 / 폐기 이벤트 목록
- [[planning-03-demo-v04]] — PLAN-006 작업 분해 (T-001 ~ T-006)

---

## Amendment — 2026-05-21

### 부분 회귀: PCM 학습 채널 부활 (PLAN-006-T-015)

**결정자**: admin (kknaks), PLAN-006-T-015

**유지**: STT phrase boundary 가 라이브 매핑 wire (`labeled_phrase`) 의 SSOT. `§Decision` 본체 변경 X.

**부분 부활**: adr-02 Pattern B 의 **PCM fan-out (학습 채널 only)**.

- `engine.stream()` 의 segment 출력은 server 가 소비만 하고 UI emit X (라이브 매핑 wire = `labeled_phrase` 단일 유지)
- 학습된 `_clusterer.centers` 가 누적되어 `identify_phrase` 매칭 정확도 향상

**사유**: admin smoke v4 측정 (2026-05-21):

- 2명 대화 → A/B/C/D/E 5개 라벨 split
- `engine.stream()` 호출 0회 → `_clusterer.centers = None` → `identify_phrase` 가 `_phrase_centroids` (단발) 만 사용
- V-01 의 4 컴포넌트 (OnlineSpeakerClusterer / AdaptiveReclusterScheduler / FinalReclusterer / SpeakerIdentifier) 학습 채널 부재가 본질 원인

**Amendment 후 흐름**:

```
PCM 입력 → STT.feed (continuous)
  ↓
PCM fan-out → engine.stream (학습 채널 — segment 출력 server 소비, UI emit X)
  ↓
  final (phrase 끝) → Transcript(t_start, t_end, text)
  ↓
  phrase PCM slice 추출
  ↓
  engine.identify_phrase(pcm_slice) → label    # 학습된 _clusterer.centers 와 매칭
  ↓
  ws.send_json({"type":"labeled_phrase", ...})  # 라이브 매핑 SSOT
```

**adr-02 관계**: `Superseded → Partially superseded`. engine.stream segment 출력 wire 는 여전히 폐기. PCM fan-out (학습 채널) 만 부활.

**구현**: [[spec-04-clustering-algorithms]] §9-5 (사용처 책임 명시) / PLAN-006-T-014 (realtime-api 구현)

---

## Amendment v2 — 2026-05-21 (T-025/T-026)

### §Decision 2 부분 폐기: identify_phrase phrase-level embedding → diart segment label lookup

**결정자**: admin (kknaks), PLAN-006-T-025/T-026

**유지**: STT phrase boundary 가 라이브 매핑 wire (`labeled_phrase`) 의 SSOT (§Decision 1 변경 X).

**부분 폐기**: §Decision 2 의 `identify_phrase` phrase-level embedding match 를 주요 경로에서 폐기.

admin smoke v6~v10 측정 결과:

| metric | 결과 |
|---|---|
| threshold/weight/gate knob 7개 조정 | collapse vs split 양극 오실레이션 — 안정 불가 |
| phrase-level embedding 분포 | duration 별 cluster 형성 (화자 ≠ 강한 신호) |
| 같은 화자 연속 phrase | A/B/C 3 라벨 split 관측 (v10) |

advisor 분석:
> "Phrase-level embeddings ≠ reliable speaker IDs at conversational durations. Diart is producing speaker labels and you're throwing them away in `engine_learn_loop`."

**근본 원인 — T-014 fan-out 결정의 누락**: `engine.stream` 의 SpeakerSegment yield 를 server 가 `pass` 로 무시. diart 가 sliding window context 로 정교하게 화자 분리한 결과를 활용하지 않음.

**신규 채택: diart segment label lookup**:

- `engine.stream` 이 yield 하는 `SpeakerSegment` 를 server 가 수집 → segment label map 유지
- STT final phrase 확정 시 → phrase `[t_start, t_end]` 와 overlap 하는 segments 의 dominant `speaker_id` 결정
- `identify_phrase` 는 fallback 전용 — segment 미도착 phrase (초기 구간) 한정

**Amendment v2 후 흐름**:

```
PCM 입력 → STT.feed (continuous)
  ↓
PCM fan-out → engine.stream (학습 채널 — segment yield server 수집)
  ↓
  SpeakerSegment(t_start, t_end, speaker_id) → server segment_map 에 누적
  ↓
  final (phrase 끝) → Transcript(t_start, t_end, text)
  ↓
  phrase [t_start, t_end] ∩ segment_map → dominant speaker_id 결정
  ↓
  (segment 미도착 시 fallback) engine.identify_phrase(pcm_slice) → label
  ↓
  ws.send_json({"type":"labeled_phrase", label, t_start, t_end, text})
```

**이유**: diart 의 sliding window context (OnlineSpeakerClusterer + AdaptiveReclusterScheduler + FinalReclusterer) 가 short phrase embedding noise 없이 화자 결정. AdaptiveScheduler 의 시간 감쇠 자동 작동. phrase-level embedding knob 조정 불필요.

**adr-02 관계**: 기존 §Amendment 의 `Partially superseded` 유지.

**구현**: [[spec-04-clustering-algorithms]] §9-6/§9-7 (사용처 책임 amend + identify_phrase 한계 박제) / PLAN-006-T-025 (realtime-api 구현)
