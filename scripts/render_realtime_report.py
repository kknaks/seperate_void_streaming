#!/usr/bin/env python3
"""Render v03 realtime ablation JSON → standalone HTML report.

PLAN-V03-T-002 — Phase 3 실시간 측정 결과 시각화.

Charts:
  - live emit latency p50/p95 (pyannote vs ecapa per sample)
  - online DER progression at 30s/60s/end (line chart)
  - final DER vs v0.2 best (bar chart)

Usage:
    python scripts/render_realtime_report.py \\
        --input eval/ablation/results/v03/v03-realtime-YYYYMMDD_HHMMSS.json \\
        --output eval/ablation/results/v03-realtime-YYYYMMDD.html
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


_V02_BEST = {
    "pyannote/embedding": 0.199,
    "ecapa-tdnn": 0.205,
}

_COLORS = [
    "rgba(54,162,235,0.85)",   # blue — pyannote
    "rgba(255,99,132,0.85)",   # red — ecapa
    "rgba(75,192,192,0.85)",
    "rgba(255,206,86,0.85)",
]
_BORDER = [
    "rgba(54,162,235,1)",
    "rgba(255,99,132,1)",
    "rgba(75,192,192,1)",
    "rgba(255,206,86,1)",
]


def _safe(v, default=float("nan")):
    if v is None or (isinstance(v, float) and v != v):
        return default
    return v


def _pct(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "N/A"
    return f"{v:.1f}%"


def _sec(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "N/A"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}s"


def _der_str(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "N/A"
    return f"{v:.3f} ({v*100:.1f}%)"


def build_report(rows: list[dict]) -> str:
    valid = [r for r in rows if not r.get("error") and r.get("metrics")]
    models = sorted({r["embedding"] for r in valid})
    samples = sorted({r["sample"] for r in valid})
    color_map = {m: _COLORS[i % len(_COLORS)] for i, m in enumerate(models)}
    border_map = {m: _BORDER[i % len(_BORDER)] for i, m in enumerate(models)}

    ts = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    # ── Latency chart: grouped bar (p50/p95 per model per sample) ──────────────
    def latency_chart() -> str:
        labels = [f"{s} p50" for s in samples] + [f"{s} p95" for s in samples]
        datasets = []
        for m in models:
            data = []
            for s in samples:
                row = next((r for r in valid if r["embedding"] == m and r["sample"] == s), None)
                data.append(_safe(row["metrics"].get("live_emit_latency_p50_s") if row else None, 0))
            for s in samples:
                row = next((r for r in valid if r["embedding"] == m and r["sample"] == s), None)
                data.append(_safe(row["metrics"].get("live_emit_latency_p95_s") if row else None, 0))
            datasets.append({
                "label": m,
                "data": data,
                "backgroundColor": color_map[m],
                "borderColor": border_map[m],
                "borderWidth": 1,
            })
        return json.dumps({"labels": labels, "datasets": datasets}, ensure_ascii=False)

    # ── Online DER line chart: x=time point, y=DER per model per sample ────────
    def online_der_chart() -> str:
        labels = ["t=30s", "t=60s", "end"]
        key_map = {
            "t=30s": "online_der_at_30s",
            "t=60s": "online_der_at_60s",
            "end": "online_der_at_end",
        }
        datasets = []
        for idx, m in enumerate(models):
            for s in samples:
                row = next((r for r in valid if r["embedding"] == m and r["sample"] == s), None)
                if row is None:
                    continue
                data = [_safe(row["metrics"].get(key_map[l]), None) for l in labels]
                datasets.append({
                    "label": f"{m} / {s}",
                    "data": [{"x": l, "y": d} for l, d in zip(labels, data)],
                    "borderColor": color_map[m],
                    "backgroundColor": color_map[m],
                    "fill": False,
                    "tension": 0.2,
                    "borderDash": [] if "record_1" in s else [5, 5],
                })
        return json.dumps({"labels": labels, "datasets": datasets}, ensure_ascii=False)

    # ── Final DER bar chart: live vs v0.2 offline best ─────────────────────────
    def final_der_chart() -> str:
        label_list = models[:]
        live_data = []
        v02_data = []
        for m in models:
            live_vals = [r["metrics"].get("final_der") for r in valid if r["embedding"] == m]
            live_avg = float(sum(v for v in live_vals if v is not None and v == v) / max(1, sum(1 for v in live_vals if v is not None and v == v))) if live_vals else float("nan")
            live_data.append(_safe(live_avg, 0))
            v02_data.append(_V02_BEST.get(m, 0))
        datasets = [
            {
                "label": "v0.3 live (avg)",
                "data": live_data,
                "backgroundColor": "rgba(54,162,235,0.8)",
            },
            {
                "label": "v0.2 offline best",
                "data": v02_data,
                "backgroundColor": "rgba(200,200,200,0.8)",
            },
        ]
        return json.dumps({"labels": label_list, "datasets": datasets}, ensure_ascii=False)

    # ── Table rows ──────────────────────────────────────────────────────────────
    table_rows_html = ""
    for r in valid:
        m = r["metrics"]
        v02_best = _V02_BEST.get(r["embedding"], float("nan"))
        final_der = _safe(m.get("final_der"))
        delta = final_der - v02_best if (final_der == final_der and v02_best == v02_best) else float("nan")
        delta_str = f"{delta:+.3f}" if delta == delta else "N/A"
        delta_cls = "positive" if delta > 0 else ("negative" if delta < 0 else "")
        table_rows_html += f"""
        <tr>
            <td>{r["embedding"]}</td>
            <td>{r["sample"]}</td>
            <td>{r.get("audio_dur_s", "?"):.1f}s</td>
            <td>{_sec(m.get("live_emit_latency_p50_s"))}</td>
            <td>{_sec(m.get("live_emit_latency_p95_s"))}</td>
            <td>{_der_str(m.get("online_der_at_30s"))}</td>
            <td>{_der_str(m.get("online_der_at_60s"))}</td>
            <td>{_der_str(m.get("online_der_at_end"))}</td>
            <td><strong>{_der_str(final_der)}</strong></td>
            <td class="{delta_cls}">{delta_str}</td>
            <td>{_pct(m.get("cpu_peak_pct"))}</td>
            <td>{m.get("ram_peak_mb", 0):.0f} MB</td>
        </tr>"""

    latency_cd = latency_chart()
    online_der_cd = online_der_chart()
    final_der_cd = final_der_chart()
    n_rows = len(valid)
    n_error = len([r for r in rows if r.get("error")])

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>void_streaming v0.3 — Realtime Ablation Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1200px; margin: 30px auto; padding: 20px; color: #222; line-height: 1.6; }}
h1 {{ border-bottom: 3px solid #4a90e2; padding-bottom: 10px; }}
h2 {{ color: #4a90e2; margin-top: 30px; }}
.chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0; }}
.chart-box {{ background: #f9f9f9; padding: 15px; border-radius: 6px; border: 1px solid #ddd; }}
.chart-box.wide {{ grid-column: span 2; }}
canvas {{ max-height: 320px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin: 15px 0; overflow-x: auto; display: block; }}
th, td {{ border: 1px solid #ddd; padding: 7px 10px; text-align: left; white-space: nowrap; }}
th {{ background: #4a90e2; color: white; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
.positive {{ color: #d9534f; font-weight: bold; }}
.negative {{ color: #5cb85c; font-weight: bold; }}
.note {{ background: #fff8e1; border-left: 4px solid #ffc107; padding: 10px 15px; margin: 15px 0; border-radius: 3px; font-size: 13px; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 15px 0; }}
.kpi-card {{ background: white; padding: 12px; border: 1px solid #ddd; border-radius: 4px; text-align: center; }}
.kpi-card .label {{ font-size: 12px; color: #666; }}
.kpi-card .value {{ font-size: 20px; font-weight: bold; color: #333; }}
footer {{ margin-top: 50px; padding-top: 20px; border-top: 1px solid #eee; color: #888; font-size: 13px; }}
</style>
</head>
<body>

<h1>🎙 void_streaming v0.3 — Realtime Ablation Report</h1>
<p style="color:#888">Generated: {ts} · {n_rows} rows · {n_error} errors</p>
<p>Phase 3: 라이브 스트리밍 환경에서 pyannote/embedding × ecapa-tdnn 측정.<br>
emit latency (양수 = real-time 뒤처짐) / online DER 진행 / final DER vs v0.2 비교.</p>

<div class="note">
<strong>측정 방법:</strong> WAV 파일을 슬라이딩 윈도우(w=2.0s, step=0.5s)로 순차 처리.
latency = wallclock_at_emit - audio_t_end_of_window. 양수는 real-time 뒤처짐.
offline StreamingInference 없음 → demo_v03 diart_loop 동일 경로.
</div>

<h2>📊 핵심 지표</h2>
<div class="kpi-grid">
{"".join(
    f'<div class="kpi-card"><div class="label">{r["embedding"]} / {r["sample"]}</div>'
    f'<div class="value">{_der_str(r["metrics"].get("final_der"))}</div>'
    f'<div class="label">final DER</div></div>'
    for r in valid
)}
</div>

<h2>📈 차트</h2>
<div class="chart-grid">
  <div class="chart-box">
    <h3>Live Emit Latency — p50/p95 (단위: 초, 양수=뒤처짐)</h3>
    <canvas id="latencyChart"></canvas>
  </div>
  <div class="chart-box">
    <h3>Final DER: v0.3 live vs v0.2 offline best</h3>
    <canvas id="finalDerChart"></canvas>
  </div>
  <div class="chart-box wide">
    <h3>Online DER 시간별 진행 (점선 = record_3)</h3>
    <canvas id="onlineDerChart"></canvas>
  </div>
</div>

<h2>📑 상세 결과</h2>
<table>
<thead>
<tr>
  <th>Embedding</th><th>Sample</th><th>Audio</th>
  <th>Latency p50</th><th>Latency p95</th>
  <th>DER @30s</th><th>DER @60s</th><th>DER @end</th>
  <th>Final DER</th><th>vs v0.2</th>
  <th>CPU peak</th><th>RAM peak</th>
</tr>
</thead>
<tbody>
{table_rows_html}
</tbody>
</table>

<h2>🔍 원시 데이터</h2>
<pre style="background:#f5f5f5;padding:15px;border-radius:4px;font-size:12px;overflow:auto;max-height:300px">{json.dumps(rows, indent=2, ensure_ascii=False)}</pre>

<footer>
<p>void_streaming v0.3 realtime ablation — PLAN-V03-T-002</p>
<p>v0.2 baseline (offline StreamingInference): pyannote=0.199, ecapa=0.205</p>
</footer>

<script>
const latencyData = {latency_cd};
const onlineDerData = {online_der_cd};
const finalDerData = {final_der_cd};

new Chart(document.getElementById("latencyChart"), {{
  type: "bar",
  data: latencyData,
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: "top" }} }},
    scales: {{
      y: {{ title: {{ display: true, text: "seconds (+ = behind realtime)" }} }}
    }}
  }}
}});

new Chart(document.getElementById("onlineDerChart"), {{
  type: "line",
  data: onlineDerData,
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: "top" }} }},
    scales: {{
      y: {{ title: {{ display: true, text: "DER" }}, min: 0 }}
    }}
  }}
}});

new Chart(document.getElementById("finalDerChart"), {{
  type: "bar",
  data: finalDerData,
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: "top" }} }},
    scales: {{
      y: {{ title: {{ display: true, text: "DER (avg across samples)" }}, min: 0 }}
    }}
  }}
}});
</script>
</body>
</html>"""
    return html


def main() -> None:
    parser = argparse.ArgumentParser(description="Render realtime ablation JSON → HTML")
    parser.add_argument("--input", required=True, help="JSON result file")
    parser.add_argument("--output", default=None, help="Output HTML path")
    args = parser.parse_args()

    rows = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        rows = [rows]

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = str(Path(args.input).parent / f"v03-realtime-{ts}.html")

    html = build_report(rows)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(html, encoding="utf-8")
    print(f"[render_realtime_report] Written: {args.output} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
