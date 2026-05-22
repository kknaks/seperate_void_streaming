---
id: reference-08
type: reference
title: diart streaming 구조 — 코드 분석
status: draft
created: 2026-05-14
updated: 2026-05-14
source_url: https://github.com/juanmc2005/diart/tree/main/src/diart
fetched_at: 2026-05-14
sources:
  - "[[reference-01-pyannote-segmentation-3]]"
  - "[[reference-02-pyannote-embedding]]"
  - "[[reference-04-pyannote-audio-inference]]"
  - "[[reference-05-pyannote-pipeline-flow]]"
  - "[[reference-06-powerset-decoder]]"
  - "[[reference-07-pyannote-embedding-code]]"
tags: [reference, diart, streaming, rxpy, online-clustering, study-step-2, source-code]
---

# diart streaming 구조 — 코드 분석

> **출처 (clone)**: `diart/src/diart/`
> - `sources.py` (322 줄) — AudioSource 추상 + File/Mic/WebSocket/AppleDevice 구현
> - `operators.py` (304 줄) — rx 기반 sliding window/buffer 연산자
> - `blocks/segmentation.py` (48 줄), `blocks/embedding.py` (178 줄), `blocks/clustering.py` (218 줄), `blocks/diarization.py` (234 줄), `blocks/aggregation.py` (218 줄)
> - `inference.py` (559 줄) — StreamingInference (rx pipeline 조립)
> - `functional.py` (28 줄) — `overlapped_speech_penalty`, `normalize_embeddings`
> **목적**: 학습 2단계 — diart 가 어떻게 streaming pipeline 을 구성하는지 정확히 파악

## Summary

diart 는 **RxPY (ReactiveX for Python)** 의 `Subject` 와 `pipe(ops.scan(...), ops.filter(...), ops.map(...))` 으로 audio stream → sliding window → segmentation → embedding → clustering → aggregation 의 reactive pipeline 을 조립. asyncio 는 사용 안 함. 진입점은 `AudioSource.read()` 가 blocking loop 으로 chunk 를 emit. 핵심 알고리즘은 `OnlineSpeakerClustering` (centroid 증분 업데이트).

⚠️ **diart default `duration=5, step=0.5` — segmentation-3.0 (10초 학습) 와 mismatch**. segmentation-3.0 을 쓰려면 `duration=10` 명시 필수.

---

## 1. AudioSource 추상 (sources.py:18-47)

```python
class AudioSource(ABC):
    def __init__(self, uri: Text, sample_rate: int):
        self.uri = uri
        self.sample_rate = sample_rate
        self.stream = Subject()  # ← rx Subject

    @property
    def duration(self) -> Optional[float]:
        return None

    @abstractmethod
    def read(self):
        """Start reading the source and yielding samples through the stream."""
        pass

    @abstractmethod
    def close(self):
        pass
```

핵심: `self.stream = Subject()` 가 **rx Observable** 의 multi-cast source. 모든 downstream pipeline 은 이 stream 에 subscribe.

### 구현체 4종

| Class | sample_rate 정책 | block_duration 기본값 | emit 방식 |
|---|---|---|---|
| `FileAudioSource` (50-135) | 사용자 지정 (AudioLoader 가 resample) | 0.5 초 | `read()` 가 unfold 후 loop 으로 `self.stream.on_next(chunk)` |
| `MicrophoneAudioSource` (138-201) | 디바이스에서 best (16/32/44.1/48 kHz 중 첫번째 지원) | 0.5 초 | sounddevice 콜백 → queue → loop |
| `WebSocketAudioSource` (204-271) | 사용자 지정 (server side) | (블록 단위 = 메시지 단위) | message 받을 때마다 `decode_audio` → `on_next` |
| `TorchStreamAudioSource` / `AppleDeviceAudioSource` (274-323) | 사용자 지정 | 0.5 초 | torchaudio.io.StreamReader |

### FileAudioSource read() 핵심 (sources.py:88-132)

