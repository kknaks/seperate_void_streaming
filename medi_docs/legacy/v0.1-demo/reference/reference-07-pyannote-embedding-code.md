---
id: reference-07
type: reference
title: pyannote embedding 모델 — 코드 분석
status: draft
created: 2026-05-14
updated: 2026-05-14
source_url: https://github.com/pyannote/pyannote-audio/tree/main/src/pyannote/audio/models/embedding
fetched_at: 2026-05-14
sources:
  - "[[reference-02-pyannote-embedding]]"
  - "[[reference-05-pyannote-pipeline-flow]]"
tags: [reference, pyannote, embedding, wespeaker, xvector, study-step-2, source-code]
---

# pyannote embedding 모델 — 코드 분석

> **출처**:
> - `pyannote-audio/src/pyannote/audio/models/embedding/__init__.py`
> - `pyannote-audio/src/pyannote/audio/models/embedding/xvector.py`
> - `pyannote-audio/src/pyannote/audio/models/embedding/wespeaker/__init__.py`
> - `pyannote-audio/src/pyannote/audio/pipelines/speaker_verification.py`
> **목적**: 학습 2단계 — 정확한 D, sample_rate, L2 정규화 여부 확정

## Summary

`pyannote.audio.models.embedding` 안에는 **두 계열 backbone** 이 있다:
1. **XVector 계열** (`XVectorMFCC`, `XVectorSincNet`) — 구식. **architecture default dim = 512**. `pyannote/embedding` legacy 모델이 사용.
2. **WeSpeaker ResNet 계열** (`WeSpeakerResNet34/152/221/293`) — 신식. **ResNet의 embed_dim = 256** (현재 코드 기준, `__init__.py:370` 등). community-1 / precision-2 의 `embedding/` subfolder 가 이 backbone.

→ pyannote 코드 자체는 **L2 정규화하지 않음**. diart 가 별도로 norm=1 정규화 (reference-08).

---

## 1. Embedding 등록 (__init__.py:24-39)

```python
from .wespeaker import (
    WeSpeakerResNet34,
    WeSpeakerResNet152,
    WeSpeakerResNet221,
    WeSpeakerResNet293,
)
from .xvector import XVectorMFCC, XVectorSincNet

__all__ = [
    "XVectorSincNet",
    "XVectorMFCC",
    "WeSpeakerResNet34",
    "WeSpeakerResNet152",
    "WeSpeakerResNet221",
    "WeSpeakerResNet293",
]
```

## 2. XVector 계열 (xvector.py)

### XVectorSincNet — 시그니처 (xvector.py:208-216)

```python
class XVectorSincNet(Model):
    SINCNET_DEFAULTS = {"stride": 10}

    def __init__(
        self,
        sample_rate: int = 16000,
        num_channels: int = 1,
        sincnet: Optional[dict] = None,
        dimension: int = 512,
        task: Optional[Task] = None,
    ):
```

- **architecture default `dimension = 512`**
- **architecture default `sample_rate = 16000`**
- 단, 이는 **architecture 생성자 default 일 뿐**. 실제 HuggingFace checkpoint 의 `hparams` 가 `save_hyperparameters("sincnet", "dimension")` (xvector.py:221) 으로 박혀 있으므로 checkpoint 마다 달라질 수 있다. legacy `pyannote/embedding` 의 실제 값은 모델 다운로드 후 `model.hparams.dimension` / `model.audio.sample_rate` 로 확인해야 정확.

### XVectorMFCC

```python
class XVectorMFCC(Model):
    MFCC_DEFAULTS = {"n_mfcc": 40, "dct_type": 2, "norm": "ortho", "log_mels": False}

    def __init__(
        self,
        sample_rate: int = 16000,
        num_channels: int = 1,
        mfcc: Optional[dict] = None,
        dimension: int = 512,
        task: Optional[Task] = None,
    ):
```

→ MFCC 기반 (SincNet 대신). 동일하게 `dimension=512` default.

### Forward (xvector.py:185-202)

```python
def forward(self, waveforms: torch.Tensor, weights: Optional[torch.Tensor] = None) -> torch.Tensor:
    outputs = self.mfcc(waveforms).squeeze(dim=1)
    for block in self.tdnns:
        outputs = block(outputs)
    outputs = self.stats_pool(outputs, weights=weights)
    return self.embedding(outputs)
```

