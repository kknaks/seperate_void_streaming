"""SpeakerEngine orchestrator — stream / finalize / persist / set_alias / merge_speakers (E-06, spec-01)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator
from uuid import UUID

import numpy as np

from speaker_engine._config import load_engine_config
from speaker_engine.audio.format import validate_pcm
from speaker_engine.audio.window import WaveformBuffer
from speaker_engine.diart_adapter import DiartAdapter, RawSpeakerEvent
from speaker_engine.exceptions import StorageError
from speaker_engine.speaker.final import FinalReclusterer
from speaker_engine.speaker.identifier import Identifier
from speaker_engine.speaker.online import OnlineSpeakerClusterer
from speaker_engine.speaker.scheduler import AdaptiveReclusterScheduler
from speaker_engine.storage.url import from_url
from speaker_engine.types import (
    LabelChange,
    PersistMapping,
    Speaker,
    SpeakerCandidate,
    SpeakerSegment,
)

logger = logging.getLogger(__name__)


@dataclass
class _UtteranceRecord:
    """utterance buffer 내부 entry — UtteranceEntry Protocol 만족 (spec-04 §OQ-04-6)."""

    utterance_id: str
    label: str
    embedding: np.ndarray
    is_locked: bool   # registered:* / stored:* → True
    t_start: float    # session-relative (seconds)
    t_end: float      # session-relative (seconds)


class SpeakerEngine:
    """SpeakerEngine orchestrator — DiartAdapter / Identifier / OnlineSpeakerClusterer
    / AdaptiveReclusterScheduler / FinalReclusterer + SpeakerStore 통합 (spec-01 §2-1)."""

    def __init__(
        self,
        storage_url: str | None = None,
        hf_token: str | None = None,
        registered_speakers: dict[str, np.ndarray] | None = None,
        registered_threshold: float = 0.70,
        stored_threshold: float = 0.75,
        max_speakers: int = 20,
        finalize_drain_timeout: float = 5.0,
        audio_queue_maxsize: int = 100,
        segmentation_model: str = "pyannote/segmentation-3.0",
        embedding_model: str = "pyannote/embedding",
        device: str | None = None,
        phrase_short_threshold_s: float = 1.5,
        phrase_auto_threshold: float = 0.42,
    ) -> None:
        # env 해석 (인자 우선 → env fallback) — EnvironmentError 가능 (F-04)
        config = load_engine_config(storage_url, hf_token)

        self._embedding_model = embedding_model
        self._finalize_drain_timeout = finalize_drain_timeout
        self._audio_queue_maxsize = audio_queue_maxsize
        self._registered_speakers = registered_speakers

        # Storage backend (spec-02, adr-03)
        self._store = from_url(config.storage_url)

        # OnlineSpeakerClusterer — DiartAdapter 에 DI (spec-04 §2-2)
        self._clusterer = OnlineSpeakerClusterer(max_speakers=max_speakers)

        # DiartAdapter — ModelLoadError / RuntimeError(CUDA) 가능 (spec-03)
        self._diart = DiartAdapter(
            hf_token=config.hf_token,
            clusterer=self._clusterer,
            segmentation_model=segmentation_model,
            embedding_model=embedding_model,
            device=device,
        )

        # 3-tier Identifier (Storage 닿는 호출 async — spec-04 §4.6)
        self._identifier = Identifier(
            store=self._store,
            model_id=embedding_model,
            registered_speakers=registered_speakers,
            registered_threshold=registered_threshold,
            stored_threshold=stored_threshold,
        )

        # Adaptive scheduler + FinalReclusterer (spec-04 §4.4, §4.5)
        self._scheduler = AdaptiveReclusterScheduler()
        self._finalizer = FinalReclusterer()

        # Session state
        self._utterances: list[_UtteranceRecord] = []
        self._utterance_counter: int = 0
        self._stream_active: bool = False
        self._finalized: bool = False
        self._candidates: list[SpeakerCandidate] = []
        self._session_start: float = 0.0
        # "auto:X" → "stored:name" 캐시 — 동일 letter 반복 저장 match 회피
        self._stored_match_map: dict[str, str] = {}
        # WaveformBuffer 참조 — finalize() 가 flush() 호출 (stream() 이후에도 유지)
        self._buffer: WaveformBuffer | None = None
        # identify_phrase 전용 state (PLAN-006-T-002, spec-04 §9)
        self._phrase_short_threshold_s: float = phrase_short_threshold_s
        self._phrase_auto_threshold: float = phrase_auto_threshold
        self._last_phrase_label: str | None = None
        # phrase 경로에서 발급된 auto centroids — (L2-normalized embedding, label)
        self._phrase_centroids: list[tuple[np.ndarray, str]] = []

    # ─────────────────────────────────────────────────────────────────────────
    # async context manager (spec-01 §2-1)

    async def __aenter__(self) -> "SpeakerEngine":
        self._session_start = time.monotonic()
        # Storage schema DDL (spec-02 §6)
        await self._store.init_schema(
            embedding_dim=self._diart.embedding_dim,
            model_id=self._embedding_model,
        )
        # registered_speakers upsert — spec-01 §4-2
        if self._registered_speakers:
            for name, emb in self._registered_speakers.items():
                norm_emb = Identifier.normalize(emb)
                await self._store.register(name, norm_emb, self._embedding_model)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        if not self._finalized:
            try:
                await self.finalize()
            except Exception:
                logger.exception("__aexit__ 중 finalize() 실패 — 무시")

    # ─────────────────────────────────────────────────────────────────────────
    # stream (spec-01 §2-1, spec-04 §4.1, adr-05 R1~R5)

    async def stream(
        self,
        source: AsyncIterator[bytes],
    ) -> AsyncIterator[SpeakerSegment | LabelChange]:
        """PCM 16kHz mono 16-bit bytes 스트림 → SpeakerSegment | LabelChange yield.

        2회 진입 시 RuntimeError (R2). 단일 출력 순서 보장 (R5).
        """
        if self._stream_active:
            raise RuntimeError(
                "stream() 는 동일 인스턴스에서 2회 진입 불가 (R2, adr-05, spec-01 §5)"
            )
        self._stream_active = True

        # buffer 인스턴스를 보존 — finalize() 가 flush() 호출
        self._buffer = WaveformBuffer(
            adapter=self._diart,
            queue_maxsize=self._audio_queue_maxsize,
        )
        try:
            async for chunk in source:
                validate_pcm(chunk, sample_rate=16000, channels=1)
                await self._buffer.feed(chunk)          # backpressure R1 흡수
                raw_events = self._buffer.drain_queue() # 생성된 window 이벤트 소비

                for raw_event in raw_events:
                    # ── L2 정규화 (spec-04 §4.2 — identifier 책임) ─────────
                    try:
                        norm_emb = Identifier.normalize(raw_event.embedding)
                    except ValueError:
                        logger.warning(
                            "embedding 정규화 실패 (NaN/zero) — chunk skip: id=%d",
                            raw_event.local_speaker_id,
                        )
                        continue

                    auto_letter = OnlineSpeakerClusterer.idx_to_letter(
                        raw_event.local_speaker_id
                    )

                    # ── stored_match_map 캐시 확인 ──────────────────────────
                    if auto_letter in self._stored_match_map:
                        label = self._stored_match_map[auto_letter]
                        is_locked = True
                        stored_change: LabelChange | None = None
                    else:
                        # ── 3-tier 매칭 (spec-01 §4-1 step 4) ──────────────
                        label, _spk = await self._with_storage_retry(
                            self._identifier.match, norm_emb
                        )
                        stored_change = None

                        if label.startswith("stored:"):
                            # 신규 stored 매칭 → prior auto:X 발화 소급 변경 (step 7)
                            self._stored_match_map[auto_letter] = label
                            is_locked = True
                            prior = [
                                u for u in self._utterances
                                if u.label == auto_letter and not u.is_locked
                            ]
                            if prior:
                                for u in prior:
                                    u.label = label
                                    u.is_locked = True
                                stored_change = LabelChange(
                                    old_label=auto_letter,
                                    new_label=label,
                                    affected_utterance_ids=[u.utterance_id for u in prior],
                                    reason="stored_match",
                                )
                        elif label.startswith("registered:"):
                            is_locked = True
                        else:
                            # Tier 3 — auto fallback
                            label = auto_letter
                            is_locked = False

                    # ── utterance buffer append (spec-04 §2-2 SOT) ──────────
                    utt_id = self._gen_utterance_id()
                    utt = _UtteranceRecord(
                        utterance_id=utt_id,
                        label=label,
                        embedding=norm_emb,
                        is_locked=is_locked,
                        t_start=raw_event.t_start,
                        t_end=raw_event.t_end,
                    )
                    self._utterances.append(utt)

                    # ── SpeakerSegment yield (R5 단일 출력 순서) ───────────
                    yield SpeakerSegment(
                        utterance_id=utt_id,
                        label=label,
                        confidence=raw_event.confidence,
                        embedding=norm_emb,
                        audio=raw_event.audio,
                        t_start=utt.t_start,
                        t_end=utt.t_end,
                    )

                    # ── stored_match LabelChange (step 7) ───────────────────
                    if stored_change is not None:
                        yield stored_change

                    # ── Adaptive scheduler (R3 inline, adr-05) ──────────────
                    self._scheduler.notify_utterance()
                    if self._scheduler.should_trigger():
                        centers = self._clusterer.centers
                        if centers is not None and len(self._clusterer.active_centers) > 0:
                            active_idxs = sorted(self._clusterer.active_centers)
                            c_labels = [
                                OnlineSpeakerClusterer.idx_to_letter(i) for i in active_idxs
                            ]
                            a_centers = centers[list(active_idxs)]
                            changes = self._scheduler.recluster(
                                utterances=self._utterances,
                                active_centers=a_centers,
                                center_labels=c_labels,
                                delta_new=self._clusterer.delta_new,
                            )
                        else:
                            changes = self._scheduler.recluster(
                                utterances=[],
                                active_centers=np.empty((0, 1)),
                                center_labels=[],
                            )

                        if changes:
                            utt_id_to_new: dict[str, str] = {}
                            for ch in changes:
                                for uid in ch.affected_utterance_ids:
                                    utt_id_to_new[uid] = ch.new_label
                            for u in self._utterances:
                                if u.utterance_id in utt_id_to_new:
                                    u.label = utt_id_to_new[u.utterance_id]
                            for ch in changes:
                                yield ch

        finally:
            self._stream_active = False
            # self._buffer 는 보존 — finalize() 가 flush() 에 사용

    # ─────────────────────────────────────────────────────────────────────────
    # finalize (spec-01 §2-1, §4-3, adr-05 R4)

    async def finalize(
        self,
        timeout: float | None = None,
    ) -> list[SpeakerCandidate]:
        """in-flight 처리 drain → HDBSCAN FinalReclusterer → SpeakerCandidate 목록.

        이미 finalize 됐으면 기존 결과 반환.
        """
        if self._finalized:
            return list(self._candidates)

        drain_timeout = timeout if timeout is not None else self._finalize_drain_timeout

        # ── 버퍼 잔량 flush (R4 drain timeout) ────────────────────────────
        if self._buffer is not None:
            try:
                remaining = await asyncio.wait_for(
                    self._buffer.flush(),
                    timeout=drain_timeout,
                )
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"finalize() drain 시간 초과 ({drain_timeout}s) — R4, spec-01 §5"
                )
            self._buffer = None

            for raw_event in remaining:
                await self._ingest_raw_event(raw_event)

        # ── FinalReclusterer 호출 (spec-04 §4.5, adr-08) ──────────────────
        centers = self._clusterer.centers
        if centers is not None and len(self._clusterer.active_centers) > 0:
            active_idxs = sorted(self._clusterer.active_centers)
            center_labels = [
                OnlineSpeakerClusterer.idx_to_letter(i) for i in active_idxs
            ]
            active_centers: np.ndarray = centers[list(active_idxs)]
        else:
            center_labels = []
            active_centers = np.empty((0, 1))

        # Bug C fix: adaptive min_cluster_size (T-023f pattern) prevents M > max_letters RuntimeError
        _N_auto = sum(1 for u in self._utterances if not u.is_locked)
        _adaptive_mcs = max(2, _N_auto // 20)  # max_letters=20
        _finalizer = (
            FinalReclusterer(min_cluster_size=_adaptive_mcs)
            if _adaptive_mcs > 2
            else self._finalizer
        )
        try:
            candidates, label_changes = _finalizer.finalize(
                utterances=self._utterances,
                online_centers=active_centers,
                center_labels=center_labels,
            )
        except (RuntimeError, ValueError) as _exc:
            # ValueError: 너무 짧은 wav (N=0) 에서 HDBSCAN _hdbscan_linkage 가
            # "Invalid shape in axis 0: 0" 던짐. T-014 admin smoke (6s wav) 에서 재현.
            logger.warning(
                "FinalReclusterer %s — online label fallback (no recluster): %s",
                type(_exc).__name__,
                _exc,
            )
            candidates = []
            label_changes = []

        # ── utterance buffer 라벨 갱신 (option B: 내부만, 사용처 yield X) ─
        utt_id_to_new: dict[str, str] = {}
        for change in label_changes:
            for uid in change.affected_utterance_ids:
                utt_id_to_new[uid] = change.new_label
        for utt in self._utterances:
            if utt.utterance_id in utt_id_to_new:
                utt.label = utt_id_to_new[utt.utterance_id]

        self._candidates = candidates
        self._finalized = True
        return candidates

    # ─────────────────────────────────────────────────────────────────────────
    # persist (spec-01 §2-1, §4-4, adr-04)

    async def persist(
        self,
        mappings: list[PersistMapping],
    ) -> list[Speaker]:
        """finalize() 이후 auto:* → SpeakerStore 영속화 + Speaker 목록 반환."""
        if not self._finalized:
            raise RuntimeError(
                "persist() 는 finalize() 호출 후에만 유효합니다 (spec-01 §5)"
            )

        candidate_map = {c.auto_id: c for c in self._candidates}

        speakers: list[Speaker] = []
        for mapping in mappings:
            if mapping.auto_id not in candidate_map:
                raise ValueError(
                    f"auto_id {mapping.auto_id!r} 는 finalize() 결과에 없습니다 (spec-01 §5)"
                )
            candidate = candidate_map[mapping.auto_id]
            speaker = await self._with_storage_retry(
                self._store.save,
                mapping.name,
                candidate.representative_embedding,
                self._embedding_model,
            )
            speakers.append(speaker)

        return speakers

    # ─────────────────────────────────────────────────────────────────────────
    # 위임 메서드 (SpeakerStore)

    async def set_alias(self, speaker_id: UUID, name: str) -> Speaker:
        """SpeakerStore.set_alias 위임."""
        return await self._store.set_alias(speaker_id, name)

    async def merge_speakers(self, source_id: UUID, target_id: UUID) -> Speaker:
        """SpeakerStore.merge 위임."""
        return await self._store.merge(source_id, target_id)

    async def delete_speaker(self, speaker_id: UUID) -> None:
        """SpeakerStore.delete 위임."""
        await self._store.delete(speaker_id)

    # ─────────────────────────────────────────────────────────────────────────
    # identify_phrase (PLAN-006-T-002, spec-04 §9)

    async def identify_phrase(self, pcm_slice: bytes) -> str:
        """Phrase PCM slice → 화자 라벨 (spec-04 §9-1, adr-10 §Decision).

        - pcm_slice: 16kHz mono PCM bytes (PCM16, 동일 format as engine.stream input)
        - Returns: "registered:<name>" / "stored:<name>" / "auto:A" / "auto:B" ...
        - 짧은 phrase (< phrase_short_threshold_s) + 직전 라벨 있음 → 직전 라벨 반환 (Option A)
        - engine.stream() / finalize() 와 Identifier / _clusterer state 공유.
        """
        # ── Option A: 짧은 phrase 단축 경로 ─────────────────────────────────
        n_samples = len(pcm_slice) // 2  # 16-bit PCM: 2 bytes per sample
        duration_s = n_samples / 16000.0
        if duration_s < self._phrase_short_threshold_s and self._last_phrase_label is not None:
            return self._last_phrase_label

        # ── embedding 추출 (DiartAdapter, clusterer state 변경 없음) ─────────
        try:
            raw_emb = await self._diart.embed_pcm(pcm_slice)
            norm_emb = Identifier.normalize(raw_emb)
        except ValueError as exc:
            logger.warning("identify_phrase: embedding 추출 실패 — fallback: %s", exc)
            if self._last_phrase_label is not None:
                return self._last_phrase_label
            label = self._alloc_auto_letter()
            self._last_phrase_label = label
            return label

        # ── 3-tier 매칭 (Identifier, spec-04 §4.2) ───────────────────────────
        label, _ = await self._with_storage_retry(self._identifier.match, norm_emb)

        if not label:
            # Tier 3: centroid 매칭 → auto 라벨 결정
            label = self._resolve_auto_label(norm_emb)

        self._last_phrase_label = label
        return label

    def _resolve_auto_label(self, norm_emb: np.ndarray) -> str:
        """auto label 결정: 기존 centroid 최근접 매칭 → 없으면 신규 letter 발급.

        stream 경로 centroids (OnlineSpeakerClusterer) 와 phrase 경로 centroids
        (_phrase_centroids) 를 모두 탐색 (단방향 공유: stream→phrase).
        _phrase_centroids 매칭 성공 시 running average (0.7 old + 0.3 new) 로 갱신.
        """
        best_label: str | None = None
        best_sim: float = -2.0
        best_phrase_idx: int = -1  # _phrase_centroids 매칭 시 인덱스, 없으면 -1

        # 1. online clusterer centroids (stream 경로 공유)
        centers = self._clusterer.centers
        if centers is not None:
            for idx in sorted(self._clusterer.active_centers):
                c = centers[idx]
                c_norm = float(np.linalg.norm(c))
                if c_norm < 1e-9:
                    continue
                sim = float(np.dot(c / c_norm, norm_emb))
                if sim > best_sim:
                    best_sim = sim
                    best_label = OnlineSpeakerClusterer.idx_to_letter(idx)
                    best_phrase_idx = -1

        # 2. phrase 경로 자체 centroids
        for i, (centroid, lbl) in enumerate(self._phrase_centroids):
            sim = float(np.dot(centroid, norm_emb))
            if sim > best_sim:
                best_sim = sim
                best_label = lbl
                best_phrase_idx = i

        if best_sim >= self._phrase_auto_threshold and best_label is not None:
            # _phrase_centroids 매칭이면 running average 갱신 (stream clusterer 는 자체 update)
            if best_phrase_idx >= 0:
                old, lbl = self._phrase_centroids[best_phrase_idx]
                updated = 0.9 * old + 0.1 * norm_emb
                updated = updated / (np.linalg.norm(updated) + 1e-9)
                self._phrase_centroids[best_phrase_idx] = (updated, lbl)
            return best_label

        # 3. 신규 letter 발급 + phrase centroid 등록
        new_letter = self._alloc_auto_letter()
        self._phrase_centroids.append((norm_emb.copy(), new_letter))
        return new_letter

    def _alloc_auto_letter(self) -> str:
        """미사용 auto letter 중 가장 작은 idx 를 발급 (stream + phrase 통합)."""
        _LETTERS = "ABCDEFGHIJKLMNOPQRST"
        used_idxs: set[int] = set()
        used_idxs.update(self._clusterer.active_centers)
        for _, lbl in self._phrase_centroids:
            try:
                used_idxs.add(OnlineSpeakerClusterer.letter_to_idx(lbl))
            except ValueError:
                pass
        for i in range(20):
            if i not in used_idxs:
                return f"auto:{_LETTERS[i]}"
        raise RuntimeError(
            "identify_phrase: auto speaker 한도 (20) 초과 — 새 letter 발급 불가"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 내부 헬퍼

    def _gen_utterance_id(self) -> str:
        """단조 증가 utterance ID 생성 (spec-01 §3 — "utt-NNN")."""
        self._utterance_counter += 1
        return f"utt-{self._utterance_counter:03d}"

    async def _with_storage_retry(self, coro_fn, *args, **kwargs):
        """StorageError 3회 exponential backoff (1s→2s→4s, spec-01 §5)."""
        delays = (1.0, 2.0, 4.0)
        last_exc: StorageError | None = None
        for i, delay in enumerate(delays):
            try:
                return await coro_fn(*args, **kwargs)
            except StorageError as exc:
                last_exc = exc
                if i < len(delays) - 1:
                    logger.warning(
                        "StorageError 임시 단절 (attempt %d/%d): %s — %.1fs 후 재시도",
                        i + 1,
                        len(delays),
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    async def _ingest_raw_event(self, raw_event: RawSpeakerEvent) -> None:
        """finalize flush 단계 raw event → utterance buffer append only (yield X)."""
        try:
            norm_emb = Identifier.normalize(raw_event.embedding)
        except ValueError:
            logger.warning("finalize flush — embedding 정규화 실패, skip")
            return

        auto_letter = OnlineSpeakerClusterer.idx_to_letter(raw_event.local_speaker_id)

        if auto_letter in self._stored_match_map:
            label = self._stored_match_map[auto_letter]
            is_locked = True
        else:
            label, _ = await self._with_storage_retry(self._identifier.match, norm_emb)
            if label.startswith("stored:"):
                self._stored_match_map[auto_letter] = label
                is_locked = True
            elif label.startswith("registered:"):
                is_locked = True
            else:
                label = auto_letter
                is_locked = False

        utt = _UtteranceRecord(
            utterance_id=self._gen_utterance_id(),
            label=label,
            embedding=norm_emb,
            is_locked=is_locked,
            t_start=raw_event.t_start,
            t_end=raw_event.t_end,
        )
        self._utterances.append(utt)


__all__ = ["SpeakerEngine"]