```python
def read(self):
    waveform = self.loader.load(self.file)
    # padding 처리 ...

    # Split into blocks
    chunks = rearrange(
        waveform.unfold(1, self.block_size, self.block_size),
        "channel chunk sample -> chunk channel sample",
    ).numpy()

    # Add last incomplete chunk with padding
    if num_samples % self.block_size != 0:
        last_chunk = waveform[:, chunks.shape[0] * self.block_size :].unsqueeze(0).numpy()
        diff_samples = self.block_size - last_chunk.shape[-1]
        last_chunk = np.concatenate([last_chunk, np.zeros((1, 1, diff_samples))], axis=-1)
        chunks = np.vstack([chunks, last_chunk])

    # Stream blocks
    for i, waveform in enumerate(chunks):
        if self.is_closed:
            break
        self.stream.on_next(waveform)
    self.stream.on_completed()
    self.close()
```

→ 파일을 block_size (0.5초 default) 단위로 잘라 sequential 하게 emit. 마지막 incomplete block 은 right-zero-pad.

→ shape on each emit: `(channel=1, block_size)` numpy.ndarray.

### WebSocketAudioSource — 핵심 (sources.py:240-271)

```python
def _on_message_received(self, client, server, message):
    if self.client is None or self.client["id"] != client["id"]:
        self.client = client
    self.stream.on_next(utils.decode_audio(message))

def read(self):
    self.server.run_forever()
```

→ websocket message 마다 decode → emit. `read()` 는 blocking server loop. 한 번에 한 client 만 허용.

→ **sample_rate 는 사용자가 명시한 값으로 박혀있고, 클라이언트 측이 그 sr 에 맞게 보내야 함** (line 233-235 의 FIXME 주석 참조).

## 2. Sliding window 누적 — `rearrange_audio_stream` (operators.py:44-100)

이게 **streaming 의 핵심**. block_size (0.5초) 짜리 chunk 들이 stream 에서 흘러나오는데, 이를 duration (10초) 짜리 window 로 누적하는 rx operator.

```python
def rearrange_audio_stream(
    duration: float = 5, step: float = 0.5, sample_rate: int = 16000
) -> Operator:
    chunk_samples = int(round(sample_rate * duration))   # = 160000 (10초 기준)
    step_samples = int(round(sample_rate * step))         # = 8000 (0.5초 기준)

    def accumulate(state: AudioBufferState, value: np.ndarray):
        # value: 새로 들어온 작은 chunk (block_size samples)
        if value.ndim != 2 or value.shape[0] != 1:
            raise ValueError(...)
        start_time = state.start_time

        # Add new samples to the buffer
        buffer = (
            value
            if state.buffer is None
            else np.concatenate([state.buffer, value], axis=1)
        )

        # Check for buffer overflow (step_samples 누적 시)
        if buffer.shape[1] >= step_samples:
            if buffer.shape[1] == step_samples:
                new_chunk, new_buffer = buffer, None
            else:
                new_chunk = buffer[:, :step_samples]
                new_buffer = buffer[:, step_samples:]

            # Add samples to next chunk
            if state.chunk is not None:
                new_chunk = np.concatenate([state.chunk, new_chunk], axis=1)

            # Truncate chunk to ensure a fixed duration
            if new_chunk.shape[1] > chunk_samples:
                new_chunk = new_chunk[:, -chunk_samples:]
                start_time += step

            return AudioBufferState(new_chunk, new_buffer, start_time, changed=True)

        return AudioBufferState(state.chunk, buffer, start_time, changed=False)

    return rx.pipe(
        ops.scan(accumulate, AudioBufferState.initial()),
        ops.filter(AudioBufferState.has_samples(chunk_samples)),
        ops.filter(lambda state: state.changed),
        ops.map(AudioBufferState.to_sliding_window(sample_rate)),
    )
```

알고리즘 정리:
1. **`scan` (accumulate)**: 작은 block 이 들어올 때마다 buffer 에 누적.
2. **buffer 가 `step_samples` (= 0.5초 분) 모이면**: chunk 에 append → chunk 가 `chunk_samples` (= 10초) 초과하면 **right slice (`new_chunk[:, -chunk_samples:]`)** 으로 자르고 `start_time += step` (시간 이동). `changed=True`.
3. **`filter` 2개**: chunk 가 완전히 채워졌고 (`has_samples`) + 변화 있을 때 (`changed=True`) 만 통과.
4. **`map`**: `AudioBufferState` → `SlidingWindowFeature` (sample 단위 해상도).