→ MFCC → TDNN 5 layers ([512, 512, 512, 512, 1500]) → StatsPool → Linear(in×2, dimension). 마지막 Linear 후 **별도 정규화 없음**.

## 3. WeSpeaker 계열 (wespeaker/__init__.py)

### 시그니처 (wespeaker/__init__.py:346-372 ResNet34)

```python
class WeSpeakerResNet34(BaseWeSpeakerResNet):
    def __init__(
        self,
        sample_rate: int = 16000,
        num_channels: int = 1,
        num_mel_bins: int = 80,
        frame_length: int = 25,
        frame_shift: int = 10,
        dither: float = 0.0,
        window_type: str = "hamming",
        use_energy: bool = False,
        task: Optional[Task] = None,
    ):
        super().__init__(...)
        self.resnet = ResNet34(
            num_mel_bins, 256, pooling_func="TSTP", two_emb_layer=False
        )
```

→ `ResNet34(feat_dim=80, embed_dim=256, ...)` — **architecture embed_dim = 256**. ResNet152/221/293 도 모두 256.

→ `dimension` 프로퍼티 (wespeaker/__init__.py:161-168):
```python
@property
def dimension(self) -> int:
    if self.fbank_only:
        return self.hparams.num_mel_bins
    return self.resnet.embed_dim
```

→ 즉 **WeSpeaker ResNet 계열의 D = 256** (architecture 차원). community-1 / precision-2 의 `embedding/` subfolder 도 이 backbone 이므로 **D = 256**.

### Forward (wespeaker/__init__.py:324-343, BaseWeSpeakerResNet)

```python
def forward(self, waveforms: torch.Tensor, weights: Optional[torch.Tensor] = None) -> torch.Tensor:
    fbank = self.compute_fbank(waveforms)
    return self.resnet(fbank, weights=weights)[1]
```

→ Kaldi-style fbank → ResNet → embedding. **별도 L2 정규화 없음**. `weights` 는 frame 별 mask (overlap 영역 제외 등).

### fbank 파라미터 (wespeaker/__init__.py:57-99)

```python
sample_rate: int = 16000,
num_mel_bins: int = 80,
frame_length: float = 25.0,   # in milliseconds
frame_shift: float = 10.0,    # in milliseconds
```

→ 25ms / 10ms hop fbank. sample_rate 16kHz 가정 (NotImplementedError 는 없으나 default).

## 4. PretrainedSpeakerEmbedding wrapper (speaker_verification.py)

Pipeline 이 사용하는 high-level wrapper. backbone 별 4 구현:
- `NeMoPretrainedSpeakerEmbedding` (line 60)
- `SpeechBrainPretrainedSpeakerEmbedding` (line 202)
- `ONNXWeSpeakerPretrainedSpeakerEmbedding` (line ~440 — community-1 / precision-2 의 ONNX 버전)
- `PyannoteAudioPretrainedSpeakerEmbedding` (line 622 — pure pyannote)

`PretrainedSpeakerEmbedding(embedding, ...)` factory (speaker_verification.py:719-778):
- `"pyannote/embedding"` 같은 pyannote 문자열 → `PyannoteAudioPretrainedSpeakerEmbedding` (legacy XVector)
- `"speechbrain/..."` → SpeechBrain
- `"nvidia/..."` → NeMo
- `"wespeaker/..."` → ONNX WeSpeaker
- 그 외 → fallback to pyannote

### PyannoteAudioPretrainedSpeakerEmbedding 핵심 (speaker_verification.py:676-716)

```python
@cached_property
def sample_rate(self) -> int:
    return self.model_.audio.sample_rate

@cached_property
def dimension(self) -> int:
    return self.model_.dimension

@cached_property
def metric(self) -> str:
    return "cosine"

@cached_property
def min_num_samples(self) -> int:
    with torch.inference_mode():
        lower, upper = 2, round(0.5 * self.sample_rate)
        middle = (lower + upper) // 2
        while lower + 1 < upper:
            try:
                _ = self.model_(torch.randn(1, 1, middle).to(self.device))
                upper = middle
            except Exception:
                lower = middle
            middle = (lower + upper) // 2
    return upper

def __call__(self, waveforms, masks=None):
    with torch.inference_mode():
        if masks is None:
            embeddings = self.model_(waveforms.to(self.device))
        else:
            embeddings = self.model_(waveforms.to(self.device), weights=masks.to(self.device))
    return embeddings.cpu().numpy()
```

