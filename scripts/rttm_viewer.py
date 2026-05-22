"""Generate a self-contained HTML viewer for RTTM diarization results.

Usage (single):
    python scripts/rttm_viewer.py --audio eval/data/korean/record_1.wav \
        --rttm eval/data/korean/record_1.rttm \
        --output eval/data/korean/record_1_viewer.html

Usage (batch):
    python scripts/rttm_viewer.py --dir eval/data/korean/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# HTML template — self-contained, no external CDN required
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <title>RTTM Viewer — {title}</title>
  <style>
    body {{ font-family: sans-serif; background: #111; color: #eee; margin: 20px; }}
    h1 {{ font-size: 18px; margin-bottom: 8px; }}
    audio {{ width: 100%; margin-bottom: 10px; }}
    .current-speaker {{
      font-size: 20px; padding: 8px 12px; background: #333;
      border-radius: 4px; margin-bottom: 10px; min-height: 36px;
    }}
    .timeline-wrap {{ position: relative; height: 60px; background: #222;
      border-radius: 4px; overflow: hidden; cursor: pointer; }}
    .segment {{ position: absolute; top: 0; height: 60px; opacity: 0.75; }}
    .cursor {{ position: absolute; top: 0; width: 2px; height: 60px;
      background: white; pointer-events: none; transition: left 0.05s linear; }}
    .time-labels {{ position: relative; height: 18px; }}
    .time-label {{ position: absolute; font-size: 10px; color: #888;
      transform: translateX(-50%); }}
    .legend {{ margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px; }}
    .legend-item {{ padding: 4px 12px; border-radius: 12px; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>RTTM Viewer — {title}</h1>

  <audio id="player" controls src="{audio_src}"></audio>

  <div class="current-speaker" id="currentSpeaker">현재 화자: —</div>

  <div class="timeline-wrap" id="timeline"></div>
  <div class="time-labels" id="timeLabels"></div>
  <div class="legend" id="legend"></div>

  <script>
    const segments = {segments_json};
    const duration  = {duration};

    // ── colour palette (≤4 named; overflow uses hash) ──────────────────────
    const PALETTE = ['#4a90e2','#e94e77','#f5a623','#7ed321'];
    function speakerColor(sp) {{
      const m = sp.match(/_(\\d+)$/);
      if (m) {{
        const idx = parseInt(m[1], 10);
        if (idx < PALETTE.length) return PALETTE[idx];
      }}
      // hash fallback
      let h = 0;
      for (const c of sp) h = (h * 31 + c.charCodeAt(0)) & 0xffff;
      return `hsl(${{h % 360}}, 70%, 55%)`;
    }}

    // ── build speaker → colour map ─────────────────────────────────────────
    const speakers = [...new Set(segments.map(s => s.speaker))].sort();
    const colorMap  = Object.fromEntries(speakers.map(sp => [sp, speakerColor(sp)]));

    // ── render timeline segments ──────────────────────────────────────────
    const timeline = document.getElementById('timeline');
    segments.forEach(seg => {{
      const bar = document.createElement('div');
      bar.className = 'segment';
      bar.style.background = colorMap[seg.speaker];
      bar.style.left  = `${{(seg.start / duration) * 100}}%`;
      bar.style.width = `${{((seg.end - seg.start) / duration) * 100}}%`;
      bar.title = `${{seg.speaker}}  ${{seg.start.toFixed(2)}}s – ${{seg.end.toFixed(2)}}s`;
      bar.addEventListener('click', e => {{
        e.stopPropagation();
        player.currentTime = seg.start;
        player.play();
      }});
      timeline.appendChild(bar);
    }});

    // cursor
    const cursor = document.createElement('div');
    cursor.className = 'cursor';
    timeline.appendChild(cursor);

    // click on empty timeline area → seek
    timeline.addEventListener('click', e => {{
      const rect = timeline.getBoundingClientRect();
      player.currentTime = ((e.clientX - rect.left) / rect.width) * duration;
      player.play();
    }});

    // ── time axis labels ──────────────────────────────────────────────────
    const labelWrap = document.getElementById('timeLabels');
    const step = duration <= 60 ? 10 : duration <= 300 ? 30 : 60;
    for (let t = 0; t <= duration; t += step) {{
      const lbl = document.createElement('div');
      lbl.className = 'time-label';
      lbl.style.left = `${{(t / duration) * 100}}%`;
      const m = Math.floor(t / 60), s = Math.floor(t % 60);
      lbl.textContent = `${{m}}:${{String(s).padStart(2,'0')}}`;
      labelWrap.appendChild(lbl);
    }}

    // ── playback tracker ─────────────────────────────────────────────────
    const player    = document.getElementById('player');
    const infoEl    = document.getElementById('currentSpeaker');
    player.addEventListener('timeupdate', () => {{
      const t = player.currentTime;
      cursor.style.left = `${{(t / duration) * 100}}%`;
      const cur = segments.find(s => s.start <= t && t < s.end);
      infoEl.textContent = cur
        ? `현재 화자: ${{cur.speaker}}  (${{t.toFixed(2)}}s)`
        : `현재 화자: —  (${{t.toFixed(2)}}s)`;
    }});

    // ── legend ────────────────────────────────────────────────────────────
    const legendEl = document.getElementById('legend');
    speakers.forEach(sp => {{
      const el = document.createElement('div');
      el.className = 'legend-item';
      el.style.background = colorMap[sp];
      el.style.color = '#fff';
      el.textContent = sp;
      legendEl.appendChild(el);
    }});
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def parse_rttm(rttm_path: Path) -> list[dict]:
    """Parse RTTM file → list of {start, end, speaker} dicts."""
    segments: list[dict] = []
    for line in rttm_path.read_text().splitlines():
        line = line.strip()
        if not line or not line.startswith("SPEAKER"):
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        t_start = float(parts[3])
        t_dur = float(parts[4])
        speaker = parts[7]
        segments.append({"start": t_start, "end": t_start + t_dur, "speaker": speaker})
    segments.sort(key=lambda s: s["start"])
    return segments


def get_audio_duration(audio_path: Path) -> float:
    """Return audio duration in seconds using soundfile."""
    try:
        import soundfile as sf  # already in project deps
        return sf.info(str(audio_path)).duration
    except Exception:
        # fallback: estimate from file size (rough, PCM 16kHz mono 16-bit)
        size_bytes = audio_path.stat().st_size - 44  # strip WAV header
        return max(1.0, size_bytes / (16000 * 2))


def render_html(audio_path: Path, rttm_path: Path, output_path: Path) -> None:
    duration = get_audio_duration(audio_path)
    segments = parse_rttm(rttm_path)
    html = _HTML_TEMPLATE.format(
        title=audio_path.name,
        audio_src=audio_path.name,   # relative — viewer and audio in same dir
        duration=f"{duration:.3f}",
        segments_json=json.dumps(segments, ensure_ascii=False),
    )
    output_path.write_text(html, encoding="utf-8")
    n_seg = len(segments)
    speakers = sorted({s["speaker"] for s in segments})
    print(
        f"  → {output_path.name}  ({n_seg} segments, {len(speakers)} speakers: "
        f"{', '.join(speakers)}, duration={duration:.1f}s)"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate self-contained HTML RTTM viewer"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dir",
        type=Path,
        metavar="DIR",
        help="Directory — process every .wav/.rttm pair",
    )
    group.add_argument(
        "--audio",
        type=Path,
        metavar="WAV",
        help="Single audio file",
    )
    parser.add_argument(
        "--rttm",
        type=Path,
        metavar="RTTM",
        help="RTTM file (required with --audio)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="HTML",
        help="Output HTML path (default: <audio_stem>_viewer.html beside audio)",
    )
    args = parser.parse_args()

    if args.dir:
        base = args.dir
        pairs: list[tuple[Path, Path, Path]] = []
        for wav in sorted(base.glob("*.wav")):
            rttm = wav.with_suffix(".rttm")
            if rttm.exists():
                out = wav.parent / (wav.stem + "_viewer.html")
                pairs.append((wav, rttm, out))
        if not pairs:
            parser.error(f"No .wav/.rttm pairs found in {base}")
        print(f"Generating {len(pairs)} viewer(s) …")
        for wav, rttm, out in pairs:
            render_html(wav, rttm, out)
    else:
        if args.rttm is None:
            parser.error("--rttm is required with --audio")
        out = args.output or (
            args.audio.parent / (args.audio.stem + "_viewer.html")
        )
        render_html(args.audio, args.rttm, out)

    print("Done.")


if __name__ == "__main__":
    main()
