---
id: spec-04
type: spec
title: Clustering Algorithms 정책 명세 — Online / AdaptiveRecluster / FinalRecluster + 컴포넌트 책임 경계
status: ready
created: 2026-05-17
updated: 2026-05-19
sources:
  - "[[planning-02-speaker-engine]]"
  - "[[spec-01-speaker-engine-api]]"
  - "[[spec-02-speaker-store-schema]]"
  - "[[spec-03-diart-adapter]]"
  - "[[adr-01-diart-wrapping-strategy]]"
  - "[[adr-05-ws-race-defaults]]"
  - "[[adr-08-final-recluster-strategy]]"
  - "[[reference-08-diart-streaming-structure]]"
tags: [spec, speaker-engine, clustering, online, adaptive, hdbscan, ready]
---

# Clustering Algorithms 정책 명세

## Summary

`speaker_engine` 의 화자 식별 알고리즘 3종 (online clustering / adaptive recluster / final recluster) 의 **알고리즘 선택 / 임계값 / 데이터 흐름 / 라벨 정책** 을 박제. 클래스명·메서드 시그니처·내부 dataclass 등은 구현 단계 결정 — 본 spec 은 외부 인터페이스 경계와 정책만 다룬다.

---

## §1 Scope

### in scope (정책 결정)

- 3 컴포넌트의 책임 경계 (forward / 세션 도중 소급 / 세션 종료 정밀)
- 알고리즘 선택 — diart 차용 vs 우리 vs HDBSCAN
- 임계값 / 파라미터 default 값 + 사용처 override 허용 여부
- 데이터 흐름 (chunk 처리 1회당 컴포넌트 호출 순서 + 책임 분담)
- 라벨 매핑 정책 (global int → `auto:<letter>`, Hungarian 보존)
- noise / max_speakers 초과 / threshold 미달 처리 정책
- L2 정규화 책임 분담
- sync / async 정책 — Storage 닿는 컴포넌트만 async

### 구현 단계 결정 (본 spec 에 박지 않음)

- 클래스명 / 메서드 시그니처 / 파일 내 함수 분할
- 내부 dataclass 형태 (utterance buffer entry 구조 등)
- config override 인자명 / 인자 폭증 처리 패턴
- HDBSCAN / scipy 등 라이브러리 함수의 구체 호출 방식
- 테스트 함수명 / fixture 이름

### out of scope (다른 문서)

- diart 의 `SpeakerSegmentation` / `OverlapAwareSpeakerEmbedding` block — [[spec-03-diart-adapter]]
- `SpeakerStore.find_match` 알고리즘 — [[spec-02-speaker-store-schema]] §4-1
- 오디오 입력 (`from_websocket` 등) — [[spec-01-speaker-engine-api]] §2-2
- DER 베이스라인 측정 / 도메인 튜닝 — `spec-05-test-strategy` (todo)

---

## §2 컴포넌트 책임 경계

[[planning-02-speaker-engine]] §504-512 에 박힌 `speaker/` 디렉토리 4 모듈의 **책임 경계** 와 그 위 `SpeakerEngine` 의 orchestration 책임을 박제. 클래스 API 형태는 구현 단계 결정.

### 2-1. 4 모듈 책임 분담

| 모듈 (planning-02 §509-512) | 책임 | 알고리즘 출처 | state 보유 |
|---|---|---|---|
| `speaker/identifier.py` | registered / stored 3-tier 매칭 + L2 정규화 강제 | 우리 (cosine + threshold) | registered dict (init 시점, immutable) |
| `speaker/online.py` | chunk 단위 forward clustering (local→global centroid) | diart `OnlineSpeakerClustering` 차용 ([[adr-01-diart-wrapping-strategy]]) | active centroid 행렬 |
| `speaker/scheduler.py` | 세션 도중 주기 트리거 + 누적 발화 소급 재라벨 | 우리 (max cosine + threshold guard) | 마지막 트리거 시점 / 발화 카운터 |
| `speaker/final.py` | 세션 종료 1회 정밀 재클러스터 + Hungarian 라벨 보존 | HDBSCAN + Hungarian ([[adr-08-final-recluster-strategy]]) | stateless (호출당 1회 실행) |

