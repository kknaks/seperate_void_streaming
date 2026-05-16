---
id: planning-01
type: planning
title: 피부과 실시간 상담 노트 시스템 — 단계별 적용 계획
status: draft
created: 2026-05-14
updated: 2026-05-14
sources: []
tags: [planning, consultation, realtime, diart, stt, llm]
---

# 피부과 실시간 상담 노트 시스템 — 단계별 적용 계획

> 다인 상담 환경(상담사 1명 + 고객 1~3명)에서 실시간으로 화자를 구분하고, 화자별 시술 추천을 팝업으로 제공하는 시스템.

---

## 0. 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────┐
│ [브라우저 클라이언트]                                          │
│   - 마이크 입력 (WebRTC / MediaRecorder)                      │
│   - 실시간 추천 팝업 UI                                        │
│   - 화자별 발화 누적 표시                                      │
└──────────────────────────────────────────────────────────────┘
                            │ WebSocket (오디오 스트림)
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ [서버 (Python, FastAPI)]                                      │
│                                                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐  │
│  │ diart           │  │ STT 엔진         │  │ LLM 추천      │  │
│  │ (화자 분리 +    │→ │ (이미 구현됨,    │→ │ (Claude/GPT) │  │
│  │  embedding 추출) │  │  엔진화 대상)    │  │              │  │
│  └─────────────────┘  └─────────────────┘  └──────────────┘  │
│           │                                                    │
│           ▼                                                    │
│  ┌─────────────────────────────────────────────┐              │
│  │ Online Clusterer (고객 A/B/C 구분)            │              │
│  │  + Time-decaying Reclustering Scheduler      │              │
│  │  + Final Reclustering (상담 종료 시)          │              │
│  └─────────────────────────────────────────────┘              │
│           │                                                    │
│           ▼                                                    │
│  ┌─────────────────────────────────────────────┐              │
│  │ DB (PostgreSQL)                              │              │
│  │  - 직원 embedding (영구)                      │              │
│  │  - 상담 세션, 발화 로그, 추천 결과            │              │
│  └─────────────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────────┘
```

---

## 1. 기술 스택 결정

| 영역 | 선택 | 비고 |
|---|---|---|
| 화자 분리 | **diart** (pyannote 기반 스트리밍) | 실시간 필수 |
| Embedding 모델 | `pyannote/embedding` (512차원) | 등록/실시간 동일 모델 |
| Segmentation 모델 | `pyannote/segmentation-3.0` | overlap-aware |
| STT | (기존 구현 활용) | 엔진화하여 인터페이스 정의 |
| 백엔드 | FastAPI + WebSocket | Python 생태계 일관성 |
| 큐/비동기 | asyncio (단순) 또는 Celery (확장 시) | MVP는 asyncio |
| DB | PostgreSQL + pgvector | embedding 저장에 pgvector 유용 |
| LLM | Claude API (Haiku 추천) | 비용 + 한국어 품질 |
| 클러스터링 | scipy + scikit-learn + hdbscan | 표준 라이브러리 |

### HuggingFace 사전 작업

```bash
# pyannote 모델은 사용 동의 필요
# https://huggingface.co/pyannote/segmentation-3.0 → "Accept" 클릭
# https://huggingface.co/pyannote/embedding → "Accept" 클릭

pip install diart pyannote-audio scipy scikit-learn hdbscan numpy
```

---

## 2. STT 엔진화 (인터페이스 정의)

기존 STT 구현을 갈아끼울 수 있도록 **추상 인터페이스**로 감싸기.

### 추상 클래스

```python
# stt/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

@dataclass
class TranscriptionSegment:
    text: str
    start_time: float          # 청크 내 상대 시작 시간 (초)
    end_time: float
    confidence: float          # 0~1
    is_final: bool             # False면 partial (스트리밍 도중)