핵심 동작:
- **block_size (input) ≠ step_size (output)** — block 이 step 보다 작으면 step 채울 때까지 누적 후 emit.
- **첫 chunk**: 10초 audio 가 모이기 전엔 emit 없음 (조용히 buffer).
- **emit shape**: `SlidingWindowFeature(data: (samples=160000, channel=1), sliding_window: SlidingWindow(start=t, duration=1/sr, step=1/sr))`

FIXME 주석 (line 50-51):
```
this should flush buffer contents when the audio stops being emitted.
Right now this can be solved by using a block size that's a dividend of the step size.
```

→ **block_size 가 step_size 의 약수 (또는 동일) 이어야 정확히 동작** — 그렇지 않으면 마지막 자투리 audio 가 emit 안 됨. 우리 라이브러리에선 명시적 flush 필요.

## 3. SpeakerSegmentation block (blocks/segmentation.py)

```python
class SpeakerSegmentation:
    def __init__(self, model: SegmentationModel, device: Optional[torch.device] = None):
        self.model = model
        self.model.eval()
        self.device = device or torch.device("cpu")
        self.model.to(self.device)
        self.formatter = TemporalFeatureFormatter()

    def __call__(self, waveform: TemporalFeatures) -> TemporalFeatures:
        """
        waveform: TemporalFeatures, shape (samples, channels) or (batch, samples, channels)
        Returns: TemporalFeatures, shape (batch, frames, speakers)
        """
        with torch.no_grad():
            wave = rearrange(
                self.formatter.cast(waveform),
                "batch sample channel -> batch channel sample",
            )
            output = self.model(wave.to(self.device)).cpu()
        return self.formatter.restore_type(output)
```

→ 단순 forward wrapper. 10초 chunk → `(batch, num_frames, num_speakers=3)` multilabel (PowersetAdapter 가 자동으로 powerset→multilabel 변환, models.py:29-39 참조).

→ **10초 window 채우기는 외부 (rearrange_audio_stream) 책임**. SpeakerSegmentation 자체는 batch forward 만.

## 4. OverlapAwareSpeakerEmbedding block (blocks/embedding.py:123-178)

이 블록이 diart 의 **차별점**. segmentation 결과를 활용해 화자별 embedding 추출.

```python
class OverlapAwareSpeakerEmbedding:
    def __init__(
        self,
        model: EmbeddingModel,
        gamma: float = 3,
        beta: float = 10,
        norm: Union[float, torch.Tensor] = 1,
        normalize_weights: bool = False,
        device: Optional[torch.device] = None,
    ):
        self.embedding = SpeakerEmbedding(model, device)
        self.osp = OverlappedSpeechPenalty(gamma, beta, normalize_weights)
        self.normalize = EmbeddingNormalization(norm)

    def __call__(self, waveform, segmentation) -> torch.Tensor:
        return self.normalize(self.embedding(waveform, self.osp(segmentation)))
```

세 단계:

### 4-1. OverlappedSpeechPenalty (functional.py:6-13)

```python
def overlapped_speech_penalty(segmentation: torch.Tensor, gamma: float = 3, beta: float = 10):
    # segmentation: (batch, frames, speakers)
    probs = torch.softmax(beta * segmentation, dim=-1)
    weights = torch.pow(segmentation, gamma) * torch.pow(probs, gamma)
    weights[weights < 1e-8] = 1e-8
    return weights
```

→ **softmax(β·seg) ^ γ · seg^γ** 를 frame 별 화자별 가중치로. β=10 가 높을수록 softmax 가 hard 해짐 (한 화자에만 가중치 몰림). γ=3 으로 거듭제곱해 low-confidence frame 가중치 ↓.

→ paper §2.2.1 Eq. 2 ("Overlap-Aware Low-Latency Online Speaker Diarization based on End-to-End Local Segmentation", diart 의 학위논문 — blocks/embedding.py:74-78 참조).

### 4-2. SpeakerEmbedding.__call__ (blocks/embedding.py:31-68)

