---
id: reference-04
type: reference
title: pyannote.audio.Inference — 코드 분석
status: draft
created: 2026-05-14
updated: 2026-05-14
source_url: https://github.com/pyannote/pyannote-audio/blob/main/src/pyannote/audio/core/inference.py
fetched_at: 2026-05-14
sources:
  - "[[reference-01-pyannote-segmentation-3]]"
  - "[[reference-06-powerset-decoder]]"
tags: [reference, pyannote, inference, sliding-window, study-step-2, source-code]
---

# pyannote.audio.Inference — 코드 분석

> **출처**: `pyannote-audio/src/pyannote/audio/core/inference.py` (총 667 줄, class `Inference`)
> **목적**: 학습 2단계 — sliding window 동작, aggregation, padding 등 정확한 동작 확정

## Summary

`Inference` 는 batch 추론을 위한 wrapper. `window="sliding"` 모드에서 `waveform.unfold` 로 chunk 생성 → batch 추론 → **hamming-window 가중치 overlap-add aggregation**. `window="whole"` 은 단일 forward. powerset 모델은 자동으로 multilabel 로 변환 (`skip_conversion=False` 기본값).

---

## 1. 생성자 시그니처 (inference.py:78-89)

```python
def __init__(
    self,
    model: Model,
    window: Text = "sliding",
    duration: Optional[float] = None,
    step: Optional[float] = None,
    pre_aggregation_hook: Callable[[np.ndarray], np.ndarray] = None,
    skip_aggregation: bool = False,
    skip_conversion: bool = False,
    device: Optional[torch.device] = None,
    batch_size: int = 32,
):
```

| 파라미터 | 기본값 | 의미 |
|---|---|---|
| `window` | `"sliding"` | `"sliding"` or `"whole"` |
| `duration` | `None` → model 학습 duration | chunk 길이 (초). segmentation-3.0 = **10** |
| `step` | `None` → warm-up 또는 `0.1 * duration` | hop (초) |
| `batch_size` | **32** | inference 배치 크기 |
| `skip_aggregation` | False | True 면 chunk 별 raw 출력 |
| `skip_conversion` | False | True 면 powerset 그대로 유지 |
| `device` | model.device | torch device |

### duration / step 결정 로직

inference.py:117-124:
```python
training_duration = next(iter(specifications)).duration
duration = duration or training_duration
```

→ **duration 은 model spec 의 `specifications.duration` (= 학습 chunk 길이) 에서 자동 결정**. segmentation-3.0 의 경우 학습 시 10초였으므로 `duration=10.0` 이 자동 세팅. 사용자가 명시적으로 다른 값을 주면 warning 만 띄우고 사용.

inference.py:155-157:
```python
step = step or (
    0.1 * self.duration if self.warm_up[0] == 0.0 else self.warm_up[0]
)
```

→ **기본 step = duration × 0.1 = 1.0초** (10초 chunk 기준). warm_up 이 있는 모델이면 warm_up 값이 step 으로.

inference.py:159-164:
```python
if step > self.duration:
    raise ValueError(...)
```

→ step > duration 이면 ValueError. step ≤ duration 이면 항상 OK (gap 없음).

### Powerset 자동 변환 (inference.py:128-141)

```python
self.skip_conversion = skip_conversion

conversion = list()
for s in specifications:
    if s.powerset and not skip_conversion:
        c = Powerset(len(s.classes), s.powerset_max_classes)
    else:
        c = nn.Identity()
    conversion.append(c.to(self.device))
```

→ powerset 모델은 `Powerset(num_classes, max_set_size)` 모듈을 자동으로 생성해 후처리로 attach. `skip_conversion=True` 면 `nn.Identity` 라 raw 7-class 가 그대로 나옴 (reference-06 참조).

## 2. infer() — 배치 forward (inference.py:182-215)

```python
def infer(self, chunks: torch.Tensor) -> Union[np.ndarray, Tuple[np.ndarray]]:
    """
    chunks : (batch_size, num_channels, num_samples) torch.Tensor
    Returns
    -------
    outputs : (batch_size, ...) np.ndarray
    """
    with torch.inference_mode():
        outputs = self.model(chunks.to(self.device))
    # __convert: outputs → conversion(.) → cpu().numpy()
```