핵심 사실:
- **`metric = "cosine"`** 고정. 코드 박제값 (line 685-686).
- **`min_num_samples` 는 runtime binary search** — 2 samples ~ 0.5·sample_rate (= 0.5초) 사이를 이분 탐색해 model 이 forward 성공하는 최소 길이를 찾음.
- **L2 정규화 없음** — `embeddings.cpu().numpy()` 그대로 반환.
- mask 지원 — `weights` 로 model forward 에 frame 별 가중치 전달 → stats pooling 에서 가중 평균 (chunk 안의 특정 화자 frame 만 사용 가능).

### ONNXWeSpeaker (community-1 의 embedding) (speaker_verification.py:481-619)

```python
@cached_property
def sample_rate(self) -> int:
    return 16000

@cached_property
def dimension(self) -> int:
    dummy_waveforms = torch.rand(1, 1, 16000)
    features = self.compute_fbank(dummy_waveforms)
    embeddings = self.session_.run(
        output_names=["embs"], input_feed={"feats": features.numpy()}
    )[0]
    _, dimension = embeddings.shape
    return dimension

@cached_property
def metric(self) -> str:
    return "cosine"
```

→ **sample_rate 는 16000 고정** (line 482-483). dimension 은 dummy waveform 으로 inference 해 실측 (line 486-493). 마찬가지로 **L2 정규화 없음** (line 596 단순 numpy 변환).

## 5. L2 정규화 — 명확한 답

### pyannote 측: 정규화 X

| 위치 | 코드 | 결론 |
|---|---|---|
| `XVectorSincNet.forward` | `return self.embedding(outputs)` (xvector.py:202) | Linear 출력 그대로 |
| `BaseWeSpeakerResNet.forward` | `return self.resnet(fbank, weights=weights)[1]` (wespeaker/__init__.py:343) | ResNet 출력 그대로 |
| `PyannoteAudioPretrainedSpeakerEmbedding.__call__` | `embeddings.cpu().numpy()` 그대로 (speaker_verification.py:716) | 정규화 없음 |
| `ONNXWeSpeakerPretrainedSpeakerEmbedding.__call__` | `embeddings = self.session_.run(...)` (line 593) | 정규화 없음 |

→ pyannote 가 반환하는 embedding 은 **raw vector**. norm 이 1 이 아닐 수 있음.

### diart 측: 정규화 O

`diart/src/diart/functional.py:16-27`:
```python
def normalize_embeddings(embeddings: torch.Tensor, norm: float | torch.Tensor = 1) -> torch.Tensor:
    if embeddings.ndim == 2:
        embeddings = embeddings.unsqueeze(0)
    emb_norm = torch.norm(embeddings, p=2, dim=-1, keepdim=True)
    return norm * embeddings / emb_norm
```

→ **L2 (p=2) norm 으로 나누고 target norm 곱**. `EmbeddingNormalization(norm=1)` 가 default — `OverlapAwareSpeakerEmbedding` 가 호출 (reference-08 참조).

→ **결론**: cosine distance 만 쓴다면 L2 정규화 여부는 상관없다 (cosine 은 자체적으로 normalize). 다만 우리 라이브러리에서 **저장 시 정규화된 형태로 박는 것이 코드 일관성에 좋음** (diart 컨벤션과 일치).

## 6. 단일 화자 audio 권장 — 코드 어디 박혀있나

명시적 제약은 없으나, 다음 두 곳에서 "분리된 화자 audio" 를 가정함이 드러남:

### `min_num_samples` (speaker_verification.py:114-132, 689-702)

너무 짧은 audio 는 model 이 forward 실패 → 0.5초보다 짧으면 NaN. 분리 후 너무 짧은 발화면 embedding 안 나옴.

### `embedding_exclude_overlap` (speaker_diarization.py:332-478)

```python
embedding_exclude_overlap: bool = False
```

`True` 면 **overlap 영역의 frame 을 mask 에서 제외** 한 후 embedding 계산. 즉 한 화자만 명확히 있는 frame 만으로 평균 — "단일 화자 audio" 라는 가정을 명시적으로 보장.

코드 발췌 (speaker_diarization.py:382-392):
```python
clean_frames = 1.0 * (
    np.sum(binary_segmentations.data, axis=2, keepdims=True) < 2
)
clean_segmentations = SlidingWindowFeature(
    binary_segmentations.data * clean_frames,
    binary_segmentations.sliding_window,
)
```