class STTEngine(ABC):
    """모든 STT 엔진이 따라야 할 인터페이스"""

    @abstractmethod
    async def initialize(self) -> None:
        """모델 로드 등 초기화"""
        pass

    @abstractmethod
    async def transcribe_chunk(
        self,
        audio_chunk: bytes,       # PCM 16kHz mono
        sample_rate: int = 16000,
    ) -> TranscriptionSegment:
        """오디오 청크를 텍스트로 변환 (동기 호출)"""
        pass

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
    ) -> AsyncIterator[TranscriptionSegment]:
        """실시간 스트림 → partial + final 결과 yield"""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """리소스 정리"""
        pass
```

### 구현 예시 (기존 STT를 래핑)

```python
# stt/your_stt_engine.py
class YourSTTEngine(STTEngine):
    def __init__(self, config: dict):
        self.config = config
        self.client = None

    async def initialize(self):
        # 기존 STT 초기화 코드 여기로
        self.client = YourExistingSTT(**self.config)

    async def transcribe_chunk(self, audio_chunk, sample_rate=16000):
        result = await self.client.process(audio_chunk)
        return TranscriptionSegment(
            text=result.text,
            start_time=result.start,
            end_time=result.end,
            confidence=result.score,
            is_final=True,
        )

    async def transcribe_stream(self, audio_stream):
        async for chunk in audio_stream:
            async for partial in self.client.stream(chunk):
                yield TranscriptionSegment(
                    text=partial.text,
                    start_time=partial.start,
                    end_time=partial.end,
                    confidence=partial.score,
                    is_final=partial.is_final,
                )

    async def shutdown(self):
        await self.client.close()
```

### 사용 측

```python
# 어디서든 STT 엔진을 갈아끼울 수 있음
stt: STTEngine = YourSTTEngine(config={"api_key": "..."})
# stt: STTEngine = WhisperSTTEngine(model="large-v3")
# stt: STTEngine = ClovaSTTEngine(api_key="...")

await stt.initialize()
result = await stt.transcribe_chunk(audio_bytes)
```

---

## 3. 직원 Embedding 등록 (1회성)

### 등록 스크립트

```python
# scripts/register_staff.py
import numpy as np
from pyannote.audio import Model, Inference
from pathlib import Path
import psycopg2  # 또는 SQLAlchemy

HF_TOKEN = "hf_xxxxx"

