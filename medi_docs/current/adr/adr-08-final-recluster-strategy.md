---
id: adr-08
type: adr
title: 세션 종료 재정렬 = HDBSCAN + online 라벨 Hungarian 보존
status: accepted
created: 2026-05-17
updated: 2026-05-17
sources:
  - "[[planning-02-speaker-engine]]"
  - "[[spec-01-speaker-engine-api]]"
  - "[[adr-01-diart-wrapping-strategy]]"
  - "[[adr-05-ws-race-defaults]]"
  - "[[reference-03-pyannote-audio-overview]]"
  - "[[reference-08-diart-streaming-structure]]"
tags: [adr, decision, speaker-engine, clustering, hdbscan, final-recluster]
---

# 세션 종료 재정렬 = HDBSCAN + online 라벨 Hungarian 보존

## Context

[[planning-02-speaker-engine]] §5 / §43 에서 "세션 종료 시 HDBSCAN 으로 누적 발화 정밀 재라벨" 을 박았고, [[planning-02-speaker-engine]] §218 / §511 에서 `FinalReclusterer` 가 우리 컴포넌트 (`engine_core/final.py`) 임을 박았다. 의존성은 [[reference-03-pyannote-audio-overview]] §77 에 `hdbscan` 으로 명시.

그러나 다음 결정은 박제 0 상태였다:
1. HDBSCAN 에 무엇을 input 으로 넣을 것인가 (발화별 평균 vs 모든 frame embedding)
2. HDBSCAN 의 결과 cluster id 를 `OnlineSpeakerClustering` 이 이미 발급한 `auto:A/B/...` 라벨과 어떻게 동기화할 것인가 — **세션 도중 사용처에게 yield 된 라벨이 finalize() 후 reshuffling 되면 사용처 부담 폭증**
3. HDBSCAN 의 noise (label=-1) 발화를 어떻게 처리할 것인가
4. `SpeakerCandidate.representative_embedding` 을 어떻게 계산할 것인가

`SpeakerEngine.finalize()` 가 반환하는 `list[SpeakerCandidate]` 가 사용처 매핑 UI 의 input 이라 — 잘못된 재라벨링은 사용자에게 직접 노출된다. 정확도와 라벨 안정성 모두 v1 요구사항.

---

## Decision

**HDBSCAN 으로 발화별 평균 embedding 을 재클러스터링하고, Hungarian matching 으로 online 시점 라벨을 최대한 보존한다. noise 발화는 가장 가까운 cluster centroid 로 흡수한다.**

| 결정 | 값 |
|---|---|
| **input** | 발화별 평균 embedding (utt 당 1 vector, L2 normalized) |
| **HDBSCAN params (default)** | `min_cluster_size=2, min_samples=1, metric="cosine", cluster_selection_epsilon=0.3, cluster_selection_method="eom"` |
| **params override** | `SpeakerEngine(final_min_cluster_size=..., final_epsilon=..., ...)` 인자로 노출 |
| **online 라벨 보존** | Hungarian assignment 로 `online cluster id ↔ HDBSCAN cluster id` 1:1 최적 매칭. 매칭 후 동일 letter (auto:A 등) 유지 |
| **noise (-1) 처리** | 해당 발화 embedding 을 모든 final cluster centroid 와 cosine 비교 → max 매칭 cluster 로 흡수 (별도 `auto:noise` 라벨 만들지 않음) |
| **representative_embedding** | cluster 내 발화의 **duration-weighted mean** + 마지막 L2 normalize 1회 |
| **LabelChange yield** | finalize 단계의 라벨 변경은 `reason="recluster"` 로 yield (별도 reason 신설 X) |

정책 본문 (input/threshold/매칭/noise/centroid 계산) 은 [[spec-04-clustering-algorithms]] §4.5 (FinalRecluster 정책) 참조. 알고리즘 의사코드 / 메서드 시그니처는 구현 단계 결정.

---

## Why

1. **발화별 평균 input** — 의료 회의 1 세션 ~수백 utterance 규모. HDBSCAN sample 수가 수백이면 실행 시간 ~수백 ms. frame 단위 (~17ms 마다 1 vector) 로 가면 sample 수 폭증해 finalize latency 가 사용처 UI 응답에 영향. 발화 평균이 도메인적으로도 자연스러움 (1 utterance = 1 화자라는 가정 위에 서비스 설계).
2. **Hungarian online 라벨 보존** — 세션 도중 `LabelChange` event 를 받은 사용처 (DB UPDATE 까지 한 상태) 입장에서, finalize 후 라벨이 완전 재shuffle 되면 추가 N건 UPDATE. Hungarian 으로 1:1 최적 매칭하면 cluster 분리/병합이 일어난 케이스에만 LabelChange 가 yield. 라벨 안정성 = 사용처 비용 절감.
3. **noise 흡수** — `min_cluster_size=2` 정책상 noise 가 발생하면 "1회 짧은 발화" 가 대부분. 별도 `auto:noise` 라벨로 노출하면 사용처 매핑 UI 에 의미 없는 entry 추가. 가장 가까운 centroid 흡수가 사용처에 깔끔.
4. **duration-weighted mean** — 짧은 응대 ("네") 와 긴 발화 (1분 진료) 가 같은 가중치면 centroid 가 짧은 발화 쪽으로 끌릴 위험. duration 가중은 안정적 centroid → `SpeakerStore.save` 시 stored 매칭 품질 ↑.
5. **online clustering 과 별도 컴포넌트로 분리** — online 은 forward streaming (이번 chunk 의 화자→centroid), final 은 retrospective (세션 전체 재라벨). 서로 다른 latency budget / data view. 동일 알고리즘으로 둘 다 처리하기엔 비효율 ([[adr-01-diart-wrapping-strategy]] 와도 일관: 검증된 알고리즘 차용 + 우리 책임은 wrap/orchestration).