→ `torch.inference_mode()` 로 grad 차단, OOM 발생 시 batch_size 줄이라는 명시적 에러. 출력은 numpy.

## 3. slide() — sliding window 처리 (inference.py:217-373)

핵심 흐름:

### 3-1. chunk 분할 (inference.py:244-264)

```python
window_size: int = self.model.audio.get_num_samples(self.duration)
step_size: int = round(self.step * sample_rate)
_, num_samples = waveform.shape

# prepare complete chunks
if num_samples >= window_size:
    chunks: torch.Tensor = rearrange(
        waveform.unfold(1, window_size, step_size),
        "channel chunk frame -> chunk channel frame",
    )
    num_chunks, _, _ = chunks.shape
else:
    num_chunks = 0
```

- `torch.Tensor.unfold(dim, size, step)` 으로 sliding window 추출.
- shape 결과: `(channel, num_chunks, window_size)` → einops 로 `(num_chunks, channel, window_size)` 으로 재배열.
- num_samples < window_size 면 빈 chunks (마지막 padding chunk 만 처리).

### 3-2. 마지막 incomplete chunk padding (inference.py:269-278)

```python
has_last_chunk = (num_samples < window_size) or (
    num_samples - window_size
) % step_size > 0
if has_last_chunk:
    last_chunk: torch.Tensor = waveform[:, num_chunks * step_size :]
    _, last_window_size = last_chunk.shape
    last_pad = window_size - last_window_size
    last_chunk = F.pad(last_chunk, (0, last_pad))
```

→ **남은 audio + 오른쪽으로 0-padding 으로 window_size 채움**. 마지막 chunk 도 별도 inference 후 `aggregate` 단계에서 padding 영역을 잘라냄 (inference.py:364-367).

### 3-3. Batch loop (inference.py:295-319)

```python
for c in np.arange(0, num_chunks, self.batch_size):
    batch: torch.Tensor = chunks[c : c + self.batch_size]
    batch_outputs = self.infer(batch)
    # append to outputs

if has_last_chunk:
    last_outputs = self.infer(last_chunk[None])
```

→ 표준 mini-batch loop. 마지막 incomplete chunk 는 별도 forward.

### 3-4. Aggregation 분기 (inference.py:328-369)

```python
def __aggregate(outputs, frames, specifications):
    if (
        self.skip_aggregation
        or specifications.resolution == Resolution.CHUNK
        or (specifications.permutation_invariant and self.pre_aggregation_hook is None)
    ):
        # raw chunk-level output
        frames = SlidingWindow(start=0.0, duration=self.duration, step=self.step)
        return SlidingWindowFeature(outputs, frames)

    if self.pre_aggregation_hook is not None:
        outputs = self.pre_aggregation_hook(outputs)

    aggregated = self.aggregate(
        SlidingWindowFeature(outputs, SlidingWindow(start=0.0, duration=self.duration, step=self.step)),
        frames,
        warm_up=self.warm_up,
        hamming=True,    # ← 핵심
        missing=0.0,
    )

    if has_last_chunk:
        aggregated.data = aggregated.crop(
            Segment(0.0, num_samples / sample_rate), mode="loose"
        )
    return aggregated
```

→ 핵심: **`hamming=True` 기본값**, 마지막 chunk 의 padding 영역은 `crop` 으로 제거.

→ 화자 diarization 의 SpeakerDiarization Pipeline 은 `skip_aggregation=True` 로 호출하여 chunk 별 raw 출력을 유지 (clustering 이 chunk 별 segmentation 을 받아야 하기 때문 — reference-05 참조).

## 4. aggregate() — overlap-add hamming aggregation (inference.py:498-620)

핵심 로직 발췌:

### 4-1. Hamming window 생성 (inference.py:538-543)

```python
hamming_window = (
    np.hamming(num_frames_per_chunk).reshape(-1, 1)
    if hamming
    else np.ones((num_frames_per_chunk, 1))
)
```