def register_staff(name: str, audio_file: str, db_conn):
    """
    직원 음성 샘플(30초~1분)에서 embedding을 추출하여 DB에 저장.

    audio_file: 16kHz mono WAV 권장
    """
    model = Model.from_pretrained("pyannote/embedding", use_auth_token=HF_TOKEN)
    inferencer = Inference(model, window="whole")

    embedding = inferencer(audio_file)  # numpy array, shape (512,)

    assert embedding.shape == (512,), f"예상 외 shape: {embedding.shape}"

    # DB 저장 (pgvector 사용 시)
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO staff (name, embedding, created_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (name) DO UPDATE
              SET embedding = EXCLUDED.embedding,
                  updated_at = NOW();
            """,
            (name, embedding.tolist()),
        )
    db_conn.commit()
    print(f"✓ {name} 등록 완료 (shape={embedding.shape})")

if __name__ == "__main__":
    import sys
    conn = psycopg2.connect("postgresql://...")
    register_staff(
        name=sys.argv[1],
        audio_file=sys.argv[2],
        db_conn=conn,
    )
```

### DB 스키마 (PostgreSQL + pgvector)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE staff (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    embedding   vector(512) NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE consultation_session (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      TIMESTAMP DEFAULT NOW(),
    ended_at        TIMESTAMP,
    staff_id        INT REFERENCES staff(id),
    customer_count  INT,
    metadata        JSONB
);

CREATE TABLE utterance (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID REFERENCES consultation_session(id),
    speaker_label   TEXT NOT NULL,        -- "staff:김원장" or "customer:A"
    text            TEXT,
    embedding       vector(512),
    start_time      FLOAT,                -- 세션 시작 기준 초
    end_time        FLOAT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE recommendation (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID REFERENCES consultation_session(id),
    customer_label  TEXT NOT NULL,
    procedures      JSONB,                -- [{"name": "보톡스", "confidence": 0.8}, ...]
    triggered_by    BIGINT REFERENCES utterance(id),
    created_at      TIMESTAMP DEFAULT NOW()
);
```

### 등록 가이드 (운영자용)

- 녹음 길이: **30초~1분**
- 환경: **실제 상담실 마이크와 동일**한 환경
- 내용: 자연스러운 대화체 (예: "안녕하세요, 오늘 어떤 시술 상담 받으러 오셨어요? 어떤 부분이 가장 고민이세요?")
- 재등록 주기: **6개월~1년** 또는 인식 정확도 저하 시

---

## 4. 화자 식별 모듈 (상담사 vs 고객)

```python
# speaker/staff_identifier.py
import numpy as np
from scipy.spatial.distance import cosine

class StaffIdentifier:
    """등록된 직원 embedding과 비교하여 상담사 여부 판단"""

    def __init__(self, staff_embeddings: dict[str, np.ndarray], threshold: float = 0.7):
        """
        staff_embeddings: {"김원장": np.ndarray(512), "이실장": ...}
        threshold: 코사인 유사도 임계값 (0.65~0.75 사이에서 조정)
        """
        self.staff = staff_embeddings
        self.threshold = threshold

    def identify(self, embedding: np.ndarray) -> tuple[str | None, float]:
        """
        Returns:
            (직원 이름, 유사도 점수)
            매칭 안 되면 (None, best_score)
        """
        if np.isnan(embedding).any():
            return None, 0.0

        best_name, best_score = None, 0.0
        for name, ref_emb in self.staff.items():
            score = 1 - cosine(embedding, ref_emb)
            if score > best_score:
                best_name, best_score = name, score

        if best_score >= self.threshold:
            return best_name, best_score
        return None, best_score
```

---

## 5. 온라인 클러스터링 (고객 A/B/C 구분)

```python
# speaker/online_clusterer.py
import numpy as np
from scipy.spatial.distance import cosine
from collections import deque
from datetime import datetime

class OnlineSpeakerClusterer:
    def __init__(
        self,
        similarity_threshold: float = 0.7,
        max_speakers: int = 5,
        max_history_per_speaker: int = 50,
        merge_threshold: float = 0.85,
    ):
        self.threshold = similarity_threshold
        self.max_speakers = max_speakers
        self.max_history = max_history_per_speaker
        self.merge_threshold = merge_threshold
        self.speakers: dict[str, deque] = {}
        self.metadata: dict[str, dict] = {}
        self._next_id = 0

    def _new_speaker_id(self) -> str:
        label = chr(ord('A') + self._next_id)
        self._next_id += 1
        return f"customer:{label}"

    def _centroid(self, sid: str) -> np.ndarray:
        return np.array(self.speakers[sid]).mean(axis=0)

    def _similarity(self, emb: np.ndarray, sid: str) -> float:
        return 1 - cosine(emb, self._centroid(sid))

    def assign(self, embedding: np.ndarray) -> tuple[str, float, bool]:
        """Returns (speaker_id, similarity, is_new_speaker)"""
        if np.isnan(embedding).any():
            return None, 0.0, False

        if not self.speakers:
            new_id = self._new_speaker_id()
            self._create_speaker(new_id, embedding)
            return new_id, 1.0, True

        scores = {sid: self._similarity(embedding, sid) for sid in self.speakers}
        best_id = max(scores, key=scores.get)
        best_score = scores[best_id]

        if best_score >= self.threshold:
            self._update_speaker(best_id, embedding)
            return best_id, best_score, False

        if len(self.speakers) >= self.max_speakers:
            # 최대 인원 초과 시 가장 가까운 곳에 강제 배치
            self._update_speaker(best_id, embedding)
            return best_id, best_score, False

        new_id = self._new_speaker_id()
        self._create_speaker(new_id, embedding)
        return new_id, best_score, True

    def _create_speaker(self, sid, emb):
        self.speakers[sid] = deque([emb], maxlen=self.max_history)
        self.metadata[sid] = {
            "created_at": datetime.now(),
            "last_seen_at": datetime.now(),
            "utterance_count": 1,
        }

    def _update_speaker(self, sid, emb):
        self.speakers[sid].append(emb)
        self.metadata[sid]["last_seen_at"] = datetime.now()
        self.metadata[sid]["utterance_count"] += 1
```

---

## 6. 시간 감쇠 재클러스터링 스케줄러

```python
# speaker/recluster_scheduler.py
import math
import time

class AdaptiveReclusterScheduler:
    """
    초반에는 자주, 후반에는 드물게 재클러스터링.
    interval = base * (1 + elapsed)^decay
    decay=0.5 → sqrt 곡선
    """
    def __init__(
        self,
        base_interval: float = 5.0,
        max_interval: float = 60.0,
        decay_rate: float = 0.5,
    ):
        self.start_time = time.time()
        self.last_recluster_time = time.time()
        self.base = base_interval
        self.max = max_interval
        self.decay = decay_rate

    def current_interval(self) -> float:
        elapsed = time.time() - self.start_time
        interval = self.base * math.pow(1 + elapsed, self.decay)
        return min(interval, self.max)

    def should_recluster(self) -> bool:
        now = time.time()
        if now - self.last_recluster_time >= self.current_interval():
            self.last_recluster_time = now
            return True
        return False
```

### 감쇠 곡선 미리보기

| 경과 시간 | 다음 재클러스터링 간격 |
|---|---|
| 0초 | 5초 |
| 30초 | 27.8초 |
| 60초 | 39.1초 |
| 120초 | 55.0초 |
| 300초+ | 60초 (max) |

---

## 7. 중간 재클러스터링 (Online Reclustering)

```python
# speaker/online_clusterer.py 에 메서드 추가
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import AgglomerativeClustering

def recluster(self) -> dict:
    """누적된 embedding으로 Agglomerative 재클러스터링 + 라벨 일관성 유지"""
    all_embs, all_labels = [], []
    for sid, embs in self.speakers.items():
        for emb in embs:
            all_embs.append(emb)
            all_labels.append(sid)

    if len(all_embs) < 4:
        return {"changed": False}

    all_embs = np.array(all_embs)

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=1 - self.threshold,
        metric="cosine",
        linkage="average",
    )
    new_labels = clustering.fit_predict(all_embs)

    mapping = self._match_labels(all_labels, new_labels)

    new_speakers = {}
    for emb, lbl in zip(all_embs, new_labels):
        mapped = mapping[lbl]
        if mapped not in new_speakers:
            new_speakers[mapped] = deque(maxlen=self.max_history)
        new_speakers[mapped].append(emb)

    diff = {
        "merged": [k for k in self.speakers if k not in new_speakers],
        "split": [k for k in new_speakers if k not in self.speakers],
        "before": len(self.speakers),
        "after": len(new_speakers),
        "changed": True,
    }
    self.speakers = new_speakers
    return diff

def _match_labels(self, old_labels, new_labels) -> dict:
    """헝가리안 알고리즘으로 새 라벨 ↔ 기존 라벨 매칭"""
    old_unique = list(set(old_labels))
    new_unique = list(set(new_labels))

    overlap = np.zeros((len(new_unique), len(old_unique)))
    for i, new in enumerate(new_unique):
        for j, old in enumerate(old_unique):
            count = sum(1 for nl, ol in zip(new_labels, old_labels)
                       if nl == new and ol == old)
            overlap[i, j] = -count

    row_ind, col_ind = linear_sum_assignment(overlap)

    mapping = {}
    for r, c in zip(row_ind, col_ind):
        mapping[new_unique[r]] = old_unique[c]

    for new in new_unique:
        if new not in mapping:
            mapping[new] = self._new_speaker_id()

    return mapping
```

---

## 8. 최종 재정렬 (Final Reclustering)

상담 종료 시점에 **HDBSCAN으로 가장 정확하게 재구성**.

```python
# speaker/final_reclusterer.py
import numpy as np
import hdbscan
from scipy.optimize import linear_sum_assignment
from dataclasses import dataclass

@dataclass
class UtteranceRecord:
    """DB에서 가져온 발화 기록"""
    utterance_id: int
    embedding: np.ndarray
    original_label: str        # 실시간 처리 시 부여된 라벨
    text: str
    start_time: float
    end_time: float

@dataclass
class FinalAssignment:
    utterance_id: int
    original_label: str
    final_label: str           # 재정렬 후 라벨
    confidence: float          # HDBSCAN의 멤버십 점수

class FinalReclusterer:
    """
    상담 종료 후 전체 발화를 가지고 정밀 재클러스터링.
    HDBSCAN 기반 (노이즈 자동 제거 + 클러스터 수 자동 결정).
    """

    def __init__(
        self,
        min_cluster_size: int = 3,
        min_samples: int = 2,
        metric: str = "cosine",
        cluster_selection_method: str = "eom",
    ):
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.metric = metric
        self.cluster_selection_method = cluster_selection_method

    def recluster(
        self,
        utterances: list[UtteranceRecord],
        staff_label: str | None = None,
    ) -> list[FinalAssignment]:
        """
        utterances: 세션의 모든 발화 (상담사 발화도 포함 가능)
        staff_label: 상담사 라벨 (있으면 그대로 유지, 클러스터링에서 제외)

        Returns: 발화별 최종 라벨 매핑
        """
        # 1. 상담사 발화 분리
        staff_utts = [u for u in utterances if u.original_label == staff_label] if staff_label else []
        customer_utts = [u for u in utterances if u.original_label != staff_label]

        if len(customer_utts) < self.min_cluster_size:
            # 데이터 부족 → 원래 라벨 유지
            return [
                FinalAssignment(u.utterance_id, u.original_label, u.original_label, 1.0)
                for u in utterances
            ]

        # 2. 고객 embedding 행렬
        embeddings = np.array([u.embedding for u in customer_utts])

        # cosine 사용 시 L2 정규화
        if self.metric == "cosine":
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            embeddings = embeddings / np.maximum(norms, 1e-9)
            metric_for_hdbscan = "euclidean"  # 정규화 후 유클리드 = 코사인과 동등
        else:
            metric_for_hdbscan = self.metric

        # 3. HDBSCAN
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            metric=metric_for_hdbscan,
            cluster_selection_method=self.cluster_selection_method,
        )
        new_labels = clusterer.fit_predict(embeddings)
        probabilities = clusterer.probabilities_

        # 4. -1(노이즈)은 가장 가까운 클러스터에 강제 배치
        new_labels = self._reassign_noise(embeddings, new_labels)

        # 5. 기존 라벨과 매칭 (라벨 일관성)
        original_labels = [u.original_label for u in customer_utts]
        mapping = self._hungarian_match(original_labels, new_labels)

        # 6. 결과 조립
        assignments = []
        for u, new_lbl, prob in zip(customer_utts, new_labels, probabilities):
            assignments.append(FinalAssignment(
                utterance_id=u.utterance_id,
                original_label=u.original_label,
                final_label=mapping[new_lbl],
                confidence=float(prob),
            ))

        # 상담사 발화는 그대로
        for u in staff_utts:
            assignments.append(FinalAssignment(
                utterance_id=u.utterance_id,
                original_label=u.original_label,
                final_label=u.original_label,
                confidence=1.0,
            ))

        # utterance_id 순으로 정렬
        assignments.sort(key=lambda x: x.utterance_id)
        return assignments

    def _reassign_noise(self, embeddings, labels):
        """HDBSCAN의 -1(노이즈) 점을 가장 가까운 클러스터로 재배치"""
        if -1 not in labels:
            return labels

        labels = labels.copy()
        cluster_ids = [c for c in set(labels) if c != -1]
        if not cluster_ids:
            # 모두 노이즈 → 단일 클러스터로
            return np.zeros_like(labels)

        # 각 클러스터 centroid 계산
        centroids = {
            c: embeddings[labels == c].mean(axis=0)
            for c in cluster_ids
        }

        for i, lbl in enumerate(labels):
            if lbl != -1:
                continue
            # 가장 가까운 centroid
            best_c, best_d = None, float("inf")
            for c, cent in centroids.items():
                d = np.linalg.norm(embeddings[i] - cent)
                if d < best_d:
                    best_c, best_d = c, d
            labels[i] = best_c

        return labels

    def _hungarian_match(self, old_labels, new_labels) -> dict:
        """새 클러스터 ↔ 기존 라벨 최적 매칭"""
        old_unique = sorted(set(old_labels))
        new_unique = sorted(set(new_labels))

        overlap = np.zeros((len(new_unique), len(old_unique)))
        for i, new in enumerate(new_unique):
            for j, old in enumerate(old_unique):
                count = sum(1 for nl, ol in zip(new_labels, old_labels)
                           if nl == new and ol == old)
                overlap[i, j] = -count

        row_ind, col_ind = linear_sum_assignment(overlap)

        mapping = {}
        used_old = set()
        for r, c in zip(row_ind, col_ind):
            mapping[new_unique[r]] = old_unique[c]
            used_old.add(old_unique[c])

        # 매칭 안 된 새 클러스터는 새 라벨 부여
        next_label_idx = 0
        for new in new_unique:
            if new not in mapping:
                # 사용되지 않은 알파벳 찾기
                while True:
                    candidate = f"customer:{chr(ord('A') + next_label_idx)}"
                    next_label_idx += 1
                    if candidate not in used_old:
                        mapping[new] = candidate
                        break

        return mapping
```

### 최종 재정렬 호출 흐름

```python
# 상담 종료 시
async def on_session_end(session_id: str):
    # 1. DB에서 모든 발화 로드
    utterances = await load_utterances(session_id)

    # 2. 최종 재정렬
    reclusterer = FinalReclusterer(min_cluster_size=3)
    final = reclusterer.recluster(
        utterances,
        staff_label="staff:김원장",
    )

    # 3. DB 업데이트
    async with db.transaction():
        for assignment in final:
            await db.execute(
                "UPDATE utterance SET final_label = $1, recluster_confidence = $2 WHERE id = $3",
                assignment.final_label,
                assignment.confidence,
                assignment.utterance_id,
            )

    # 4. LLM에 전체 정리된 대화 전달 → 최종 상담 노트 생성
    final_transcript = await build_transcript(session_id)
    consultation_note = await llm.summarize(final_transcript)

    return consultation_note
```

---

## 9. 전체 통합 (실시간 처리 루프)

```python
# server/realtime_pipeline.py
import asyncio
import numpy as np
from diart.sources import WebSocketAudioSource
from diart.blocks import SpeakerSegmentation, OverlapAwareSpeakerEmbedding
import rx.operators as ops
import diart.operators as dops

class ConsultationPipeline:
    def __init__(self, session_id: str, stt_engine: STTEngine):
        self.session_id = session_id
        self.stt = stt_engine

        # 직원 embedding 로드 (DB에서)
        staff_embs = load_staff_embeddings()
        self.staff_identifier = StaffIdentifier(staff_embs, threshold=0.7)

        # 고객 클러스터러
        self.clusterer = OnlineSpeakerClusterer(
            similarity_threshold=0.65,
            max_speakers=4,
        )

        # 재클러스터링 스케줄러
        self.scheduler = AdaptiveReclusterScheduler(
            base_interval=5.0,
            max_interval=60.0,
            decay_rate=0.5,
        )

        # diart blocks
        self.segmentation = SpeakerSegmentation.from_pretrained(
            "pyannote/segmentation-3.0", use_hf_token=HF_TOKEN
        )
        self.embedding = OverlapAwareSpeakerEmbedding.from_pretrained(
            "pyannote/embedding", use_hf_token=HF_TOKEN
        )

    async def process_audio_chunk(self, audio_chunk, embeddings, waveform):
        """청크 단위 처리"""
        embeddings_np = embeddings[0].detach().cpu().numpy()

        for speaker_idx, emb in enumerate(embeddings_np):
            if np.isnan(emb).any():
                continue

            # 1. 상담사 식별
            staff_name, staff_score = self.staff_identifier.identify(emb)

            if staff_name:
                speaker_label = f"staff:{staff_name}"
                trigger_recommendation = False
            else:
                customer_id, sim, is_new = self.clusterer.assign(emb)
                speaker_label = customer_id
                trigger_recommendation = True

                if is_new:
                    await self.notify_new_customer(customer_id)

            # 2. STT 호출
            segment_audio = extract_speaker_segment(waveform, speaker_idx)
            transcription = await self.stt.transcribe_chunk(segment_audio)

            # 3. DB 저장
            utterance_id = await save_utterance(
                self.session_id, speaker_label, transcription, emb
            )

            # 4. UI 푸시
            await self.push_to_ui({
                "speaker": speaker_label,
                "text": transcription.text,
                "timestamp": transcription.start_time,
            })

            # 5. 추천 트리거 (조건부)
            if trigger_recommendation:
                await self.maybe_trigger_recommendation(
                    customer_id, transcription
                )

        # 6. 재클러스터링 체크
        if self.scheduler.should_recluster():
            diff = self.clusterer.recluster()
            if diff.get("changed"):
                await self.notify_label_change(diff)

    async def on_session_end(self):
        """상담 종료 → 최종 재정렬 → 상담 노트 생성"""
        utterances = await load_utterances(self.session_id)
        reclusterer = FinalReclusterer()
        final = reclusterer.recluster(utterances, staff_label="staff:...")
        await update_final_labels(final)

        # LLM 상담 노트 생성
        note = await self.generate_consultation_note()
        await save_note(self.session_id, note)
        return note
```

---

## 10. LLM 추천 트리거 (간단 버전)

```python
# llm/recommender.py
from anthropic import AsyncAnthropic
import json

class ProcedureRecommender:
    PROCEDURES = [
        "보톡스", "필러", "울쎄라", "써마지", "슈링크",
        "레이저토닝", "IPL", "프락셀", "리쥬란", "물광주사",
        # ... 시술 사전
    ]

    KEYWORDS_TO_TRIGGER = [
        "처짐", "주름", "기미", "잡티", "여드름", "흉터", "모공",
        "탄력", "리프팅", "미백", "보톡스", "필러",
        # ... 등
    ]

    def __init__(self, client: AsyncAnthropic):
        self.client = client
        self.last_call_time = {}  # 화자별 마지막 호출 시간

    def should_trigger(self, customer_id: str, text: str) -> bool:
        # 키워드 감지
        if any(kw in text for kw in self.KEYWORDS_TO_TRIGGER):
            return self._check_cooldown(customer_id)
        return False

    def _check_cooldown(self, customer_id: str, cooldown: float = 10.0) -> bool:
        import time
        now = time.time()
        last = self.last_call_time.get(customer_id, 0)
        if now - last < cooldown:
            return False
        self.last_call_time[customer_id] = now
        return True

    async def recommend(self, customer_id: str, recent_utterances: list[str]) -> dict:
        prompt = f"""다음은 피부과 상담 중 고객의 최근 발화입니다.
이 고객에게 추천할 시술을 JSON으로 제시하세요.

발화:
{chr(10).join(recent_utterances)}

가능한 시술: {", ".join(self.PROCEDURES)}

응답 형식:
{{
  "concerns": ["주요 고민 1", "주요 고민 2"],
  "recommended_procedures": [
    {{"name": "시술명", "reason": "이유", "confidence": 0.0~1.0}}
  ]
}}
"""

        response = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text
        return json.loads(text)
```

---

## 11. 단계별 적용 로드맵

### Phase 1: 기반 구축 (1주차)
- [ ] HuggingFace 토큰 발급 + pyannote 모델 동의
- [ ] PostgreSQL + pgvector 세팅
- [ ] DB 스키마 생성
- [ ] STT 추상 인터페이스 정의 + 기존 STT 래핑
- [ ] 직원 등록 스크립트 작성 및 1명 등록 테스트

### Phase 2: 화자 분리 코어 (2주차)
- [ ] `StaffIdentifier` 구현 + 단위 테스트
- [ ] `OnlineSpeakerClusterer` 구현 + 단위 테스트
- [ ] `AdaptiveReclusterScheduler` 구현
- [ ] diart blocks를 사용한 임베딩 추출 파이프라인 동작 확인
- [ ] **오프라인 검증**: 사전 녹음 파일로 정확도 측정 (DER)

### Phase 3: 실시간 통합 (3주차)
- [ ] FastAPI WebSocket 엔드포인트 (오디오 수신)
- [ ] 브라우저 MediaRecorder 클라이언트
- [ ] 전체 파이프라인 통합 (`ConsultationPipeline`)
- [ ] DB 발화 저장
- [ ] 실시간 발화 표시 UI

### Phase 4: 추천 시스템 (4주차)
- [ ] LLM 추천 모듈 (`ProcedureRecommender`)
- [ ] 키워드 사전 + 트리거 로직
- [ ] 추천 결과 UI 팝업
- [ ] 쿨다운 / 빈도 조절

### Phase 5: 최종 재정렬 + 상담 노트 (5주차)
- [ ] `FinalReclusterer` (HDBSCAN) 구현
- [ ] 상담 종료 트리거 + 재정렬 실행
- [ ] LLM 최종 상담 노트 생성 (화자별 시술 정리표)
- [ ] 상담사 검토/수정 UI

### Phase 6: 최적화 + 운영 (6주차+)
- [ ] 임계값(threshold) 튜닝 (실제 데이터로)
- [ ] 라벨 변경 UI 처리 (사용자 혼란 최소화)
- [ ] 개인정보 마스킹 (전화번호, 이름)
- [ ] 모니터링 (Prometheus + Grafana)
- [ ] 백업/복구 정책

---

## 12. 검증 지표 (KPI)

| 지표 | 목표 | 측정 방법 |
|---|---|---|
| 화자 분리 정확도 (DER) | < 15% | 사전 라벨링된 테스트 셋 |
| 상담사 식별 정확도 | > 95% | 정답 비율 |
| 실시간 지연 (Latency) | < 2초 | 마이크 입력 → UI 표시 |
| STT 정확도 (WER) | < 15% (한국어) | 사전 라벨링 |
| 추천 적중률 | > 70% | 상담사 평가 |
| LLM 비용 / 상담 1건 | < 1,500원 | API 사용량 모니터링 |

---

## 13. 주의사항 / 리스크

### 기술적 리스크

- **단일 마이크 한계**: 화자 분리 정확도가 다채널 대비 떨어짐 (~80%).
  → 향후 다채널 마이크 도입 옵션 검토 권장.

- **초반 1~2분 라벨 불안정**: 클러스터링이 안정화되기 전까지 라벨이 바뀔 수 있음.
  → UI에 "분석 중..." 표시로 사용자 기대치 조정.

- **목소리가 비슷한 고객**: 같은 연령대/성별이면 구분 어려움.
  → 사후 재정렬로 보정.

### 법적/운영 리스크

- **의료법/개인정보보호법**: 상담 녹음에 환자 동의 필수.
- **데이터 보관**: 음성 파일 보관 정책 명문화 (예: 30일 후 자동 삭제).
- **LLM API 데이터 처리 위치**: Anthropic/OpenAI가 한국 서버 미지원이면 → 로컬 LLM 또는 한국 클라우드 검토.
- **민감 정보 마스킹**: 전화번호, 주민번호 자동 마스킹 필요.

---

## 14. 다음 단계 (논의 필요)

- [ ] STT 엔진 인터페이스 검토 → 기존 STT 어떻게 래핑할지 구체 설계
- [ ] 마이크 환경 최종 결정 (단일 vs 다채널)
- [ ] LLM 호스팅 결정 (Claude API vs 로컬 LLM)
- [ ] UI/UX 와이어프레임 (팝업 vs 사이드바)
- [ ] 운영 인프라 (자체 서버 vs 클라우드)

---

*문서 버전: v1.0 | 작성일: 2026-05-14 | 원본: `~/Downloads/consultation_system_plan.md`*
