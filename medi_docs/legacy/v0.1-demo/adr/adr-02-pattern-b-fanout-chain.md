---
id: adr-02
type: adr
title: Pattern B 채택 — 엔진 출력 chain + 사용처 tee split fan-out
status: partially-superseded
created: 2026-05-14
updated: 2026-05-21
sources:
  - "[[planning-02-speaker-engine]]"
superseded_by: "[[adr-10-stt-driven-sequential-chain]]"
tags: [adr, decision, speaker-engine, integration-pattern, event-model, partially-superseded]
---

# Pattern B 채택 — 엔진 출력 chain + 사용처 tee split fan-out

## Context

speaker-engine 을 사용처(FastAPI WS 핸들러 등)에 통합하는 방식으로 두 가지 패턴이 검토되었다.

- **Pattern A (DI 방식)**: 사용처가 STT 인스턴스를 엔진에 주입. 엔진 내부에서 STT 를 직접 호출.
- **Pattern B (fan-out + chain)**: 사용처가 오디오 청크를 STT 와 engine 양쪽에 직접 분기(tee split). 엔진 출력만 이벤트 chain 으로 소비.

v0.3 에서는 `AudioChunk` passthrough 이벤트를 통해 엔진이 오디오를 STT 쪽으로도 통과시키는 구조가 있었으나, 이는 엔진이 "청크 라우터" 역할을 겸하는 단일 책임 위반임이 확인되어 v0.4 에서 제거.

## Decision

**Pattern B 채택. 엔진 인터페이스 = 이벤트 출력 chain, 오디오 입력 = 사용처가 tee split (STT 와 engine 으로 fan-out). 엔진 출력 이벤트 2종 (`SpeakerSegment | LabelChange`). `AudioChunk` passthrough 이벤트 제거.**

동작 구조:
1. 사용처가 WS 청크를 받아 `tee()` generator 를 통해 STT 와 engine 양쪽에 분기
2. 엔진은 `engine.stream(tee())` 로 오디오를 소비하여 이벤트만 yield
3. 사용처는 `async for event in engine.stream(...)` 으로 이벤트를 단일 소비

```python
# 사용처 tee split 골격 (5~10줄)
async def tee():
    async for chunk in from_websocket(ws):
        asyncio.create_task(stt.feed(chunk))  # fan-out: STT
        yield chunk                           # engine 입력
```

엔진 출력 2종:
- `SpeakerSegment` — 발화 단위 라벨 확정 이벤트
- `LabelChange` — 클러스터 재계산 후 라벨 변경 이벤트

## Why

1. **단일 책임**: 엔진은 "audio in → labeled events out" 만 책임. STT 파이프라인은 사용처 도메인.
2. **STT 자유도**: 사용처가 streaming STT / batch STT 를 자유 선택. 엔진에 영향 없음.
3. **테스트 단순화**: 화자 분리 정확도를 STT mock 없이 단독 검증 가능.
4. **chunk 라벨링 기술 불가**: overlap 시 단일 chunk 에 복수 화자 성분 혼재 → chunk 단위 라벨 부정확. 라벨 확정은 발화 단위 `SpeakerSegment` 에서만 보장.

## Alternatives Considered

| 대안 | 거부 사유 |
|---|---|
| (a) Pattern A — DI 로 STT 인스턴스를 엔진에 주입 | 결합도 ↑. STT versioning / timeout 정책 / 에러 propagation 이 엔진 책임으로 흘러옴 |
| (b) v0.3 단일 체인 (AudioChunk passthrough 부활) | 엔진이 chunk 라우터 역할 겸임 → 단일 책임 위반. 사용처 tee 5~10줄이 더 명확 |

## Consequences

**긍정**
- 엔진 단일 책임 보장: "audio chunk in → labeled events out" 만
- STT 선택 자유: streaming/batch STT 엔진 영향 없음
- 테스트 독립성: STT 없이 화자 분리만 단위 검증 가능

**부정/중립**
- 사용처가 5~10줄 tee split 작성 필요 (소량 부담)
- 청크 단위 라벨링 본질 불가 → 발화 단위 라벨만 보장 (사용처가 retroactive 매핑 필요)
- streaming STT 라면 partial 자막은 라벨 없이 먼저 노출 → 라벨은 `SpeakerSegment` 수신 후 소급

## Related

- [[planning-02-speaker-engine]] §1 단일 책임, §2 Out of Scope, §3 통합 방식
- [[adr-01-diart-wrapping-strategy]] — diart blocks 가 이벤트 생성의 기반
- [[adr-03-storage-via-env-url]] — SpeakerStore 가 stored/registered 라벨 판별에 사용
- [[adr-04-manual-persist-flow]] — 세션 종료 후 finalize → 수동 persist 흐름

---

## Partially Superseded — 2026-05-21

### 부분 폐기 결정: [[adr-10-stt-driven-sequential-chain]] 채택

**결정자**: admin (kknaks), PLAN-006-T-001

**폐기 범위 (PLAN-006-T-001)**:

1. **PLAN-005 실측** (2026-05-20, AMI 4 세션 avg):
   - streaming raw DER **19.40%** ≈ finalize DER **19.73%**
   - adr-09 서버 live grouping layer 추가에도 매핑 품질 미개선

2. **본질적 boundary 불일치 확인**:
   - engine boundary = 화자 변경 시점 (sliding window 기준)
   - STT boundary = phrase 끝 (ElevenLabs committed transcript 기준)
   - **두 boundary 는 서로 다른 이벤트 축** — 시간 매칭 layer 로는 본질 해결 불가
   - 시연 결과: "엄청 느림" / 긴 발화 (~30초) 한 줄 누적

3. **대안 검토 및 거부**: 매핑 안정화 layer 강화 / STT-engine sync barrier — 모두 boundary 불일치 본질 미해결

**대체**: [[adr-10-stt-driven-sequential-chain]] — STT phrase boundary 를 SSOT 로 삼고, engine 이 STT 의 phrase PCM slice 를 receive → 화자 라벨 반환.

### 부분 부활 (PLAN-006-T-015 Amendment)

**admin smoke v4 측정 (2026-05-21)**:
- `engine.stream()` 호출 0회 → `_clusterer.centers = None` → `identify_phrase` 가 `_phrase_centroids` (단발) 만 사용 → 2명 대화에서 A/B/C/D/E 5개 라벨 split

**부활 범위**: PCM fan-out (학습 채널 only). engine.stream 에 PCM 을 계속 공급하여 4 컴포넌트 (Online/Adaptive/Final/Identifier) 가 학습 누적 → identify_phrase 매칭 정확도 향상.

**폐기 유지**: engine.stream 의 segment 출력 → UI emit. 라이브 매핑 wire 는 `labeled_phrase` 단일 유지 (adr-10 §Decision 변경 없음).

**참조**: [[adr-10-stt-driven-sequential-chain]] §Amendment / [[spec-04-clustering-algorithms]] §9-5

**본문 보존**: 이 문서 (Pattern B 설계) 는 legacy 자산으로 유지. 향후 v0.2+ 재검토 시 참조 가능.