```python
def __call__(self, waveform, weights=None) -> torch.Tensor:
    """
    waveform: (samples, channels) or (batch, samples, channels)
    weights: (frames, speakers) or (batch, frames, speakers) — per-speaker, per-frame
    Returns
    -------
    embeddings: (batch, speakers, embedding_dim) if weights, else (batch, embedding_dim)
    """
    with torch.no_grad():
        inputs = self.waveform_formatter.cast(waveform).to(self.device)
        inputs = rearrange(inputs, "batch sample channel -> batch channel sample")
        if weights is not None:
            weights = self.weights_formatter.cast(weights).to(self.device)
            batch_size, _, num_speakers = weights.shape
            inputs = inputs.repeat(1, num_speakers, 1)
            weights = rearrange(weights, "batch frame spk -> (batch spk) frame")
            inputs = rearrange(inputs, "batch spk sample -> (batch spk) 1 sample")
            output = rearrange(
                self.model(inputs, weights),
                "(batch spk) feat -> batch spk feat",
                batch=batch_size,
                spk=num_speakers,
            )
        else:
            output = self.model(inputs)
        return output.squeeze().cpu()
```

→ 한 audio chunk 를 **num_speakers 번 복제**해 각 화자별 weight 와 함께 한 번에 batch forward. 결과는 `(batch, num_speakers, dim)` — chunk 당 3개 embedding (segmentation-3.0 기준).

### 4-3. EmbeddingNormalization (functional.py:16-27)

```python
def normalize_embeddings(embeddings: torch.Tensor, norm: float | torch.Tensor = 1) -> torch.Tensor:
    if embeddings.ndim == 2:
        embeddings = embeddings.unsqueeze(0)
    emb_norm = torch.norm(embeddings, p=2, dim=-1, keepdim=True)
    return norm * embeddings / emb_norm
```

→ **명시적 L2 정규화**. default `norm=1` 이라 unit vector. pyannote 가 정규화 안 하는 것과 대비 (reference-07 §5).

## 5. OnlineSpeakerClustering (blocks/clustering.py)

diart 의 streaming 핵심 — pyannote 의 VBxClustering 을 대체.

```python
class OnlineSpeakerClustering:
    def __init__(
        self,
        tau_active: float,    # 활성 화자 임계 (seg max)
        rho_update: float,    # centroid update 임계 (seg mean)
        delta_new: float,     # 새 centroid 생성 거리 임계
        metric: Optional[str] = "cosine",
        max_speakers: int = 20,
    ):
        self.centers: Optional[np.ndarray] = None     # (max_speakers, dim)
        self.active_centers = set()
        self.blocked_centers = set()
```

세 임계값:
| 파라미터 | default (SpeakerDiarizationConfig) | 의미 |
|---|---|---|
| `tau_active` | 0.6 | chunk 내 segmentation 의 화자 max 가 이 값 이상이면 active |
| `rho_update` | 0.3 | chunk 내 segmentation 의 화자 mean 이 이 값 이상이면 centroid update |
| `delta_new` | 1.0 | 거리 threshold (cosine). 모든 centroid 와 이 거리 초과면 새 화자 |

### identify() 알고리즘 핵심 (clustering.py:119-210)

```python
def identify(self, segmentation, embeddings) -> SpeakerMap:
    embeddings = embeddings.detach().cpu().numpy()
    active_speakers = np.where(np.max(segmentation.data, axis=0) >= self.tau_active)[0]
    long_speakers = np.where(np.mean(segmentation.data, axis=0) >= self.rho_update)[0]
    no_nan_embeddings = np.where(~np.isnan(embeddings).any(axis=1))[0]
    active_speakers = np.intersect1d(active_speakers, no_nan_embeddings)

    if self.centers is None:
        self.init_centers(embeddings.shape[1])
        assignments = [(spk, self.add_center(embeddings[spk])) for spk in active_speakers]
        return SpeakerMapBuilder.hard_map(...)

    # 1. 모든 (local, global) 거리 매트릭스
    dist_map = SpeakerMapBuilder.dist(embeddings, self.centers, self.metric)
    inactive_speakers = np.array([spk for spk in range(num_local_speakers) if spk not in active_speakers])
    dist_map = dist_map.unmap_speakers(inactive_speakers, self.inactive_centers)

    # 2. delta_new 이내 매칭만 유지
    valid_map = dist_map.unmap_threshold(self.delta_new)

    # 3. 매칭 안 된 active speakers
    missed_speakers = [s for s in active_speakers if not valid_map.is_source_speaker_mapped(s)]

    # 4. 새 centroid 생성 or free centroid 재사용
    new_center_speakers = []
    for spk in missed_speakers:
        has_space = len(new_center_speakers) < self.num_free_centers
        if has_space and spk in long_speakers:
            new_center_speakers.append(spk)
        else:
            # free centroid 중 가장 가까운 곳에 강제 매핑
            preferences = np.argsort(dist_map.mapping_matrix[spk, :])
            preferences = [g for g in preferences if g in self.active_centers]
            _, g_assigned = valid_map.valid_assignments()
            free = [g for g in preferences if g not in g_assigned]
            if free:
                valid_map = valid_map.set_source_speaker(spk, free[0])

    # 5. centroid update (rho_update 통과 화자만)
    to_update = [
        (ls, gs) for ls, gs in zip(*valid_map.valid_assignments())
        if ls not in missed_speakers and ls in long_speakers
    ]
    self.update(to_update, embeddings)

    # 6. 새 centroid 추가
    for spk in new_center_speakers:
        valid_map = valid_map.set_source_speaker(spk, self.add_center(embeddings[spk]))

    return valid_map
```

