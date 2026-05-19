#!/usr/bin/env python3
"""
AMI Meeting Corpus 1 session 다운로드 + RTTM ground truth 확보.

사용법:
    export HF_TOKEN=<token>
    pip install pyarrow  # 다운로드 도구 (speaker_engine 런타임 의존성 X)
    python scripts/download_ami.py [--session ES2002a] [--out tests/data/ami/]

출력:
    {out}/{session}/audio.wav         -- 16kHz mono PCM
    {out}/{session}/reference.rttm    -- pyannote.metrics 가 읽는 ground truth

소스:
    audio + timestamps: diarizers-community/ami HuggingFace 데이터셋 (IHM configuration)
    RTTM 은 timestamps_start / timestamps_end / speakers 컬럼에서 생성

사전 조건:
    pip install pyarrow  (parquet 읽기 도구)
    HF_TOKEN 환경변수 (diarizers-community/ami 는 공개 데이터셋이라 토큰 불필요하지만
    다운로드 속도 향상을 위해 설정 권장)

참고:
    - ES2002a 는 diarizers-community/ami 의 train split 에 포함 (pyannote test split 과 다름)
    - 4 화자 (FEE005, MEE006, MEE007, MEE008), ~21분 활성 발화, ~1272초 총 길이
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


# (session, parquet_index, row_index) — IHM train split 위치
# 신규 session 추가 시 해당 parquet 와 row 를 사전 확인 필요
_SESSION_LOC: dict[str, tuple[str, int, int]] = {
    "ES2002a": ("train", 8, 5),
    # 필요시 다른 session 추가
}


def _check_pyarrow() -> None:
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        print("ERROR: pyarrow 가 필요합니다. 설치: pip install pyarrow", file=sys.stderr)
        sys.exit(1)


def _find_session_in_split(
    repo_id: str, split: str, session: str, hf_token: str
) -> tuple[str, int, int] | None:
    """split 전체 parquet 를 순서대로 스캔해서 session 위치 반환. 느릴 수 있음."""
    import huggingface_hub as hf
    import pyarrow.parquet as pq

    n_shards = {"train": 19, "validation": 3, "test": 3}
    total = n_shards.get(split, 3)
    for i in range(total):
        fname = f"ihm/{split}-{i:05d}-of-{total:05d}.parquet"
        try:
            p = hf.hf_hub_download(repo_id=repo_id, repo_type="dataset", filename=fname, token=hf_token or None)
        except Exception:
            continue
        table = pq.read_table(p, columns=["audio"])
        for j in range(len(table)):
            path = table[0][j].as_py().get("path", "")
            if session.lower() in path.lower():
                return fname, i, j
    return None


def _download_from_parquet(
    session: str, out_dir: Path, hf_token: str,
    parquet_idx: int, row_idx: int, split: str
) -> None:
    """diarizers-community/ami parquet 에서 audio + RTTM 추출."""
    import huggingface_hub as hf
    import pyarrow.parquet as pq
    import torchaudio
    import io

    total = {"train": 19, "validation": 3, "test": 3}[split]
    fname = f"ihm/{split}-{parquet_idx:05d}-of-{total:05d}.parquet"
    print(f"[download_ami] parquet 다운로드: diarizers-community/ami / {fname}")
    p = hf.hf_hub_download(
        repo_id="diarizers-community/ami",
        repo_type="dataset",
        filename=fname,
        token=hf_token or None,
    )

    table = pq.read_table(p)
    row = table.slice(row_idx, 1)

    audio_struct = row.column("audio")[0].as_py()
    ts_start = row.column("timestamps_start")[0].as_py()
    ts_end = row.column("timestamps_end")[0].as_py()
    speakers = row.column("speakers")[0].as_py()

    print(f"[download_ami] session={session}  segments={len(ts_start)}  speakers={set(speakers)}")

    # --- audio: bytes → torchaudio → 16kHz mono WAV ---
    wav_path = out_dir / "audio.wav"
    raw_bytes = audio_struct["bytes"]
    waveform, sr = torchaudio.load(io.BytesIO(raw_bytes))
    if sr != 16_000:
        resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=16_000)
        waveform = resampler(waveform)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    torchaudio.save(str(wav_path), waveform, 16_000)
    dur = waveform.shape[1] / 16_000
    print(f"[download_ami] audio.wav 저장: {wav_path} ({dur:.1f}s, {wav_path.stat().st_size // 1024}KB)")

    # --- RTTM 생성 ---
    rttm_path = out_dir / "reference.rttm"
    with open(rttm_path, "w") as f:
        for s, e, spk in zip(ts_start, ts_end, speakers):
            dur_seg = e - s
            if dur_seg > 0:
                f.write(f"SPEAKER {session} 1 {s:.3f} {dur_seg:.3f} <NA> <NA> {spk} <NA> <NA>\n")
    print(f"[download_ami] reference.rttm 저장: {rttm_path} ({len(ts_start)} segments)")


def main() -> None:
    parser = argparse.ArgumentParser(description="AMI 1 session 다운로드 (diarizers-community/ami 소스)")
    parser.add_argument("--session", default="ES2002a", help="AMI session ID (default: ES2002a)")
    parser.add_argument("--out", default="tests/data/ami/", help="출력 디렉토리 (default: tests/data/ami/)")
    parser.add_argument("--split", default=None, help="HF split (train/validation/test). None 이면 자동 탐색")
    parser.add_argument("--parquet-idx", type=int, default=None, help="parquet shard 인덱스 (자동 탐색 불필요 시)")
    parser.add_argument("--row-idx", type=int, default=None, help="parquet row 인덱스 (자동 탐색 불필요 시)")
    args = parser.parse_args()

    _check_pyarrow()
    hf_token = os.environ.get("HF_TOKEN", "")

    session = args.session
    out_dir = Path(args.out) / session
    out_dir.mkdir(parents=True, exist_ok=True)

    # 이미 존재하면 스킵
    if (out_dir / "audio.wav").exists() and (out_dir / "reference.rttm").exists():
        print(f"[download_ami] 이미 존재 — 스킵: {out_dir}")
        return

    # parquet 위치 결정
    if args.split and args.parquet_idx is not None and args.row_idx is not None:
        split, parquet_idx, row_idx = args.split, args.parquet_idx, args.row_idx
    elif session in _SESSION_LOC:
        split, parquet_idx, row_idx = _SESSION_LOC[session]
        print(f"[download_ami] 사전 매핑 사용: {session} → {split}[{parquet_idx},{row_idx}]")
    else:
        print(f"[download_ami] {session} 위치 자동 탐색 중 (느릴 수 있음)...")
        result = _find_session_in_split("diarizers-community/ami", "train", session, hf_token)
        if result is None:
            result = _find_session_in_split("diarizers-community/ami", "test", session, hf_token)
        if result is None:
            print(f"ERROR: {session} 을 diarizers-community/ami 에서 찾지 못했습니다.", file=sys.stderr)
            sys.exit(1)
        fname, parquet_idx, row_idx = result
        split = fname.split("/")[1].split("-")[0]

    _download_from_parquet(session, out_dir, hf_token, parquet_idx, row_idx, split)

    print(f"\n[download_ami] 완료!")
    print(f"  audio.wav    : {out_dir / 'audio.wav'}")
    print(f"  reference.rttm: {out_dir / 'reference.rttm'}")


if __name__ == "__main__":
    main()
