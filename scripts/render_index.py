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

<h1>🎙 void_streaming v0.4 — INDEX</h1>
<p class="muted">Generated: {generated_at}</p>
<p>한국어 회의 도메인 화자 분리 + 실시간 STT 자막 + 라이브 화자 라벨링 demo. v0.2 (ablation) → v0.3 (라이브 매핑) → v0.4 (라이브 latency + 운영 가이드).</p>

<div style="background: #fff3cd; border-left: 6px solid #f0ad4e; padding: 20px 25px; margin: 25px 0; border-radius: 4px;">
<h2 style="margin-top: 0; color: #8a6d3b; border: none;">⭐ 운영 배포 가이드 — 결론</h2>
<p style="font-size: 15px;"><strong>설정</strong>: <code>pyannote/embedding × window=2.0s × step=0.5s × baseline scheduler × CPU</code></p>
<p style="font-size: 15px;"><strong>Azure VM</strong>: <strong>Standard B2s</strong> (2 vCPU, 4GB RAM, ~$30/월)</p>
<p style="font-size: 15px;"><strong>SLA</strong>: STT 자막 ~0.5s · 라이브 라벨링 p50 <strong>1.5s</strong> / p95 <strong>2.4s</strong> · DER ~0.20 · CPU 38× realtime</p>
<p style="font-size: 16px; margin-top: 15px;">📘 <a href="v04-operational-guide.html" style="color: #8a6d3b; font-weight: bold;">전체 운영 가이드 보기 →</a></p>
</div>

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

<p class="muted">상세 분석: <a href="v02-final.html"><strong>v0.2 최종 종합 ⭐</strong></a> · <a href="phase1-analysis.html">Phase 1 분석</a></p>

<h2>📁 Phase 별 산출물</h2>

<h2>📁 Phase 별 산출물</h2>

<div class="phase done">
<h3>Phase 0~1 — Embedding × Window × Step ablation <span class="status done">DONE</span></h3>
<ul>
<li>📊 <a href="phase1-full-20260522.html"><strong>Phase 1 Full HTML (72 rows)</strong> ⭐</strong></a> — 차트 + sortable table</li>
<li>📄 <a href="phase1-analysis.html">Phase 1 분석 보고서</a></li>
<li>측정: 3 embedding (pyannote / ecapa-tdnn / wespeaker) × 4 window × 3 step × 2 sample = 72 rows</li>
</ul>
<p><strong>핵심 발견</strong>:</p>
<ul>
<li><strong>step=0.5 압도적 우위</strong> — step=0.1/0.25 는 DER 0.85+ (실용 불가)</li>
<li><strong>window=2.0 최적</strong> — 전 모델 공통</li>
<li>북극성 (DER ≤ 0.15) 미달 — best 17.6% (wespeaker CPU 비실용)</li>
</ul>
</div>

<div class="phase done">
<h3>Phase 2 — Scheduler ablation (8 variant 통합) <span class="status done">DONE</span></h3>
<ul>
<li>📊 <a href="phase2-final-20260522.html"><strong>Phase 2 최종 HTML (32 rows, 8 scheduler)</strong> ⭐</a></li>
<li>5 정적 variant + 3 legacy 동적 variant (AdaptiveReclusterScheduler / FinalReclusterer HDBSCAN / both)</li>
<li>측정: 2 embedding × (5+3) scheduler × 2 sample = 32 rows</li>
</ul>
<p><strong>핵심 발견</strong>:</p>
<ul>
<li><strong>8 variant 모두 baseline 못 이김</strong> (≥2pp 기준 미달) → baseline 채택 확정</li>
<li>legacy-adaptive: 유일하게 양 모델 평균 개선 (−0.3~−0.5pp), 기준 미달</li>
<li>legacy-final (HDBSCAN): ecapa-tdnn +10pp 악화</li>
<li>📄 <a href="v02-final.html"><strong>v0.2 ablation 최종 종합</strong></a></li>
</ul>
</div>