업데이트 (clustering.py:85-99):
```python
def update(self, assignments, embeddings):
    if self.centers is not None:
        for l_spk, g_spk in assignments:
            assert g_spk in self.active_centers, "Cannot update unknown centers"
            self.centers[g_spk] += embeddings[l_spk]   # ← 단순 누적 합 (평균 X)
```

⚠️ **주목**: centroid update 가 **단순 누적 합** — running mean 이 아님. 매번 새 embedding 을 그대로 더함. embedding 이 L2 정규화돼 있고 (norm=1), centroid 도 결국 cosine 비교 (normalize 후) 되니 누적 길이 무관.

### 결과: SpeakerMap

local speaker (0/1/2 of current chunk) → global speaker (0~max_speakers-1) 매핑. `__call__` (line 212-218) 가 이 map 을 segmentation 데이터에 적용해 reshape:

```python
def __call__(self, segmentation, embeddings) -> SlidingWindowFeature:
    return SlidingWindowFeature(
        self.identify(segmentation, embeddings).apply(segmentation.data),
        segmentation.sliding_window,
    )
```

## 6. SpeakerDiarization Pipeline (blocks/diarization.py)

위 building block 들을 합친 final pipeline.

### Config default (diarization.py:21-87)

```python
class SpeakerDiarizationConfig(base.PipelineConfig):
    def __init__(
        self,
        segmentation: m.SegmentationModel | None = None,
        embedding: m.EmbeddingModel | None = None,
        duration: float = 5,       # ⚠ segmentation-3.0 와 mismatch
        step: float = 0.5,
        latency: float | Literal["max", "min"] | None = None,
        tau_active: float = 0.6,
        rho_update: float = 0.3,
        delta_new: float = 1,
        gamma: float = 3,
        beta: float = 10,
        max_speakers: int = 20,
        normalize_embedding_weights: bool = False,
        device: torch.device | None = None,
        sample_rate: int = 16000,
        **kwargs,
    ):
        self.segmentation = segmentation or m.SegmentationModel.from_pyannote("pyannote/segmentation")
        self.embedding = embedding or m.EmbeddingModel.from_pyannote("pyannote/embedding")
        ...
```

⚠️ **`duration = 5`** — diart 가 만들어진 시점에 `pyannote/segmentation` v2 가 5초 학습이었기 때문. **segmentation-3.0 (10초 학습) 을 쓰려면 `duration=10` 명시 필수**. 5초 inference 로도 어느정도 동작하지만 모델 학습 도메인 벗어남.

`latency = None → step` 이라 default 는 minimum latency (0.5초).

### __call__ 핵심 (diarization.py:157-234)

