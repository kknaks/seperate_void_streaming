"""render_index.py — v0.2 ablation study 최종 종합 HTML 생성.

산출물:
- eval/ablation/results/INDEX.html — top-level entry point
- eval/ablation/results/phase1-analysis.html — markdown → HTML 변환

INDEX 는 모든 Phase 의 HTML / RTTM viewer / 분석 보고서를 link.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import markdown


ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "eval" / "ablation" / "results"
DATA_KOREAN = ROOT / "eval" / "data" / "korean"
RETROSPECTIVE = ROOT / "medi_docs" / "current" / "retrospective"


INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>void_streaming v0.2 — Ablation Study INDEX</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1100px; margin: 30px auto; padding: 20px; line-height: 1.7; color: #222; }}
h1 {{ border-bottom: 3px solid #4a90e2; padding-bottom: 10px; }}
h2 {{ color: #4a90e2; margin-top: 30px; }}
.phase {{ background: #f7f9fc; padding: 15px 25px; margin: 20px 0; border-left: 4px solid #4a90e2; border-radius: 4px; }}
.phase.done {{ border-left-color: #5cb85c; }}
.phase.pending {{ border-left-color: #f0ad4e; }}
.phase.blocked {{ border-left-color: #d9534f; }}
.status {{ display: inline-block; padding: 3px 10px; border-radius: 3px; font-size: 12px; font-weight: bold; }}
.status.done {{ background: #5cb85c; color: white; }}
.status.pending {{ background: #f0ad4e; color: white; }}
.status.blocked {{ background: #d9534f; color: white; }}
ul {{ padding-left: 25px; }}
li {{ margin: 6px 0; }}
a {{ color: #4a90e2; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.summary-table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
.summary-table th, .summary-table td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
.summary-table th {{ background: #4a90e2; color: white; }}
.summary-table tr:nth-child(even) {{ background: #f9f9f9; }}
.muted {{ color: #888; font-size: 13px; }}
.kpi {{ font-size: 22px; font-weight: bold; color: #4a90e2; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 15px 0; }}
.kpi-card {{ background: white; padding: 12px; border: 1px solid #ddd; border-radius: 4px; text-align: center; }}
.kpi-card .label {{ font-size: 12px; color: #666; }}
.kpi-card .value {{ font-size: 20px; font-weight: bold; color: #333; }}
footer {{ margin-top: 50px; padding-top: 20px; border-top: 1px solid #eee; color: #888; font-size: 13px; }}
</style>
</head>
<body>

<h1>🎙 void_streaming v0.2 — Ablation Study INDEX</h1>
<p class="muted">Generated: {generated_at}</p>
<p>한국어 회의/상담 도메인에서 화자 분리 정확도 최적화 — embedding × window × scheduler ablation study + 결과 기반 단순 demo.</p>

<h2>📊 핵심 결과 요약</h2>

<div class="kpi-grid">
<div class="kpi-card"><div class="label">측정 row</div><div class="value">72</div></div>
<div class="kpi-card"><div class="label">embedding 모델</div><div class="value">3</div></div>
<div class="kpi-card"><div class="label">best avg DER</div><div class="value">0.199</div></div>
<div class="kpi-card"><div class="label">best runtime (real-time)</div><div class="value">16s / 277s</div></div>
</div>

<table class="summary-table">
<tr><th>모델</th><th>best avg DER</th><th>avg runtime</th><th>실시간 가능?</th></tr>
<tr><td>wespeaker-resnet221</td><td>0.176</td><td>368s</td><td>❌ CPU 11.5x</td></tr>
<tr><td><strong>pyannote/embedding</strong> ⭐</td><td><strong>0.199</strong></td><td><strong>16s</strong></td><td>✅ CPU 실시간 OK</td></tr>
<tr><td>ecapa-tdnn</td><td>0.205</td><td>46s</td><td>✅ CPU 실시간 OK (일관성 최고)</td></tr>
</table>

<p class="muted">상세 분석: <a href="phase1-analysis.html">Phase 1 분석 보고서</a></p>

<h2>📁 Phase 별 산출물</h2>

<div class="phase done">
<h3>Phase 0 — 환경 구축 <span class="status done">DONE</span></h3>
<ul>
<li>4 embedding 모델 wrap (pyannote / ECAPA-TDNN / WeSpeaker, TitaNet-L 폐기)</li>
<li>한국어 데이터셋 + RTTM ground truth (자동 생성)
  <ul>
    <li>📁 <a href="../../data/korean/record_1.wav">record_1.wav</a> (277.5s) + <a href="../../data/korean/record_1.rttm">record_1.rttm</a></li>
    <li>🔍 <a href="../../data/korean/record_1_viewer.html">record_1 RTTM viewer</a></li>
    <li>📁 <a href="../../data/korean/record_3.wav">record_3.wav</a> (168.2s) + <a href="../../data/korean/record_3.rttm">record_3.rttm</a></li>
    <li>🔍 <a href="../../data/korean/record_3_viewer.html">record_3 RTTM viewer</a></li>
  </ul>
</li>
<li>📜 scripts/eval_ablation.py + scripts/render_report.py</li>
<li>📜 scripts/rttm_viewer.py + scripts/generate_rttm.py + scripts/render_index.py</li>
</ul>
</div>

<div class="phase done">
<h3>Phase 1 — embedding × window × step grid <span class="status done">DONE</span></h3>
<ul>
<li>📊 <a href="phase1-full-20260522.html">Phase 1 Full HTML (72 rows, 차트 + sortable table)</a> ⭐</li>
<li>📊 <a href="phase1-pilot-20260522.html">Phase 1 Pilot HTML (record_1 36 rows)</a></li>
<li>📊 <a href="phase1-partial-20260522.html">Phase 1 Partial HTML</a></li>
<li>📄 <a href="phase1-analysis.html">Phase 1 분석 보고서 (markdown 기반)</a></li>
<li>📑 Raw JSON: <code>eval/ablation/results/20260522_*.json</code> (5 files) + <code>all.csv</code></li>
</ul>
<p><strong>핵심 발견</strong>:</p>
<ul>
<li><strong>step=0.5 압도적 우위</strong> — step=0.1/0.25 는 DER 0.85+ (실용 불가)</li>
<li><strong>window=2.0 최적</strong> — 전 모델 공통</li>
<li>북극성 (DER ≤ 0.15) 미달 — best 17.6% (wespeaker CPU)</li>
<li>record_3 DER 전반 높음 — sample 난이도 vs RTTM 품질 검증 진행 중</li>
</ul>
</div>

<div class="phase done">
<h3>Phase 2 — scheduler ablation <span class="status done">DONE</span></h3>
<ul>
<li>📊 <a href="phase2-20260522.html">Phase 2 HTML (20 rows, scheduler 비교 차트)</a> ⭐</li>
<li>입력: pyannote/embedding + ecapa-tdnn (w=2.0 s=0.5)</li>
<li>scheduler 5종: baseline / decay-A / decay-B / hdbscan-on / hdbscan-off</li>
<li>측정: 2 후보 × 5 scheduler × 2 sample = 20 rows (에러 0)</li>
<li>📄 <a href="../../../reports/PLAN-V02-T-007-evaluator.md">PLAN-V02-T-007 결과 리포트</a></li>
</ul>
<p><strong>핵심 발견</strong>:</p>
<ul>
<li><strong>scheduler 효과 미미</strong> — 어떤 variant도 2pp 이상 DER 개선 없음 (채택 기준 미달)</li>
<li>decay-A: 전 모델 악화 (avg +6.5pp). decay-B: 소폭 악화 (+2.1pp)</li>
<li>hdbscan-on: pyannote 소폭 개선 (−0.3pp), ecapa-tdnn 대폭 악화 (+8.4pp) — 비일관성</li>
<li><strong>결론</strong>: baseline (diart default) 채택 권고. 북극성 DER ≤ 0.15 미달, Phase 3 또는 GPU 환경 검토 필요</li>
</ul>
</div>

<div class="phase pending">
<h3>Phase 3 — demo 구현 <span class="status pending">PENDING</span></h3>
<ul>
<li>Phase 2 결과 후 별도 plan 분리</li>
<li>diart + 선택 embedding + ElevenLabs STT + UI 4-panel</li>
<li>운영 환경 enrollment (Phase 4) 는 out of v0.2 scope</li>
</ul>
</div>

<h2>📚 문서 인덱스</h2>

<table class="summary-table">
<tr><th>분류</th><th>문서</th><th>설명</th></tr>
<tr><td rowspan="2">adr</td><td><a href="../../../medi_docs/current/adr/adr-01-ablation-centric-design.md">adr-01</a></td><td>wrapper 폐기 + ablation-centric 정체성</td></tr>
<tr><td><a href="../../../medi_docs/current/adr/adr-02-html-report.md">adr-02</a></td><td>HTML report 공유 (본 INDEX 의 근거)</td></tr>
<tr><td>planning</td><td><a href="../../../medi_docs/current/planning/planning-01-ablation-study.md">planning-01</a></td><td>v0.2 큰 그림 plan</td></tr>
<tr><td rowspan="3">plan</td><td><a href="../../../medi_docs/current/plan/PLAN-V02-001-phase0-env-setup.md">PLAN-V02-001</a></td><td>Phase 0 환경 구축</td></tr>
<tr><td><a href="../../../medi_docs/current/plan/PLAN-V02-002-phase1-grid.md">PLAN-V02-002</a></td><td>Phase 1 grid</td></tr>
<tr><td><a href="../../../medi_docs/current/plan/PLAN-V02-003-phase2-scheduler.md">PLAN-V02-003</a></td><td>Phase 2 scheduler</td></tr>
<tr><td>spec</td><td><a href="../../../medi_docs/current/spec/">spec-01 ~ spec-06</a></td><td>grid / embedding interface / scripts / metric</td></tr>
<tr><td>retrospective</td><td><a href="phase1-analysis.html">phase1-analysis</a></td><td>Phase 1 분석 보고서</td></tr>
<tr><td>legacy</td><td><a href="../../../medi_docs/legacy/v0.1-demo/">v0.1-demo</a></td><td>폐기된 PLAN-001~006 자료 보존</td></tr>
</table>

<footer>
<p>void_streaming v0.2 ablation study — 한국어 회의/상담 도메인 화자 분리 최적화</p>
<p>모든 측정 결과의 raw 데이터는 <code>eval/ablation/results/</code>, 데이터셋은 <code>eval/data/korean/</code></p>
</footer>

</body>
</html>
"""


