---
id: reference-06
type: reference
title: Powerset decoder — 코드 분석
status: draft
created: 2026-05-14
updated: 2026-05-14
source_url: https://github.com/pyannote/pyannote-audio/blob/main/src/pyannote/audio/utils/powerset.py
fetched_at: 2026-05-14
sources:
  - "[[reference-01-pyannote-segmentation-3]]"
  - "[[reference-03-pyannote-audio-overview]]"
tags: [reference, pyannote, powerset, decoder, study-step-2, source-code]
---

# Powerset decoder — 코드 분석

> **출처**: `pyannote-audio/src/pyannote/audio/utils/powerset.py` (총 241 줄)
> **목적**: 학습 2단계 — segmentation-3.0 출력 디코딩 알고리즘 확정

## Summary

`Powerset(num_classes, max_set_size)` 클래스는 **powerset ↔ multilabel 양방향 변환** 을 제공한다. `num_classes=3, max_set_size=2` 면 7 powerset class 가 만들어진다. 변환은 `mapping` 버퍼와 `matmul` 으로 수행 — `(B, T, num_powerset) @ (num_powerset, num_classes) → (B, T, num_classes)`.

---

## 1. 클래스 시그니처 (powerset.py:48-54)

```python
class Powerset(nn.Module):
    def __init__(self, num_classes: int, max_set_size: int):
        super().__init__()
        self.num_classes = num_classes
        self.max_set_size = max_set_size
        self.register_buffer("mapping", self.build_mapping(), persistent=False)
        self.register_buffer("cardinality", self.build_cardinality(), persistent=False)
```

- `num_classes` = 한 chunk 의 **최대 화자 수** (segmentation-3.0 = **3**)
- `max_set_size` = 한 frame 의 **동시 발화 최대 화자 수** (segmentation-3.0 = **2**)

`Inference.__init__` 에서는 이 값을 model spec 에서 가져옴 (inference.py:131-136):

```python
for s in specifications:
    if s.powerset and not skip_conversion:
        c = Powerset(len(s.classes), s.powerset_max_classes)
    else:
        c = nn.Identity()
```

→ segmentation-3.0 의 `specifications.classes` 길이 = 3, `powerset_max_classes` = 2.

## 2. 7-class 생성 알고리즘 (powerset.py:80-109)

```python
@cached_property
def powerset_classes(self) -> list[set[int]]:
    """List of powerset classes

    e.g. with num_classes = 3 and max_set_size = 2:
    {}, {0}, {1}, {2}, {0, 1}, {0, 2}, {1, 2}
    """
    powerset_classes = []
    for set_size in range(0, self.max_set_size + 1):
        for current_set in combinations(range(self.num_classes), set_size):
            powerset_classes.append(set(current_set))
    return powerset_classes
```

핵심: `range(0, max_set_size + 1)` 이므로 `set_size = 0, 1, 2` 순차로 `combinations` 호출.

| set_size | combinations(3, k) | 개수 | 누적 인덱스 |
|---|---|---|---|
| 0 | `[()]` | 1 | 0 |
| 1 | `(0,), (1,), (2,)` | 3 | 1, 2, 3 |
| 2 | `(0,1), (0,2), (1,2)` | 3 | 4, 5, 6 |
| **총** | | **7** | |

`build_mapping()` 은 이 클래스를 `(7, 3)` 행렬로 (powerset.py:80-109):

```python
[0, 0, 0]  # none           ← non-speech
[1, 0, 0]  # class #1
[0, 1, 0]  # class #2
[0, 0, 1]  # class #3
[1, 1, 0]  # classes #1 and #2  ← overlap (0,1)
[1, 0, 1]  # classes #1 and #3  ← overlap (0,2)
[0, 1, 1]  # classes #2 and #3  ← overlap (1,2)
```

→ reference-01 에 적힌 7-class 표와 정확히 일치 (확정).

## 3. Powerset → Multilabel (powerset.py:115-140)

```python
def to_multilabel(self, powerset: torch.Tensor, soft: bool = False) -> torch.Tensor:
    """
    powerset : (batch_size, num_frames, num_powerset_classes) torch.Tensor
        Soft predictions in "powerset" space.
    soft : bool, optional
        Return soft multi-label predictions. Defaults to False (i.e. hard predictions)
        Assumes that `powerset` are "log probabilities".
    """
    if soft:
        powerset_probs = torch.exp(powerset)
    else:
        powerset_probs = torch.nn.functional.one_hot(
            torch.argmax(powerset, dim=-1),
            self.num_powerset_classes,
        ).float()

    return torch.matmul(powerset_probs, self.mapping)
```

알고리즘 발췌:
1. **Hard mode** (default): `argmax` 로 7 class 중 1개 선택 → one-hot → mapping 과 matmul.
2. **Soft mode**: log-prob 을 exp 해서 soft prob → mapping 과 matmul (각 화자별 marginal probability).

`forward` 는 `to_multilabel` 의 alias (powerset.py:142-144).