```python
def __call__(self, waveforms: Sequence[SlidingWindowFeature]) -> Sequence[tuple[Annotation, SlidingWindowFeature]]:
    batch = torch.stack([torch.from_numpy(w.data) for w in waveforms])

    expected_num_samples = int(np.rint(self.config.duration * self.config.sample_rate))
    assert batch.shape[1] == expected_num_samples, ...

    # Extract segmentation and embeddings
    segmentations = self.segmentation(batch)  # (batch, frames, speakers)
    embeddings = self.embedding(batch, segmentations)  # (batch, speakers, dim)

    seg_resolution = waveforms[0].extent.duration / segmentations.shape[1]

    outputs = []
    for wav, seg, emb in zip(waveforms, segmentations, embeddings):
        sw = SlidingWindow(start=wav.extent.start, duration=seg_resolution, step=seg_resolution)
        seg = SlidingWindowFeature(seg.cpu().numpy(), sw)

        # Update clustering state and permute segmentation
        permuted_seg = self.clustering(seg, emb)   # ← OnlineSpeakerClustering

        # Update sliding buffer
        self.chunk_buffer.append(wav)
        self.pred_buffer.append(permuted_seg)

        # Aggregate buffer outputs for this time step
        agg_waveform = self.audio_aggregation(self.chunk_buffer)
        agg_prediction = self.pred_aggregation(self.pred_buffer)
        agg_prediction = self.binarize(agg_prediction)

        # Shift prediction timestamps if required
        if self.timestamp_shift != 0:
            ...

        outputs.append((agg_prediction, agg_waveform))

        # Buffer 크기 제한
        if len(self.chunk_buffer) == self.pred_aggregation.num_overlapping_windows:
            self.chunk_buffer = self.chunk_buffer[1:]
            self.pred_buffer = self.pred_buffer[1:]

    return outputs
```

핵심:
- chunk 들이 들어올 때마다 segmentation + embedding → `OnlineSpeakerClustering` 으로 local→global 매핑
- `chunk_buffer` / `pred_buffer` 가 sliding 으로 최근 N chunk (`num_overlapping_windows`) 유지 → 그 buffer 의 마지막 step 영역만 aggregate
- `pred_aggregation` = `DelayedAggregation(step, latency, strategy="hamming", cropping_mode="loose")` (diarization.py:107-112)
- `audio_aggregation` = `DelayedAggregation(step, latency, strategy="first", cropping_mode="center")` (line 113-118)

→ pyannote `Inference.aggregate` 와 동일한 **Hamming-weighted aggregation** 사용. 단 streaming 이라 buffer 가 최근 N 개로 제한됨.

`DelayedAggregation.num_overlapping_windows = int(round(latency / step))` (aggregation.py:185). 예: duration=10, step=0.5, latency=2.0 → num_overlapping_windows = 4.

## 7. rx pipeline 조립 (inference.py:99-147)

```python
self.stream = self.source.stream

# Rearrange stream to form sliding windows
self.stream = self.stream.pipe(
    dops.rearrange_audio_stream(chunk_duration, step_duration, source.sample_rate),
)

# Dynamic resampling if needed
if sample_rate != self.source.sample_rate:
    self.stream = self.stream.pipe(
        ops.map(blocks.Resample(self.source.sample_rate, sample_rate, ...))
    )

# Form batches
self.stream = self.stream.pipe(
    ops.buffer_with_count(count=self.batch_size),
)

# Pipeline (segmentation + embedding + clustering + aggregation)
self.stream = self.stream.pipe(
    ops.do_action(on_next=lambda _: self._chrono.start()),
    ops.map(self.pipeline),    # ← SpeakerDiarization.__call__
    ops.do_action(on_next=lambda _: self._chrono.stop()),
)

# Flatten and accumulate
self.stream = self.stream.pipe(
    ops.flat_map(lambda results: rx.from_iterable(results)),
    ops.do(self.accumulator),
)
```

→ 표준 rx pipeline. `subscribe(on_error, on_completed)` 호출 후 `self.source.read()` 가 blocking 으로 chunk emit (inference.py:225-231).

→ **asyncio 와의 관계**: 없음. `WebsocketServer.run_forever()` 또는 sounddevice 콜백, 또는 file iter loop 가 그 자체로 blocking — async runtime 필요 없음.

## 8. AggregationStrategy 옵션 (blocks/aggregation.py:28-40)

```python
@staticmethod
def build(name: Literal["mean", "hamming", "first"], cropping_mode):
    if name == "mean":
        return AverageStrategy(cropping_mode)
    elif name == "hamming":
        return HammingWeightedAverageStrategy(cropping_mode)
    else:
        return FirstOnlyStrategy(cropping_mode)
```

| strategy | 동작 | 용도 |
|---|---|---|
| `mean` | 단순 평균 | 단순한 경우 |
| `hamming` | hamming-weighted 평균 (default for predictions) | segmentation 결과 합칠 때 |
| `first` | 첫 buffer 의 focus 영역만 사용 (default for audio) | 원본 waveform 재구성 (값 중복 회피) |