### 2-2. 3-component 역할 분리 (재명시)

```
forward (이번 chunk)        → online.py
세션 도중 소급 (주기)        → scheduler.py
세션 종료 정밀 (1회)         → final.py
```

세 모듈은 동일 utterance buffer 를 본다. **utterance buffer = `SpeakerEngine` 의 SOT** — scheduler/final 은 buffer 를 인자로 받음 (자체 buffer 보유 X).

centroid state 는 `online.py` 만 보유. scheduler/final 은 호출 시점에 centroid 를 인자로 받음.

### 2-3. SpeakerEngine orchestration 책임

[[spec-01-speaker-engine-api]] §2-1 의 `SpeakerEngine` 이 4 모듈 인스턴스를 보유하고 chunk 처리 흐름 (§4-1) 을 수행한다. 그 외 SpeakerEngine 책임:

- utterance buffer SOT (세션 누적 발화)
- global centroid id → `auto:<letter>` 매핑 SOT (A~T, 의제 1.B)
- scheduler trigger 판정 호출 + 결과 LabelChange yield
- finalize 시 final 모듈 호출 + SpeakerCandidate / LabelChange 사용처 반환

---

## §3 Data Boundaries

본 spec 은 신규 dataclass 를 박지 않는다. 외부 데이터 경계만 박제:

| 데이터 | 정의 위치 | 본 spec 의 사용 |
|---|---|---|
| `SpeakerSegment` / `LabelChange` / `SpeakerCandidate` | [[spec-01-speaker-engine-api]] §3 | 컴포넌트 출력 — 본 spec §4 흐름이 yield/반환 대상 명시 |
| segmentation + embedding 텐서 | [[spec-03-diart-adapter]] §3 | online clustering input |
| `SpeakerStore.find_match` 반환 | [[spec-02-speaker-store-schema]] §2 | identifier 가 호출 |

utterance buffer entry 의 내부 구조, 컴포넌트 config 객체 형태 등은 **구현 단계 결정** — 본 spec 의 정책 (lock 여부, override 허용 여부) 만 정의한다.

---

## §4 동작 정책

### 4-1. chunk 처리 흐름 (per 10s window)

```
audio bytes
    ↓ (WaveformBuffer 누적 — spec-03)
[10s window 채워짐]
    ↓
diart_adapter.process_window(window)  →  segmentation + raw embeddings
    ↓
[L2 normalize 강제]                      ← identifier 책임 (§4-2)
    ↓
online clustering (forward)              →  local→global centroid 매핑
    ↓ (각 active speaker 의 embedding 별)
identifier 3-tier 매칭                    →  registered / stored / auto
    ↓
SpeakerEngine: utterance buffer append + global idx → letter 매핑
    ↓
yield SpeakerSegment
    ↓
(주기 조건 충족 시) scheduler trigger      →  소급 재라벨
    ↓
yield LabelChange* (reason="recluster")
```

### 4-2. L2 정규화 책임

- **위치**: identifier 모듈이 utterance embedding 단에서 1회 강제 수행
- **이유**: pyannote/embedding 모델 자체는 정규화 안 함 ([[reference-07-pyannote-embedding-code]]). diart 의 `EmbeddingNormalization` 은 frame 단위에서 수행하지만 우리는 utterance 단위 (frame mean 이후) 에서 한 번 더 강제 — cosine 비교의 정합성 보장
- **zero vector 입력**: 정책상 발생 안 해야 함. 발생 시 즉시 예외 raise

### 4-3. Online clustering 정책 (의제 1 합의)

