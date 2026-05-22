#!/usr/bin/env python3
"""Render ablation JSON results → single offline HTML report.

Spec: medi_docs/current/spec/spec-04-render-report.md
"""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import jinja2


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def load_rows(input_path: str) -> list[dict]:
    p = Path(input_path)
    if p.suffix == ".csv":
        rows = []
        with open(p, newline="") as f:
            for raw in csv.DictReader(f):
                row = dict(raw)
                # reconstruct nested metrics dict
                metric_keys = [
                    "der", "initial_cluster_latency_s",
                    "labeling_latency_p50_s", "labeling_latency_p95_s",
                    "label_consistency", "cpu_peak_pct", "cpu_avg_pct",
                    "ram_peak_mb", "ram_avg_mb", "cold_load_s", "total_runtime_s",
                ]
                row["metrics"] = {}
                for k in metric_keys:
                    try:
                        row["metrics"][k] = float(row.pop(k, 0) or 0)
                    except (ValueError, TypeError):
                        row["metrics"][k] = 0.0
                for fk in ["window_s", "step_s"]:
                    try:
                        row[fk] = float(row[fk])
                    except (ValueError, TypeError, KeyError):
                        pass
                rows.append(row)
        return rows
    else:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return [data]


# ─────────────────────────────────────────────────────────────────────────────
# Summary computation
# ─────────────────────────────────────────────────────────────────────────────

def _der(row: dict) -> float:
    v = row.get("metrics", {}).get("der", float("inf"))
    if v is None or (isinstance(v, float) and (v != v)):  # nan check
        return float("inf")
    return float(v)


