---
id: spec-05
type: spec
title: 데이터셋 + Ground Truth 명세
status: draft
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[planning-01-ablation-study]]"
  - "[[spec-01-ablation-grid]]"
  - "[[spec-06-metrics]]"
tags: [spec, v0.2, dataset, ground-truth, rttm, ami]
---

# spec-05 — 데이터셋 + Ground Truth 명세

## Summary

ablation 평가에 사용할 오디오 데이터셋 목록, 저장 위치, Ground Truth (RTTM) 형식, 수집 우선순위를 명세한다. 실제 데이터셋 수집/RTTM 변환은 T-004 (evaluator) 영역.

---

## 데이터셋 목록

### AMI Corpus Subset (영어 baseline)

| 항목 | 값 |
|------|---|
| 목적 | V-01 baseline 유지 — 영어 benchmark 비교 |
| 세션 수 | 4 session (ES2002a/b/c/d 또는 동등) |
| 형식 | 16kHz mono WAV |
| 저장 위치 | `eval/data/ami/` |
| Ground Truth | `eval/data/ami/*.rttm` |
| 출처 | AMI Meeting Corpus (공개 데이터) |
| 비고 | V-01 baseline 에서 사용한 session 그대로 |

AMI ground truth 는 공식 RTTM 파일 활용:
- `http://groups.inf.ed.ac.uk/ami/corpus/` (공개 라이선스 CC-BY 4.0)

### 한국어 회의/상담 Sample

| 항목 | 값 |
|------|---|
| 목적 | 운영 환경(한국어 의료 상담)에 가까운 평가 |
| 파일명 | `record_1.wav` 외 N개 (사용자 제공) |
| 형식 | 16kHz mono WAV 권장 (다른 경우 변환 필요) |
| 저장 위치 | `eval/data/korean/` |
| Ground Truth | `eval/data/korean/*.rttm` |
| 수집 상태 | **T-004 에서 정리** — 사용자 보유 |

---

## Ground Truth 형식 (RTTM)

pyannote.metrics 표준 RTTM:

```
SPEAKER <file_id> 1 <onset> <duration> <NA> <NA> <speaker_id> <NA> <NA>
```

예시:
```
SPEAKER ES2002a 1 0.000 2.340 <NA> <NA> SPEAKER_00 <NA> <NA>
SPEAKER ES2002a 1 2.500 1.800 <NA> <NA> SPEAKER_01 <NA> <NA>
```

**필드 설명**:
- `<file_id>`: WAV 파일명 (확장자 제외)
- `<onset>`: 발화 시작 시간 (초)
- `<duration>`: 발화 길이 (초)
- `<speaker_id>`: 화자 고유 ID (세션 내 일관성 필수)

---

## 저장 구조

```
eval/
  data/
    ami/
      ES2002a.wav
      ES2002a.rttm
      ES2002b.wav
      ES2002b.rttm
      ES2002c.wav
      ES2002c.rttm
      ES2002d.wav
      ES2002d.rttm
    korean/
      record_1.wav
      record_1.rttm
      record_2.wav       # 추가 sample (사용자 제공)
      record_2.rttm
      ...
```

---

## 수집 우선순위

1. **의료 상담 음성** — 운영 환경에 가장 근접 (DER 실용 신뢰도 최고)
2. **다화자 (2~4인) 자연 대화** — ablation 의미 있으려면 최소 2화자
3. **최소 30초, 권장 3분 이상** — latency 측정 신뢰도
4. AMI corpus 는 영어 benchmark 보조 역할 (한국어 결과가 우선)

---

## 데이터셋 등록 방식 (eval_ablation.py)

```bash
--samples eval/data/ami/ES2002a.wav eval/data/korean/record_1.wav \
--gt-rttm ES2002a.wav:eval/data/ami/ES2002a.rttm \
--gt-rttm record_1.wav:eval/data/korean/record_1.rttm
```

`--gt-rttm` 은 `<sample_basename>:<rttm_path>` 형태로 반복 지정.

---

## 후속 task (T-004 evaluator)

- 한국어 sample RTTM 생성/검증
- AMI RTTM 다운로드 확인
- 오디오 포맷 변환 (필요 시 16kHz mono 변환 스크립트)
- 데이터셋 등록 절차 문서화
