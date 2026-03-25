#!/usr/bin/env python3
"""
Dead Air Detector for Adobe Premiere Pro
Analyzes audio files and outputs JSON timecodes of content regions (non-silent).

Usage:
    python detect_silence.py <audio_or_video_file> [options]

Output:
    Writes a JSON file with keep/cut regions to the same directory as input.

Requirements:
    pip install librosa soundfile numpy
    ffmpeg must be on PATH (for extracting audio from video files)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import librosa
import numpy as np


def extract_audio(input_path: str, sr: int = 22050) -> tuple[np.ndarray, int]:
    """
    Load audio from any file ffmpeg can read.
    Returns (samples, sample_rate).
    """
    ext = Path(input_path).suffix.lower()
    audio_exts = {".wav", ".mp3", ".flac", ".ogg", ".aac", ".m4a"}

    if ext in audio_exts:
        y, sr_out = librosa.load(input_path, sr=sr, mono=True)
        return y, sr_out

    # Video file — extract audio to a temp wav first
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", input_path,
                "-vn", "-acodec", "pcm_s16le",
                "-ar", str(sr), "-ac", "1",
                tmp.name,
            ],
            check=True,
            capture_output=True,
        )
        y, sr_out = librosa.load(tmp.name, sr=sr, mono=True)
        return y, sr_out
    finally:
        os.unlink(tmp.name)


def detect_content_regions(
    y: np.ndarray,
    sr: int,
    silence_thresh_db: float = -40.0,
    min_silence_dur: float = 0.75,
    min_content_dur: float = 0.15,
    pad_seconds: float = 0.05,
) -> list[dict]:
    """
    Detect regions of audio that contain content (non-silence).

    Args:
        y:                Audio samples (mono).
        sr:               Sample rate.
        silence_thresh_db: RMS power below this (in dB) = silence. Default -40 dB.
        min_silence_dur:  Minimum silence duration (seconds) to count as a gap.
        min_content_dur:  Minimum content duration (seconds) to keep.
        pad_seconds:      Padding added before/after each content region.

    Returns:
        List of dicts: {"start": float, "end": float} in seconds.
    """
    frame_length = 2048
    hop_length = 512
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]

    # Convert threshold from dB to linear
    silence_thresh_linear = librosa.db_to_power(silence_thresh_db)

    # Boolean mask: True = content frame
    is_content = rms > silence_thresh_linear

    # Convert frame indices to time
    times = librosa.frames_to_time(
        np.arange(len(rms)), sr=sr, hop_length=hop_length
    )
    duration = len(y) / sr

    # Find contiguous content regions
    regions = []
    in_content = False
    start = 0.0

    for i, (t, c) in enumerate(zip(times, is_content)):
        if c and not in_content:
            start = t
            in_content = True
        elif not c and in_content:
            regions.append({"start": start, "end": t})
            in_content = False

    if in_content:
        regions.append({"start": start, "end": duration})

    # Merge regions separated by less than min_silence_dur
    merged = []
    for r in regions:
        if merged and (r["start"] - merged[-1]["end"]) < min_silence_dur:
            merged[-1]["end"] = r["end"]
        else:
            merged.append(dict(r))

    # Filter out tiny content regions
    merged = [r for r in merged if (r["end"] - r["start"]) >= min_content_dur]

    # Apply padding (clamped to file bounds)
    for r in merged:
        r["start"] = max(0.0, r["start"] - pad_seconds)
        r["end"] = min(duration, r["end"] + pad_seconds)

    # Re-merge any overlapping regions after padding
    final = []
    for r in merged:
        if final and r["start"] <= final[-1]["end"]:
            final[-1]["end"] = r["end"]
        else:
            final.append(dict(r))

    return final


def seconds_to_timecode(seconds: float, fps: float = 29.97) -> str:
    """Convert seconds to HH:MM:SS:FF timecode string."""
    total_frames = int(round(seconds * fps))
    ff = total_frames % int(round(fps))
    total_seconds = total_frames // int(round(fps))
    ss = total_seconds % 60
    total_minutes = total_seconds // 60
    mm = total_minutes % 60
    hh = total_minutes // 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def main():
    parser = argparse.ArgumentParser(
        description="Detect dead air in audio/video and output JSON cut list."
    )
    parser.add_argument("input", help="Path to audio or video file")
    parser.add_argument(
        "-t", "--threshold", type=float, default=-40.0,
        help="Silence threshold in dB (default: -40). Raise toward 0 to be more aggressive."
    )
    parser.add_argument(
        "-s", "--min-silence", type=float, default=0.75,
        help="Minimum silence duration in seconds to cut (default: 0.75)"
    )
    parser.add_argument(
        "-c", "--min-content", type=float, default=0.15,
        help="Minimum content duration in seconds to keep (default: 0.15)"
    )
    parser.add_argument(
        "-p", "--pad", type=float, default=0.05,
        help="Padding in seconds around each content region (default: 0.05)"
    )
    parser.add_argument(
        "--fps", type=float, default=29.97,
        help="Timeline frame rate for timecode output (default: 29.97)"
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="Output JSON path (default: <input_name>_cuts.json in same directory)"
    )

    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    if not os.path.isfile(input_path):
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading audio from: {input_path}")
    y, sr = extract_audio(input_path)
    duration = len(y) / sr
    print(f"  Duration: {duration:.2f}s | Sample rate: {sr} Hz")

    print(f"Detecting content (threshold={args.threshold} dB, min_silence={args.min_silence}s)...")
    regions = detect_content_regions(
        y, sr,
        silence_thresh_db=args.threshold,
        min_silence_dur=args.min_silence,
        min_content_dur=args.min_content,
        pad_seconds=args.pad,
    )

    # Compute silence regions (inverse of content)
    silence_regions = []
    prev_end = 0.0
    for r in regions:
        if r["start"] > prev_end:
            silence_regions.append({"start": prev_end, "end": r["start"]})
        prev_end = r["end"]
    if prev_end < duration:
        silence_regions.append({"start": prev_end, "end": duration})

    total_content = sum(r["end"] - r["start"] for r in regions)
    total_silence = duration - total_content

    output = {
        "source_file": input_path,
        "duration": round(duration, 4),
        "fps": args.fps,
        "settings": {
            "threshold_db": args.threshold,
            "min_silence_sec": args.min_silence,
            "min_content_sec": args.min_content,
            "pad_sec": args.pad,
        },
        "summary": {
            "content_regions": len(regions),
            "total_content_sec": round(total_content, 4),
            "total_silence_sec": round(total_silence, 4),
            "percent_removed": round(100 * total_silence / duration, 1) if duration > 0 else 0,
        },
        "keep_regions": [
            {
                "index": i,
                "start_sec": round(r["start"], 4),
                "end_sec": round(r["end"], 4),
                "start_tc": seconds_to_timecode(r["start"], args.fps),
                "end_tc": seconds_to_timecode(r["end"], args.fps),
                "duration_sec": round(r["end"] - r["start"], 4),
            }
            for i, r in enumerate(regions)
        ],
        "silence_regions": [
            {
                "start_sec": round(r["start"], 4),
                "end_sec": round(r["end"], 4),
                "duration_sec": round(r["end"] - r["start"], 4),
            }
            for r in silence_regions
        ],
    }

    if args.output:
        out_path = args.output
    else:
        stem = Path(input_path).stem
        out_path = str(Path(input_path).parent / f"{stem}_cuts.json")

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults:")
    print(f"  Content regions: {len(regions)}")
    print(f"  Content:  {total_content:.1f}s")
    print(f"  Silence:  {total_silence:.1f}s ({output['summary']['percent_removed']}% removed)")
    print(f"  Output:   {out_path}")


if __name__ == "__main__":
    main()