<div class="phase done">
<h3>Phase 3 — 라이브 매핑 검증 <span class="status done">DONE</span></h3>
<ul>
<li>📊 <a href="v03-realtime-20260523.html">v0.3 라이브 ablation HTML</a> — 4 rows (2 embedding × 2 sample) 라이브 환경</li>
<li><strong>demo_v03.py</strong> — diart + ElevenLabs STT + 시간 overlap mapping + UI 4-panel</li>
<li>시연 81 phrase: 초기 50초 cluster 형성 후 <strong>stable (A=고객 / B=상담사)</strong></li>
<li>pyannote 라이브 DER 0.224 — 1순위 재확인</li>
</ul>
</div>

<div class="phase done">
<h3>Phase 4 — 라이브 latency + 운영 가이드 <span class="status done">DONE</span></h3>
<ul>
<li>📘 <a href="v04-operational-guide.html"><strong>⭐ v0.4 운영 가이드 (Azure 배포 권장)</strong></a></li>
<li>📄 <a href="v04-live-latency.html">v0.4 라이브 latency retrospective</a></li>
<li>측정: pyannote × record_1 (p50 1.51s) + record_3 (p50 1.58s)</li>
<li>v0.3 음수 latency 공식 보정 → 진짜 wall-clock 측정</li>
<li><strong>운영 배포 가능 수준 확정</strong> — Azure B2s (2vCPU/4GB) 권장</li>
</ul>
</div>

<h2>📚 산출물 인덱스</h2>

<table class="summary-table">
<tr><th>분류</th><th>파일</th><th>설명</th></tr>
<tr><td rowspan="2"><strong>⭐ 결론</strong></td><td><a href="v04-operational-guide.html">v04-operational-guide.html</a></td><td><strong>운영 배포 가이드 (Azure VM + 설정값 + SLA)</strong></td></tr>
<tr><td><a href="v02-final.html">v02-final.html</a></td><td>v0.2 ablation 최종 종합 (최적 조합 박제)</td></tr>
<tr><td rowspan="4">ablation HTML</td><td><a href="phase1-full-20260522.html">phase1-full</a></td><td>72 rows embedding × window × step</td></tr>
<tr><td><a href="phase2-final-20260522.html">phase2-final</a></td><td>32 rows 8 scheduler 비교</td></tr>
<tr><td><a href="v03-realtime-20260523.html">v03-realtime</a></td><td>4 rows 라이브 환경 재측정</td></tr>
<tr><td><a href="v04-live-latency.html">v04-live-latency</a></td><td>라이브 wall-clock latency</td></tr>
<tr><td rowspan="2">분석</td><td><a href="phase1-analysis.html">phase1-analysis</a></td><td>Phase 1 분석 보고서</td></tr>
<tr><td><a href="v04-live-latency.html">v04-live-latency</a></td><td>v0.4 latency retrospective</td></tr>
<tr><td>raw 데이터</td><td><code>_raw/</code></td><td>측정 JSON / CSV 누적 (Phase 1/2/v03/v04)</td></tr>
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

    # v0.2 final 종합 분석 HTML 변환
    final_md = RETROSPECTIVE / "v02-final.md"
    if final_md.exists():
        render_markdown_to_html(
            final_md,
            results_dir / "v02-final.html",
            "v0.2 Ablation Study 최종 종합",
        )

    # v0.4 라이브 latency
    v04_lat_md = RETROSPECTIVE / "v04-live-latency.md"
    if v04_lat_md.exists():
        render_markdown_to_html(
            v04_lat_md,
            results_dir / "v04-live-latency.html",
            "v0.4 Phase 4 — 진짜 라이브 latency",
        )

    # v0.4 운영 가이드 (release-notes)
    op_guide_md = ROOT / "medi_docs" / "current" / "release-notes" / "v04-operational-guide.md"
    if op_guide_md.exists():
        render_markdown_to_html(
            op_guide_md,
            results_dir / "v04-operational-guide.html",
            "void_streaming v0.4 — 운영 가이드",
        )

    # INDEX HTML
    render_index(results_dir / "INDEX.html")

    print(f"[render_index] Open: {results_dir / 'INDEX.html'}")


if __name__ == "__main__":
    main()