| 항목 | 정책 |
|---|---|
| 알고리즘 | diart `OnlineSpeakerClustering` 그대로 차용. 자체 재구현 X ([[adr-01-diart-wrapping-strategy]]) |
| 3 임계값 default | `tau_active=0.6` / `rho_update=0.3` / `delta_new=1.0` (diart `SpeakerDiarizationConfig` default, [[reference-08-diart-streaming-structure]] §5) |
| override | `SpeakerEngine.__init__` 인자로 노출 (인자명은 구현 단계 결정) |
| `max_speakers` | default 20 ([[planning-02-speaker-engine]] §582), 인자 조정 가능 |
| centroid update | diart 단순 누적 합 정책 그대로. L2 normalized embedding 가정 |
| global idx → 라벨 | `auto:A` ~ `auto:T` (A-Z 순차, max=20 → T). letter 매핑은 SpeakerEngine SOT |
| identifier 결과 vs online 결과 충돌 | registered/stored 라벨 우선. 단 online centroid 는 동일 embedding 으로 갱신 (state 일관성) |
| 세션 격리 | 인스턴스 단위. 같은 인스턴스 2회 진입 시 `RuntimeError` ([[adr-05-ws-race-defaults]] R2). reset API 없음 |
| `max_speakers` 초과 | diart 동작 그대로 (가장 가까운 active centroid 강제 매핑) + WARN 로그. 별도 예외 raise X |

### 4-4. AdaptiveRecluster 정책 (의제 2 합의)

| 항목 | 정책 |
|---|---|
| 컴포넌트 출처 | 우리 ([[planning-02-speaker-engine]] §218) |
| 실행 시점 | chunk 처리 후 동기 inline ([[adr-05-ws-race-defaults]] R3) |
| 트리거 | "신규 발화 ≥ 10 OR 마지막 트리거 후 ≥ 30초" 하이브리드 (OR 조건). default 박제 + override 허용 |
| 재계산 범위 | 세션 누적 전체 발화. 단 `registered:*` / `stored:*` 라벨이 잠긴 발화는 대상 제외 |
| 라벨 재할당 | 각 발화 embedding → 모든 active online centroid 와 cosine 최대 매칭 |
| threshold guard | 매칭 max cosine 이 `delta_new` (cosine distance 환산) 보다 낮으면 변경 거부 — 현재 라벨 유지 |
| 결과 yield | `LabelChange(reason="recluster", affected_utterance_ids=[...])` — (old_label, new_label) 쌍별로 1 event ([[spec-01-speaker-engine-api]] §3) |
| latency 정책 | v1 cap 없음. 의료 회의 규모 (수십~수백 발화 × 20 centroid) 에서 ~수십 ms 예상. 측정 후 v2 에 cap 도입 검토 |

### 4-5. FinalRecluster 정책 (의제 3 합의, [[adr-08-final-recluster-strategy]])

| 항목 | 정책 |
|---|---|
| 알고리즘 | HDBSCAN ([[reference-03-pyannote-audio-overview]] §77 의 `hdbscan` 의존성 활용) |
| 실행 시점 | `engine.finalize()` 호출 시 1회. drain timeout = 5s ([[adr-05-ws-race-defaults]] R4) 안에 완료 |
| 대상 | `auto:*` 발화만. `registered:*` / `stored:*` 발화는 영속 화자라 제외 |
| input 단위 | **발화별 평균 embedding** (utterance 당 1 vector). frame 단위 입력 거부 (latency 폭증) |
| HDBSCAN params (default) | `min_cluster_size=2, min_samples=1, metric="cosine", cluster_selection_epsilon=0.3, cluster_selection_method="eom"` |
| params override | `SpeakerEngine.__init__` 인자로 노출 (인자명은 구현 단계 결정) |
| online 라벨 보존 | Hungarian assignment 으로 online cluster ↔ HDBSCAN cluster 1:1 최적 매칭 — 매칭 후 동일 letter (auto:A 등) 유지 |
| Hungarian cost threshold | cosine distance > 0.5 매칭 거부 (서로 다른 사람으로 판단). default 박제 + override 허용 |
| unmapped final cluster | 새 letter 발급 (A~T 중 미사용). 발급 순서는 cluster id 오름차순 |
| noise (-1) 발화 | 가장 가까운 final centroid 로 흡수. 별도 `auto:noise` 라벨 만들지 않음 |
| 전부 noise 케이스 | 단일 cluster 로 묶음 + WARN 로그 |
| `representative_embedding` (SpeakerCandidate) | cluster 내 발화의 **duration-weighted mean** (linear) + 마지막 L2 normalize 1회 |
| LabelChange yield | finalize 단계 라벨 변경도 `reason="recluster"` 사용. 별도 reason 신설 X |