## 4. Multilabel → Powerset (powerset.py:146-168)

```python
def to_powerset(self, multilabel: torch.Tensor) -> torch.Tensor:
    return F.one_hot(
        torch.argmax(torch.matmul(multilabel, self.mapping.T), dim=-1),
        num_classes=self.num_powerset_classes,
    )
```

→ multilabel 을 mapping transpose 와 곱해 가장 유사한 powerset class 의 one-hot 출력. hard 변환만 지원.

## 5. Powerset 결과의 frame 별 의미

`(num_frames, 7)` shape 의 raw model output 에서:
- raw model output 은 **log-probability** (또는 sigmoid 가 아닌 softmax) — `Inference.aggregate` 가 hamming-window weighted 평균하기 때문에 frame 별 7 차원이 각각 누적된 후 합쳐짐.
- `Inference.__init__` (line 130-141) 가 `Powerset(3,2)` 모듈을 `self.conversion` 으로 잡고 `infer()` 호출 시 자동 적용 → 사용자에게는 multilabel `(num_frames, 3)` 으로 보임 (`skip_conversion=False` 기본값).
- `skip_conversion=True` 면 `(num_frames, 7)` powerset 그대로 출력.

## 6. Inverse pseudocode (직접 구현 시)

powerset → multilabel decoder 를 우리 라이브러리에서 직접 구현해야 한다면:

```python
# 7-class mapping (segmentation-3.0 고정 가정)
MAPPING = np.array([
    [0, 0, 0],   # 0: silence
    [1, 0, 0],   # 1: spk #1
    [0, 1, 0],   # 2: spk #2
    [0, 0, 1],   # 3: spk #3
    [1, 1, 0],   # 4: spk #1 + #2
    [1, 0, 1],   # 5: spk #1 + #3
    [0, 1, 1],   # 6: spk #2 + #3
], dtype=np.float32)

def powerset_to_multilabel_hard(scores: np.ndarray) -> np.ndarray:
    """
    scores: (num_frames, 7) — softmax/log-prob 출력
    returns: (num_frames, 3) — 각 화자별 0/1
    """
    hard_class = np.argmax(scores, axis=-1)  # (num_frames,)
    one_hot = np.eye(7, dtype=np.float32)[hard_class]  # (num_frames, 7)
    return one_hot @ MAPPING  # (num_frames, 3)


def powerset_to_multilabel_soft(log_probs: np.ndarray) -> np.ndarray:
    """log-prob → 각 화자별 marginal probability"""
    probs = np.exp(log_probs)  # (num_frames, 7)
    return probs @ MAPPING  # (num_frames, 3) — float
```

→ pyannote 의존 없이 numpy 만으로 구현 가능. mapping 매트릭스는 build 단계에서 고정 (segmentation-3.0 architecture 가 바뀌지 않는 한).

## 7. Permutation mapping (powerset.py:170-241)

학습 시 화자 순서를 permute 할 때 multilabel permutation 을 powerset permutation 으로 변환. 우리 추론 라이브러리에는 **불필요** (학습 코드 전용).

---

## 우리 라이브러리 영향 (실제 사실)

| 1단계 가정 | 코드 확정 | 행동 |
|---|---|---|
| 7-class 의 정확한 의미 | ✅ class 0=silence, 1~3=단독, 4~6=overlap (mapping 매트릭스 7×3 박제) | 그대로 사용 |
| `argmax` 로 hard / `exp+matmul` 로 soft | ✅ 양쪽 모두 표준 (powerset.py:132-140) | 우리도 hard / soft 둘 다 지원 |
| pyannote 의존 필요? | ❌ 불필요 — mapping 매트릭스만 박으면 numpy 로 충분 | speaker_engine 내부에 mini decoder 박제 가능 (lock-in 감소) |
| inverse 도 필요한지 | hard inverse 만 제공. inference 에는 forward 만 쓰임 | inverse 는 학습 외엔 불필요 |

**핵심 결정**: speaker_engine 의 powerset decoder 는 pyannote `Powerset` 클래스에 의존하지 말고 위 의사코드처럼 numpy 7×3 mapping 으로 자체 구현 → 외부 라이브러리 의존성 ↓, segmentation 모델만 갈아끼우면 됨.

---

## 미확인 사항 (남은 것)

- 학습 시 `powerset_max_classes` 가 모델 카드/checkpoint hparams 에서 어떻게 노출되는지 (pretrained 모델 로드 시 `model.specifications.powerset_max_classes` 가 자동 셋업됨은 inference.py:131-136 에서 확인됨, 그러나 specifications 의 raw 값을 보려면 모델을 실제로 로드해야 함).
- soft mode 의 log_prob 입력 가정 — segmentation-3.0 의 forward 가 log_softmax 인지 softmax 인지는 forward 함수를 봐야 (PyanNet.py 미확인). `Inference.__init__` 가 `Powerset` 을 그대로 후처리로 붙이므로 모델 출력이 이미 log_prob 형태로 학습돼 있을 가능성 높음.