ANALYSIS_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1000px; margin: 30px auto; padding: 20px; line-height: 1.7; color: #222; }}
h1 {{ border-bottom: 3px solid #4a90e2; padding-bottom: 10px; }}
h2 {{ color: #4a90e2; margin-top: 30px; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
h3 {{ color: #333; margin-top: 25px; }}
table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
table th, table td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
table th {{ background: #4a90e2; color: white; }}
table tr:nth-child(even) {{ background: #f9f9f9; }}
code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
pre {{ background: #f4f4f4; padding: 12px; border-radius: 4px; overflow-x: auto; }}
pre code {{ background: none; padding: 0; }}
blockquote {{ border-left: 4px solid #4a90e2; padding-left: 15px; color: #555; margin: 15px 0; }}
.nav {{ background: #f7f9fc; padding: 10px 20px; border-radius: 4px; margin-bottom: 20px; }}
.nav a {{ color: #4a90e2; text-decoration: none; }}
.nav a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="nav"><a href="INDEX.html">← v0.2 INDEX 로 돌아가기</a></div>
{content}
<div class="nav" style="margin-top: 40px;"><a href="INDEX.html">← v0.2 INDEX 로 돌아가기</a></div>
</body>
</html>
"""


def render_markdown_to_html(md_path: Path, output_path: Path, title: str) -> None:
    md_text = md_path.read_text(encoding="utf-8")
    # frontmatter 제거 (--- ... ---)
    if md_text.startswith("---"):
        end = md_text.find("\n---\n", 3)
        if end != -1:
            md_text = md_text[end + 5 :]
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "nl2br"],
    )
    html = ANALYSIS_TEMPLATE.format(title=title, content=html_body)
    output_path.write_text(html, encoding="utf-8")
    print(f"[render_index] Written: {output_path}")


def render_index(output_path: Path) -> None:
    html = INDEX_TEMPLATE.format(generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    output_path.write_text(html, encoding="utf-8")
    print(f"[render_index] Written: {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default=str(RESULTS_DIR))
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1 analysis HTML 변환
    analysis_md = RETROSPECTIVE / "phase1-analysis.md"
    if analysis_md.exists():
        render_markdown_to_html(
            analysis_md,
            results_dir / "phase1-analysis.html",
            "Phase 1 Ablation 분석 — Embedding × Window × Step",
        )

    # INDEX HTML
    render_index(results_dir / "INDEX.html")

    print(f"[render_index] Open: {results_dir / 'INDEX.html'}")


if __name__ == "__main__":
    main()