### 4-6. sync / async 정책 (의제 4.D 합의)

| 컴포넌트 책임 | sync/async |
|---|---|
| online clustering (numpy 연산) | sync |
| L2 정규화 (numpy 연산) | sync |
| identifier — registered 매칭 (in-memory dict) | sync 가능 |
| identifier — stored 매칭 (`SpeakerStore.find_match` 호출) | **async** (Storage I/O) |
| scheduler recluster (numpy 연산) | sync |
| final recluster (HDBSCAN sync API) | sync |
| `SpeakerEngine.stream()` | async generator (전체 orchestration) |

원칙: Storage 닿는 컴포넌트만 async. 순수 numpy 연산 sync. `SpeakerEngine.stream()` 만 async generator.

### 4-7. Protocol vs concrete (의제 4.E 합의)

- `SpeakerStore` 만 Protocol ([[spec-02-speaker-store-schema]]) — backend 교체 가능
- `speaker/` 4 모듈은 concrete — v1 단일 구현. v2 에 교체 가능성 등장하면 Protocol 화 검토

---

## §5 오류 / 예외 정책

본 spec 은 신규 예외를 박지 않는다. [[spec-01-speaker-engine-api]] §5 의 예외 정책에 본 컴포넌트의 발생 케이스를 매핑만 한다.

| spec-01 §5 정의 예외 | 본 컴포넌트의 발생 케이스 |
|---|---|
| `ValueError` | L2 정규화 시 zero vector 입력 (정책상 발생 안 해야 함) |
| `RuntimeError` (R2) | `engine.stream()` 동일 인스턴스 2회 진입 (세션 격리 정책) |
| `TimeoutError` (R4) | `finalize()` drain timeout (5s) 초과 — HDBSCAN 실행 포함 |
| soft error (WARN) | `max_speakers` 초과 시 diart 강제 매핑 / HDBSCAN 전부 noise |
| soft error (INFO) | Hungarian 매칭 전부 threshold 초과로 거부 (모든 final cluster 가 새 letter) |

예외 신설 없음. 모델 D 불일치 같은 케이스도 spec-01 §5 의 `RuntimeError` 로 흡수.

---

## §6 검증 시나리오 (정책 검증 — 구체 테스트 함수는 spec-05-test-strategy todo)

본 spec 의 정책이 워커 구현 후 충족되는지 확인할 **시나리오 카테고리** 만 박제. 구체 test 함수명·fixture·case 분할은 `spec-05-test-strategy` (todo) 에서 결정.

| 카테고리 | 검증할 정책 |
|---|---|
| 단일 화자 reliability | 1명 화자 N 발화 → letter 일관 유지 (online idx 안정) |
| 화자 분리 정확도 | 2명 교대 발화 → 2 letter 발급 + AdaptiveRecluster 가 라벨 안정 유지 |
| Final 재정렬 효과 | 의도적 online drift fixture → FinalRecluster 가 분리/병합 + Hungarian 으로 letter 보존 |
| Lock 정책 | registered/stored 발화는 Adaptive/Final 영향 X |
| Noise 흡수 | HDBSCAN noise (-1) → 가장 가까운 centroid 로 흡수, `SpeakerCandidate` 에 noise entry 없음 |
| max_speakers 초과 | WARN 로그 + diart 강제 매핑, exception X |
| Duration weighted centroid | 짧은 발화 + 긴 발화 mix → centroid 가 긴 발화 쪽으로 치우침 |
| Hungarian threshold | cosine distance > 0.5 매칭 거부 → 새 letter 발급 |
| Empty session finalize | 발화 0건 finalize → 빈 후보/이벤트 반환, exception X |
| L2 정규화 강제 | zero vector 입력 → `ValueError` (정책상 발생 안 해야 함) |