---

## 우리 라이브러리 영향 (실제 사실)

| 1단계 가정 | 코드 확정 | 행동 |
|---|---|---|
| sliding window 누적 어떻게 | **`scan` operator + AudioBufferState** — block 단위 누적 → step 단위 emit | 우리도 `ChunkBuffer` 클래스로 동일 패턴 (rx 없이 manual 구현 가능) |
| 10초 window 어떻게 채우나 | duration=10 명시 + rearrange_audio_stream | 우리도 동일 |
| OverlapAwareSpeakerEmbedding | **softmax(β·seg)^γ · seg^γ** weight (Equation 2) + L2 정규화 | 우리 embedding 추출은 이 가중치 채택 권장 (overlap 자연 다운웨이트) |
| 온라인 clustering | **OnlineSpeakerClustering** — centroid 단순 누적 합, τ_active/ρ_update/δ_new 임계 | streaming 의 핵심. 알고리즘 그대로 차용 가능 |
| rx vs asyncio | **rx (RxPY)** 단독 — asyncio 와 별개 | 우리는 asyncio 친화 wrapper 필요 (Linky/Charty 가 asyncio) |
| AudioSource 인터페이스 | `AudioSource.stream = Subject()` + `read()` (blocking) | 우리는 `AsyncAudioSource` 추상으로 (asyncio.Queue 기반) |
| **default duration=5** | ⚠️ segmentation-3.0 와 mismatch — **반드시 duration=10 명시** | 우리 default 는 10초 (segmentation-3.0 학습값 따라감) |
| block_size 와 step_size 관계 | **block_size 가 step_size 의 약수 (또는 동일)** 이어야 자투리 안 잃음 | 우리도 동일 규칙 강제 또는 명시적 flush |
| latency vs step | latency >= step 항상 (line 93-94), `latency=None` 이면 latency=step | 우리도 동일 |

### 우리 라이브러리에서 채택할 핵심 아이디어 3가지

1. **`OnlineSpeakerClustering` 알고리즘** (centroid 누적 + τ/ρ/δ 임계) — diart 논문 reference 그대로 차용. SpeakerStore (3-tier) 와 합치면 registered/stored 우선 매칭 + auto cluster fallback.
2. **`OverlapAwareSpeakerEmbedding`** (softmax · seg^γ weight) — embedding 추출 시 segmentation 결과를 직접 frame mask 로 활용해 overlap 영역 자연 다운웨이트.
3. **`DelayedAggregation`** (Hamming-weighted, sliding buffer N개) — streaming 에서 latency 와 정확도 trade-off 결정 정점.

### diart 가 가진 한계 (우리가 개선할 점)

1. **rx 의존성** — RxPY 는 maintainance mode. asyncio 우선 환경에서 어색. 우리는 asyncio.Queue 로 stream 추상화.
2. **3-tier 화자 라벨링 부재** — diart 는 모두 auto cluster. 우리는 registered (DB 등록) / stored (히스토리) / auto (이번 세션) 3-tier.
3. **default duration=5** — segmentation-3.0 mismatch. 우리는 default 10초.
4. **WebSocket source 한계** — 한 client 만 허용, sample_rate 검증 없음 (FIXME 주석). 우리는 multi-session + sample_rate validation.

---

## 미확인 사항 (남은 것)

- `SpeakerMap` / `SpeakerMapBuilder` 정확한 구현 — `diart/mapping.py` 미정독.
- `TemporalFeatures` / `TemporalFeatureFormatter` — `diart/features.py` 미정독 (numpy/torch/SlidingWindowFeature 통합 추상).
- `Resample` block — block 정확한 구현 미확인 (torchaudio.transforms.Resample wrapper 추정).
- `models.py` 의 `SegmentationModel.from_pyannote` / `EmbeddingModel.from_pretrained` 의 lazy loading 디테일 (대략 파악, 자세히는 미정독).
- benchmark 모드의 batch 가속 (segmentation/embedding 미리 batch 처리) — inference.py:259-265 의 다른 코드 경로.
- GPU/CPU 실측 latency — 코드에서 확인 불가, 실측 필요.
