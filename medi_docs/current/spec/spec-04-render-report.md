---
id: spec-04
type: spec
title: render_report.py + HTML Template 명세
status: draft
created: 2026-05-22
updated: 2026-05-22
sources:
  - "[[planning-01-ablation-study]]"
  - "[[spec-01-ablation-grid]]"
tags: [spec, v0.2, report, html, visualization]
---

# spec-04 — render_report.py + HTML Template 명세

## Summary

`scripts/render_report.py` 스크립트와 Jinja2 HTML 템플릿 구조를 명세한다. ablation 결과 JSON/CSV → 단일 offline HTML 보고서 생성.

---

## 스크립트 위치

```
scripts/render_report.py
templates/ablation_report.html
```

---

## CLI 인터페이스

```bash
python scripts/render_report.py [options]
```

| 인자 | 기본값 | 설명 |
|------|--------|------|
| `--input` | 필수 | JSON 결과 파일 또는 `all.csv` 경로 |
| `--output` | `eval/ablation/report_YYYYMMDD.html` | 출력 HTML 경로 |
| `--template` | `templates/ablation_report.html` | Jinja2 템플릿 경로 |
| `--title` | `Ablation Report` | HTML 제목 |

**예시**:
```bash
python scripts/render_report.py \
  --input eval/ablation/results/all.csv \
  --output eval/ablation/report_20260522.html
```

---

## 입력 데이터 처리

- JSON 단일 파일: rows array 로드
- CSV (`all.csv`): pandas / csv 모듈로 로드 후 동일 row dict 구조로 변환
- 두 형식 모두 spec-01 schema 필드 기준

---

## 출력: 단일 HTML 파일

- **offline 가능**: CSS 인라인 + Chart.js CDN (또는 번들 인라인)
- 단일 `.html` 파일로 공유 가능

---

## HTML 구조 (섹션)

### 1. 요약 섹션

```
- Best overall: (embedding, window, step) → DER {value}
- Best per model:
  - pyannote/embedding: (w={}, s={}) → DER {}
  - ecapa-tdnn: ...
  - wespeaker-resnet221: ...
  - titanet-l: ...
- Trade-off highlight: 최소 DER vs 최소 labeling latency (서로 다르면 표기)
```

### 2. 모델별 Sortable Table

컬럼: `embedding | window_s | step_s | sample | DER | latency_p50 | latency_p95 | label_consistency | cpu_peak | ram_peak | gpu_peak | gpu_mem_peak | cold_load | total_runtime | error`

- JavaScript 기반 column sort
- `error` 있는 row 는 배경색 강조

### 3. 비교 Chart (Chart.js)

| Chart | X축 | Y축 | 색 구분 |
|-------|-----|-----|---------|
| DER vs labeling latency scatter | `labeling_latency_p50_s` | `der` | embedding model |
| DER vs CPU scatter | `cpu_avg_pct` | `der` | embedding model |
| DER vs GPU memory scatter | `gpu_mem_peak_mb` | `der` | embedding model |
| window vs DER line chart | `window_s` | `der` | embedding model (per line) |

---

## 의존성

```
jinja2>=3.x
pandas  # csv 처리용 (또는 csv 표준 라이브러리)
```

Chart.js: CDN `https://cdn.jsdelivr.net/npm/chart.js` (또는 번들 인라인)

---

## 템플릿 구조 (`templates/ablation_report.html`)

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{ title }}</title>
  <!-- inline CSS -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
  <h1>{{ title }}</h1>
  
  <!-- 1. 요약 섹션 -->
  <section id="summary">
    <h2>Summary</h2>
    <p>Best overall: <strong>{{ best_overall.embedding }}</strong>
       window={{ best_overall.window_s }}s step={{ best_overall.step_s }}s
       → DER={{ "%.3f"|format(best_overall.der) }}</p>
    ...
  </section>

  <!-- 2. 모델별 테이블 -->
  <section id="table">
    <h2>Results Table</h2>
    <table id="results-table">
      <thead>...</thead>
      <tbody>
        {% for row in rows %}
        <tr class="{{ 'error-row' if row.error else '' }}">
          <td>{{ row.embedding }}</td>
          ...
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </section>

  <!-- 3. Charts -->
  <section id="charts">
    <canvas id="der-latency-scatter"></canvas>
    <canvas id="der-cpu-scatter"></canvas>
    <canvas id="der-gpu-mem-scatter"></canvas>
    <canvas id="window-der-line"></canvas>
  </section>

  <script>
    // Chart.js 초기화 — JSON data inline
    const data = {{ chart_data | tojson }};
    ...
  </script>
</body>
</html>
```

---

## render_report.py 핵심 로직

```python
def render(input_path, output_path, template_path, title):
    rows = load_rows(input_path)          # JSON 또는 CSV
    summary = compute_summary(rows)       # best overall, per model
    chart_data = build_chart_data(rows)   # Chart.js 용 datasets
    
    env = jinja2.Environment(loader=jinja2.FileSystemLoader("."))
    tmpl = env.get_template(template_path)
    html = tmpl.render(
        title=title,
        rows=rows,
        summary=summary,
        chart_data=chart_data,
    )
    Path(output_path).write_text(html, encoding="utf-8")
```

---

## Why HTML (adr-02 예정)

사용자 의도: "JSON → HTML 템플릿 렌더링 + 결과 모델별 grouping". offline 공유 가능하고 Chart.js 로 인터랙티브 시각화 제공. Jupyter notebook 은 환경 의존성이 높아 기각.