---

## Alternatives Considered

| 대안 | 거부 사유 |
|---|---|
| **(a) Final recluster 안 함 — online 결과 그대로** | online 은 forward only. centroid drift 보정 불가. 누적 오류 → DER 악화 |
| **(b) k-means (k=session_speaker_count)** | k 를 사전에 모름. AdaptiveScheduler 가 세션 도중 추정한 k 를 그대로 쓰면 online 오류 그대로 전파 |
| **(c) VBxClustering** | pyannote batch pipeline 용 — streaming 친화 X. session 단위 batch 처리 가능하지만 hyperparameter 더 많고 의료 도메인 튜닝 데이터 없음. ([[reference-05-pyannote-pipeline-flow]] §3.5) |
| **(d) HDBSCAN + 라벨 reshuffling 무시 (단순 cluster id 재발급)** | 사용처 부담 폭증 — 세션 도중 yield 한 LabelChange 가 무의미해짐 |
| **(e) HDBSCAN frame-level input** | sample 수 폭증, latency 수십 초 가능. v1 finalize latency budget (~수백 ms) 초과 |
| **(f) AdaptiveRecluster 만으로 충분, finalize 시 추가 처리 X** | AdaptiveRecluster 도 online centroid 만 활용 (그게 정의). HDBSCAN 같은 density-based 방법으로 한 번 더 보정해야 cluster 경계 정밀화 |

---

## Consequences

**긍정**
- finalize() 가 사용처 매핑 UI 에 안정적 candidate 제공 — 라벨 reshuffling 최소화로 사용처 DB UPDATE 부담 ↓
- duration weighted centroid 로 `SpeakerStore.save` 시 stored 매칭 정확도 ↑
- online (diart) / adaptive (우리) / final (우리 HDBSCAN) 3 컴포넌트 책임 분리 — 단위 테스트 / 교체 가능성 ↑

**부정 / 비용**
- `hdbscan` 의존성 추가 ([[reference-03-pyannote-audio-overview]] §77 에 박힘, 비용 미미)
- Hungarian matching 필요 — scipy 가 pyannote 이미 끌어와 있어 추가 의존성 0 (구체 함수는 구현 단계 결정)
- HDBSCAN hyperparameter 4개 + epsilon — 의료 도메인 튜닝 데이터 없음. v1 default 값은 추정. **v1 릴리스 후 DER 베이스라인 측정 + 튜닝 필요** (`spec-05-test-strategy` todo)
- final recluster 시점에 발화 수 × D-dim 배열 메모리 보유 — 세션당 수백 발화 × 256D float32 ≈ 수백 KB. 무시 가능
- `finalize()` 가 동기 (R4 drain timeout 5s 내) — HDBSCAN + Hungarian 실행 시간이 이 안에 들어와야 함. v1 규모 (수백 utt × 20 cluster) 에선 안전

---

## Open Questions

| ID | 질문 | 해결 시점 |
|---|---|---|
| OQ-08-1 | HDBSCAN `cluster_selection_epsilon=0.3` 의 의료 도메인 최적값 | v1 릴리스 후 DER 측정 — `spec-05-test-strategy` (todo) |
| OQ-08-2 | duration weighted mean 의 weight 함수 — linear vs log-scale | 실측 후 결정. spec-04 §4.5 에 linear 박제 |
| OQ-08-3 | Hungarian 매칭 후 unmapped final cluster 처리 — 새 letter 발급? | 일단 새 letter 발급 (A~T 중 미사용 letter). spec-04 §4.5 박제 |

---

## 참조

- [[planning-02-speaker-engine]] — §5 / §43 (HDBSCAN 정밀 재정렬 요구), §218 (FinalReclusterer = 우리), §511 (위치)
- [[spec-01-speaker-engine-api]] — §3 `SpeakerCandidate` dataclass, §4-3 `finalize()` drain 정책
- [[adr-01-diart-wrapping-strategy]] — diart 차용 정책 (FinalRecluster 는 HDBSCAN 으로 별도, 일관성)
- [[adr-05-ws-race-defaults]] — R4 finalize drain timeout 5s
- [[reference-03-pyannote-audio-overview]] §77 — `hdbscan` 의존성 출처
- [[reference-08-diart-streaming-structure]] §5 — diart `OnlineSpeakerClustering` 와의 비교 기준
- [[spec-04-clustering-algorithms]] §4.5 — FinalRecluster 정책 본문 (input/threshold/매칭/noise/centroid)