`np.hamming(N)` = 0.54 - 0.46·cos(2π·n/(N-1)) — 중심이 1.0, 끝이 0.08 정도인 종 모양 가중치.

### 4-2. Warm-up 영역 처리 (inference.py:548-559)

```python
warm_up_window = np.ones((num_frames_per_chunk, 1))
warm_up_left = round(warm_up[0] / scores.sliding_window.duration * num_frames_per_chunk)
warm_up_window[:warm_up_left] = epsilon
warm_up_right = round(warm_up[1] / scores.sliding_window.duration * num_frames_per_chunk)
warm_up_window[num_frames_per_chunk - warm_up_right :] = epsilon
```

→ 양 끝 warm_up 영역은 `epsilon (1e-12)` 가중치 (사실상 무시). segmentation-3.0 은 warm_up=(0.0, 0.0) 이라 영향 없음.

### 4-3. Overlap-add 누적 (inference.py:588-611)

```python
for chunk, score in scores:
    mask = 1 - np.isnan(score)
    np.nan_to_num(score, copy=False, nan=0.0)
    start_frame = frames.closest_frame(chunk.start + 0.5 * frames.duration)
    aggregated_output[start_frame : start_frame + num_frames_per_chunk] += (
        score * mask * hamming_window * warm_up_window
    )
    overlapping_chunk_count[start_frame : start_frame + num_frames_per_chunk] += (
        mask * hamming_window * warm_up_window
    )
```

→ 각 chunk 의 `score` 를 hamming · warm_up · mask 가중치로 곱해 누적, **분모는 가중치 합**. NaN 영역은 mask=0 이라 분자/분모 둘 다 contribution 0.

### 4-4. 최종 평균 (inference.py:613-618)

```python
if skip_average:
    average = aggregated_output
else:
    average = aggregated_output / np.maximum(overlapping_chunk_count, epsilon)
average[aggregated_mask == 0.0] = missing
```

→ **분모 가중치 합으로 나누어 weighted mean**. 어떤 chunk 도 닿지 않은 영역은 `missing` 값 (`__aggregate` 에서 `missing=0.0` 전달).

→ **즉 "sliding window aggregation" 의 실체 = Hamming-weighted overlap-add average**. 단순 평균/최대 아님.

## 5. __call__() — 파일 처리 (inference.py:375-415)

```python
def __call__(self, file: AudioFile, hook: Optional[Callable] = None):
    fix_reproducibility(self.device)
    waveform, sample_rate = self.model.audio(file)

    if self.window == "sliding":
        return self.slide(waveform, sample_rate, hook=hook)

    outputs = self.infer(waveform[None])
    return outputs[0]  # (단순화)
```

| window | 입력 | 출력 |
|---|---|---|
| `"sliding"` | AudioFile (긴 파일) | `SlidingWindowFeature` (`data.shape = (num_frames, num_classes)`) |
| `"whole"` | AudioFile | `np.ndarray` (`(num_classes,)` or `(D,)` for embedding) |

`whole` 모드는 frame-based 모델에는 경고 (inference.py:108-114).

## 6. 입출력 형상 (segmentation-3.0 / 10초 sliding 기준)

| 단계 | shape | dtype |
|---|---|---|
| 입력 waveform | `(channel=1, num_samples)` | torch.float32 |
| 분할된 chunks | `(num_chunks, 1, 160000)` | torch.float32 |
| chunk 별 raw 출력 (powerset) | `(num_chunks, num_frames, 7)` | (model dep.) |
| 자동 multilabel 변환 후 | `(num_chunks, num_frames, 3)` | np.float32 |
| Aggregation 후 (skip_aggregation=False) | `(total_num_frames, 3)` SlidingWindowFeature | np.float32 |

여기서 `num_frames` = `model.num_frames(window_size)` — receptive field 계산 결과.

## 7. Frame rate — derived 값

**segmentation-3.0 (PyanNet 기반) frame rate 는 모델 카드에 명시 안 됨**. 코드에서 derive:

- `PyanNet.SINCNET_DEFAULTS = {"stride": 10}` (PyanNet.py:64)
- SincNet 의 cumulative stride: `[stride, 3, 1, 3, 1, 3]` = `[10, 3, 1, 3, 1, 3]` (sincnet.py:97)
- 총 stride = 10 × 3 × 1 × 3 × 1 × 3 = **270 samples**
- 16 kHz 기준: 270 / 16000 = **16.875 ms / frame**, 약 **59.3 fps**

→ 10초 chunk = 160000 samples 면 **frame 수 ≈ 589~592** (정확한 값은 `multi_conv_num_frames` 의 kernel overhead 까지 계산해야 — 우리가 산수로 derive 한 근사치).

→ 1단계 자료의 "**~20ms (50fps)** 추정" 은 **부정확**. 실제는 ~17ms / ~59fps.

## 8. Pipeline 에서의 사용 (실전 호출)

SpeakerDiarization 은 segmentation 을 다음과 같이 호출 (speaker_diarization.py:237-244, reference-05 에서 자세히):

```python
self._segmentation = Inference(
    model,
    duration=segmentation_duration,
    step=self.segmentation_step * segmentation_duration,  # = 0.1 × duration = 1.0s
    skip_aggregation=True,    # ← chunk 별 raw 출력 유지 (clustering 용)
    batch_size=segmentation_batch_size,
)
```

→ **Diarization Pipeline 은 `skip_aggregation=True`**. 즉 aggregate 하지 않고 `(num_chunks, num_frames, 3)` 모두 보관 → embedding 추출 & clustering 후 reconstruct 단계에서 별도 처리.

---

## 우리 라이브러리 영향 (실제 사실)

| 1단계 가정 | 코드 확정 | 행동 |
|---|---|---|
| frame rate ~20ms / 50fps | ❌ derived: **~16.875ms / ~59fps** (PyanNet stride=10) | 588~592 frame/chunk 기준으로 계산 |
| sliding hop 권장 500ms | Pipeline 기본 = **1초 (duration × 0.1)** | 우리는 latency 요구에 따라 200ms~1초 선택 |
| aggregation 방식 mean | ✅ **Hamming-weighted overlap-add** (inference.py:359) | 우리도 동일하게 |
| 마지막 chunk padding | ✅ **right-pad with zeros, crop after aggregate** | 동일 패턴 채택 |
| GPU/CPU latency | ❌ **코드에서 확인 불가** — 실측 필요 | 학습 3단계 (실측) |
| skip_aggregation 의 의미 | ✅ Pipeline 은 chunk 별 raw 출력 보존 (clustering 입력용) | streaming 에서도 raw 유지 후 자체 aggregation |
| batch_size 기본 | **32** (Inference) / **1** (SpeakerDiarization 내부) | streaming 은 chunk 1개씩 (batch 1) 자연스러움 |

### streaming 시 우리 라이브러리가 직접 해야 할 일

1. `WaveformBuffer` — 10초 sliding window 누적. hop = 0.5~1.0s.
2. **buffer 가 10초 차면**: model forward → `(1, num_frames, 7)` raw powerset 출력.
3. powerset → multilabel decoder (reference-06 의 numpy 의사코드).
4. **chunk 누적**: `(num_chunks, num_frames, 3)` 보관, hamming-weighted overlap-add 로 timeline 재구성.
5. timeline 의 화자 #0/#1/#2 는 local label — 다음 chunk 의 local label 과 매핑은 embedding clustering 단계에서 (reference-08).
6. 마지막 chunk: right-zero-pad → forward → `crop(0, real_duration)`.

---

## 미확인 사항 (남은 것)

- `Inference.audio.get_num_samples(duration)` 의 정확한 동작 — `Audio` 클래스 (core/io.py) 미정독. `duration × sample_rate` 의 단순 정수 변환일 가능성 높음.
- `multi_conv_num_frames` 의 정확한 공식 (utils/receptive_field.py 미정독) — 정확한 frame count 가 필요할 때만 정독하면 됨.
- segmentation-3.0 의 raw forward 가 log_softmax 인지 softmax 인지 — PyanNet.forward 정독 필요.
- batch_size = 32 vs 1 의 latency 차이 — 실측 필요.