→ "active speaker count < 2" 인 frame 만 mask 에 남김 = 단일 화자 가정.

community-1 / precision-2 의 default 는 `embedding_exclude_overlap = False` (speaker_diarization.py:205) 이지만, overlap 영역은 segmentation mask 가 작아 stats pooling 가중치가 낮아짐으로 자연스럽게 단일 화자 frame 비중이 큼.

## 7. legacy `pyannote/embedding` vs community-1 embedding 의 차이

| 항목 | `pyannote/embedding` (legacy) | community-1 `embedding/` subfolder |
|---|---|---|
| backbone | `XVectorSincNet` (architecture 추정) | WeSpeaker ResNet34 (ONNX) |
| architecture dim default | **512** | **256** |
| sample_rate | 16 kHz | 16 kHz |
| input feature | SincNet (raw waveform) | Kaldi fbank (80 mel) |
| wrapper | `PyannoteAudioPretrainedSpeakerEmbedding` | `ONNXWeSpeakerPretrainedSpeakerEmbedding` |
| metric | cosine | cosine |
| L2 정규화 | 없음 | 없음 |

→ **pyannote/embedding 의 정확한 dim 은 실제 checkpoint 로드 후 `model.dimension` 으로 확인 필요** (architecture 생성자 default 는 512 이지만 hparams 가 override 될 수 있음). 단 일반적으로 512 가 거의 확정 (X-vector 의 표준 dim).

→ community-1 의 embedding 은 ResNet34 의 embed_dim 이 코드에 256 으로 박혀있으므로 (`__init__.py:370`) **D = 256 확정**.

---

## 우리 라이브러리 영향 (실제 사실)

| 1단계 가정 | 코드 확정 | 행동 |
|---|---|---|
| D = 512 | **모델에 따라 다름** — legacy XVector default 512, community-1 ResNet34 = 256 | 코드 상수 X, `model.dimension` 으로 runtime 결정 |
| sample_rate = 16 kHz | ✅ 두 계열 모두 16 kHz default | 16 kHz 고정 OK |
| 최소 audio 길이 | **runtime binary search** (2 samples ~ 0.5·sr) | `min_num_samples` 만 신뢰, 하드코드 X |
| metric = cosine | ✅ 코드 박제 (`metric = "cosine"`) | 그대로 |
| L2 정규화 여부 | **pyannote 출력 X, diart 가 별도 정규화 (norm=1)** | 우리 SpeakerStore 저장 전 명시적 L2 정규화 권장 |
| mask 지원 | ✅ `weights` 로 frame 가중치 전달 → stats pool 가중평균 | overlap 영역 가중치 ↓ 로 단일 화자 가정 자연 보장 |

### 핵심 가이드

1. **D 는 모델 의존** — speaker_engine config 에 `dimension: int` 를 dynamic 으로 (model.dimension 으로 초기화). 하드코드 금지.
2. **L2 정규화 명시적** — pyannote raw 를 받자마자 `e / np.linalg.norm(e)` 적용. cosine distance 만 쓰니 결과는 같지만 저장 일관성 ↑, diart 호환성 ↑.
3. **min_audio_duration** — runtime detect 결과 사용. 일반적으로 ~0.1초 (1600 samples) ~ 0.5초가 안전 범위.
4. **threshold 가이드 없음** — 모델 카드/코드 모두 cosine threshold 권장값 없음. 데이터셋 별 튜닝 필요.
5. **mask 활용** — segmentation 결과로 만든 binary mask 를 embedding model 에 `weights=` 로 전달하면 overlap 영역 자연 제거.

---

## 미확인 사항 (남은 것)

- `pyannote/embedding` checkpoint 의 **실제** hparams 값 (dimension/sample_rate) — model 다운로드 후 직접 확인 필요. 일반적으로 architecture default 와 동일 (512 / 16kHz) 추정.
- `min_num_samples` 의 실측치 — 모델별 실측 필요. legacy XVector 는 1600 samples (0.1초) 정도, ONNX WeSpeaker 는 더 짧을 수 있음.
- ResNet34 의 embed_dim 이 community-1 checkpoint 에서도 256 유지인지 — ONNX session 의 출력 shape 확인 필요 (`PretrainedSpeakerEmbedding.dimension` 이 dummy 로 실측하므로 의문 없을 가능성 높음).
- GPU/CPU inference latency — 코드에서 확인 불가, 실측 필요.