---

## §7 의존성

| 패키지 | 출처 | 본 spec 의 용도 |
|---|---|---|
| `diart >= 0.9` | [[spec-01-speaker-engine-api]] §7 | online clustering 알고리즘 차용 |
| `hdbscan` | [[reference-03-pyannote-audio-overview]] §77 (pyannote 이 끌어옴) | final recluster |
| `numpy` | 코어 | embedding 연산 |
| `scipy` | pyannote 이 끌어옴 | Hungarian assignment 라이브러리 (구체 함수는 구현 단계) |

추가 의존성 0 — 기존 박힌 의존성 재사용.

---

## §OQ 후속 박제 대상 (Open Questions)

| ID | 질문 | 상태 | closure 근거 / 해결 시점 |
|---|---|---|---|
| OQ-04-1 | `delta_new` cosine distance 환산 임계 — 의료 도메인 최적값 | **deferred (v1.1)** | [[runbook-01-engine-tuning]] §5: 도메인 audio 측정 후 재튜닝 |
| OQ-04-2 | Hungarian cost threshold (default 0.5) 의 의료 도메인 최적값 | **closed (V-01)** | [[runbook-01-engine-tuning]] §3-3 + §4-(3): pyannote.metrics label-invariance 로 DER eval 에서 grid tuning 무의미. 실시간 streaming label consistency 에는 유효. 별도 metric (label-fixed DER) 도입 시 v1.1 재논의 |
| OQ-04-3 | HDBSCAN noise 흡수 후 centroid 재계산 정책 — v1 은 흡수 전 centroid 사용 | open | v2 에 noise 비율 측정 후 |
| OQ-04-4 | duration weight 함수 — linear vs log-scale ([[adr-08-final-recluster-strategy]] OQ-08-2 동일) | open | linear 유지, 실측 후 재검토 |
| OQ-04-5 | scheduler / final / identifier 의 클래스 API 형태 (메서드 시그니처 / config 객체 / override 인자 prefix) | **구현 단계 결정** | 본 spec 의 정책을 만족하는 한 워커 자유도 |
| OQ-04-6 | utterance buffer entry 의 내부 dataclass 형태 (lock 플래그 / 라벨 / embedding 보관 등) | **구현 단계 결정** | SpeakerEngine 내부 |

---

## §8 참조

- [[planning-02-speaker-engine]] — §41 (3-tier threshold), §43 (HDBSCAN 정밀 재정렬), §218 (Adaptive/Final = 우리), §504-512 (디렉토리), §582 (max_speakers=20)
- [[spec-01-speaker-engine-api]] — §2-1 (`SpeakerEngine` API), §3 (`SpeakerCandidate` / `LabelChange` dataclass), §4-3 (`finalize()` drain), §5 (예외 정책)
- [[spec-02-speaker-store-schema]] — §4-1 (`SpeakerStore.find_match` — identifier 가 호출)
- [[spec-03-diart-adapter]] — `DiartAdapter.process_window()` 출력 (segmentation + embeddings)
- [[adr-01-diart-wrapping-strategy]] — diart 차용 정책
- [[adr-05-ws-race-defaults]] — R2 (세션 격리) / R3 (inline recluster) / R4 (drain timeout 5s)
- [[adr-08-final-recluster-strategy]] — FinalRecluster architectural 결정 (HDBSCAN + Hungarian)
- [[reference-07-pyannote-embedding-code]] — L2 정규화 책임 분담 근거
- [[reference-08-diart-streaming-structure]] §5 — diart `OnlineSpeakerClustering` 본문
- [[reference-03-pyannote-audio-overview]] §77 — `hdbscan` / `scipy` 의존성 출처