def compute_summary(rows: list[dict]) -> dict:
    valid = [r for r in rows if not r.get("error") and _der(r) < float("inf")]
    if not valid:
        return {"best_overall": None, "best_per_model": {}, "tradeoff": None}

    best_overall = min(valid, key=_der)

    models = sorted({r["embedding"] for r in valid})
    best_per_model = {}
    for m in models:
        model_rows = [r for r in valid if r["embedding"] == m]
        if model_rows:
            best_per_model[m] = min(model_rows, key=_der)

    # tradeoff: best DER vs best latency
    best_latency = min(
        valid,
        key=lambda r: r.get("metrics", {}).get("labeling_latency_p50_s", float("inf"))
    )
    tradeoff = None
    if best_latency["embedding"] != best_overall["embedding"] or \
       best_latency["window_s"] != best_overall["window_s"]:
        tradeoff = {
            "der_champion": best_overall,
            "latency_champion": best_latency,
        }

    return {
        "best_overall": best_overall,
        "best_per_model": best_per_model,
        "tradeoff": tradeoff,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Chart data
# ─────────────────────────────────────────────────────────────────────────────

_COLORS = [
    "rgba(54,162,235,0.8)",
    "rgba(255,99,132,0.8)",
    "rgba(75,192,192,0.8)",
    "rgba(255,206,86,0.8)",
]


def build_chart_data(rows: list[dict]) -> dict:
    valid = [r for r in rows if not r.get("error")]
    models = sorted({r["embedding"] for r in valid})
    color_map = {m: _COLORS[i % len(_COLORS)] for i, m in enumerate(models)}

    _SCHED_COLORS = [
        "rgba(54,162,235,0.8)",
        "rgba(255,99,132,0.8)",
        "rgba(75,192,192,0.8)",
        "rgba(255,206,86,0.8)",
        "rgba(153,102,255,0.8)",
    ]

    def scatter_datasets(x_key: str, y_key: str = "der") -> list[dict]:
        datasets = []
        for m in models:
            pts = [
                {
                    "x": r.get("metrics", {}).get(x_key, 0),
                    "y": r.get("metrics", {}).get(y_key, 0),
                    "label": f"{r['sample']} w={r['window_s']} s={r['step_s']}",
                }
                for r in valid if r["embedding"] == m
            ]
            datasets.append({"label": m, "data": pts, "backgroundColor": color_map[m]})
        return datasets

    def line_datasets() -> list[dict]:
        # window_s vs DER, one line per embedding
        datasets = []
        for m in models:
            model_rows = [r for r in valid if r["embedding"] == m]
            window_der: dict[float, list] = {}
            for r in model_rows:
                w = float(r.get("window_s", 0))
                d = r.get("metrics", {}).get("der", 0)
                window_der.setdefault(w, []).append(d)
            pts = sorted(
                [{"x": w, "y": float(sum(ds) / len(ds))} for w, ds in window_der.items()],
                key=lambda p: p["x"]
            )
            datasets.append({"label": m, "data": pts, "borderColor": color_map[m],
                             "backgroundColor": color_map[m], "fill": False, "tension": 0.2})
        return datasets

    def scheduler_bar_datasets() -> dict:
        """Per-scheduler avg DER, one bar group per embedding."""
        schedulers = sorted({r.get("scheduler", "baseline") for r in valid})
        datasets = []
        for i, m in enumerate(models):
            model_valid = [r for r in valid if r["embedding"] == m]
            values = []
            for sc in schedulers:
                sc_rows = [r for r in model_valid if r.get("scheduler", "baseline") == sc]
                avg = float(sum(r["metrics"]["der"] for r in sc_rows) / len(sc_rows)) if sc_rows else 0.0
                values.append(round(avg, 4))
            datasets.append({
                "label": m,
                "data": values,
                "backgroundColor": _COLORS[i % len(_COLORS)],
            })
        return {"labels": schedulers, "datasets": datasets}

    def scheduler_delta_datasets() -> dict:
        """DER delta vs baseline per scheduler, one bar group per embedding."""
        schedulers = sorted({r.get("scheduler", "baseline") for r in valid})
        datasets = []
        for i, m in enumerate(models):
            model_valid = [r for r in valid if r["embedding"] == m]
            base_rows = [r for r in model_valid if r.get("scheduler", "baseline") == "baseline"]
            base_der = float(sum(r["metrics"]["der"] for r in base_rows) / len(base_rows)) if base_rows else 0.0
            values = []
            for sc in schedulers:
                sc_rows = [r for r in model_valid if r.get("scheduler", "baseline") == sc]
                avg = float(sum(r["metrics"]["der"] for r in sc_rows) / len(sc_rows)) if sc_rows else 0.0
                values.append(round(avg - base_der, 4))
            datasets.append({
                "label": m,
                "data": values,
                "backgroundColor": _COLORS[i % len(_COLORS)],
            })
        return {"labels": schedulers, "datasets": datasets}

    return {
        "der_latency": scatter_datasets("labeling_latency_p50_s"),
        "der_cpu": scatter_datasets("cpu_avg_pct"),
        "window_der": line_datasets(),
        "scheduler_bar": scheduler_bar_datasets(),
        "scheduler_delta": scheduler_delta_datasets(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Render
# ─────────────────────────────────────────────────────────────────────────────

def render(input_path: str, output_path: str, template_path: str, title: str) -> None:
    rows = load_rows(input_path)
    summary = compute_summary(rows)
    chart_data = build_chart_data(rows)

    tmpl_p = Path(template_path)
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(tmpl_p.parent)),
        autoescape=True,
    )
    tmpl = env.get_template(tmpl_p.name)
    html = tmpl.render(
        title=title,
        rows=rows,
        summary=summary,
        chart_data=json.dumps(chart_data, ensure_ascii=False),
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        total_rows=len(rows),
        error_rows=sum(1 for r in rows if r.get("error")),
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    print(f"[render_report] Written: {output_path} ({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render ablation results to HTML")
    parser.add_argument("--input", required=True, help="JSON or CSV result file")
    parser.add_argument("--output", default=None, help="Output HTML path")
    parser.add_argument("--template", default="templates/ablation_report.html")
    parser.add_argument("--title", default="Ablation Report")
    args = parser.parse_args()

    if args.output is None:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        stem = Path(args.input).stem
        args.output = str(Path(args.input).parent / f"report_{stem}_{ts}.html")

    render(args.input, args.output, args.template, args.title)
    print(f"[render_report] Open: {args.output}")


if __name__ == "__main__":
    main()
