# Premiere Pro Dead Air Cutter

Two-part tool that detects silence in audio and removes it from your Premiere Pro timeline.

## Architecture

```
┌──────────────┐      JSON       ┌──────────────────┐
│  Python      │  ────────────>  │  ExtendScript     │
│  detect_     │  keep_regions   │  apply_cuts.jsx   │
│  silence.py  │  + timecodes    │  (runs in PPro)   │
└──────────────┘                 └──────────────────┘
     │                                  │
     ▼                                  ▼
 Analyzes audio                  Removes original clip,
 via librosa RMS                 re-inserts sub-clips
 energy detection                for content-only regions
```

**Why two parts?** Premiere's scripting API has no access to audio sample data. Silence detection must happen externally; the script then manipulates timeline clips using the results.

---

## Setup

### Python (one time)
```bash
pip install librosa soundfile numpy
```
ffmpeg must be on your PATH (for video file audio extraction).

### Premiere Pro
No installation needed. The .jsx runs directly via `File > Scripts > Run Script File...`

---

## Usage

### Step 1: Detect silence
```bash
python detect_silence.py /path/to/your/recording.wav
```

This creates `recording_cuts.json` in the same directory.

### Step 2: Review the JSON (optional)
Open the JSON to inspect detected regions. Key fields:
- `keep_regions`: array of content segments with start/end timecodes
- `silence_regions`: array of gaps that will be removed
- `summary.percent_removed`: how much dead air was found

### Step 3: Apply in Premiere Pro
1. Open your project and sequence
2. Make sure the clip is on V1 / A1 (or edit `targetVideoTrack` / `targetAudioTrack` in the .jsx)
3. `File > Scripts > Run Script File...` → select `apply_cuts.jsx`
4. Select your `_cuts.json` when prompted
5. Confirm the operation

---

## Tuning Parameters

| Flag | Default | Effect |
|------|---------|--------|
| `-t` / `--threshold` | -40 dB | RMS level below which audio = silence. Raise toward 0 to cut more aggressively. -30 is good for noisy rooms. |
| `-s` / `--min-silence` | 0.75s | Gaps shorter than this are kept (natural breath pauses). Lower to 0.3 for fast-paced cuts. |
| `-c` / `--min-content` | 0.15s | Content regions shorter than this are discarded (clicks, pops). |
| `-p` / `--pad` | 0.05s | Padding added before/after each content region to prevent clipped words. Increase to 0.1–0.2 for safety. |
| `--fps` | 29.97 | Timeline frame rate (for timecode display only; cuts use seconds). |

### Examples
```bash
# Aggressive cut for a talking-head video in a quiet room
python detect_silence.py video.mp4 -t -45 -s 0.5 -p 0.08

# Conservative cut preserving natural pauses
python detect_silence.py interview.wav -t -35 -s 1.5 -p 0.15

# Podcast with background noise
python detect_silence.py podcast.mp3 -t -30 -s 0.75 -p 0.1
```

---

## Known Limitations

1. **Effects don't transfer.** The .jsx removes the original clip and inserts new sub-clips. Any effects, keyframes, or audio adjustments on the original clip are lost. Apply effects *after* running the cutter, or use adjustment layers.

2. **Single clip per track.** The script operates on the first clip of the target tracks. For multi-clip timelines, select which clip to process by adjusting the track indices in the .jsx, or split your work into per-clip sequences.

3. **No undo granularity.** Premiere treats the entire script execution as one undo step. `Ctrl+Z` will revert all changes at once.

4. **overwriteClip behavior.** The ExtendScript `overwriteClip` method places content at the specified time. If other clips exist on the track, they may be overwritten. Run this on a clean track or duplicate your sequence first.

5. **Linked audio/video.** If your clip has linked A/V, the script handles V1 insertion (which auto-places linked audio). For unlinked or audio-only clips, it falls back to audio track insertion.

---

## Troubleshooting

**"No active sequence"** — Open a sequence in Premiere before running the script.

**Cuts sound choppy** — Increase `--pad` to 0.1 or 0.15 to add more breathing room around content edges.

**Too much silence left** — Raise `--threshold` (e.g., -35 or -30) and/or lower `--min-silence` (e.g., 0.4).

**Content is getting cut** — Lower `--threshold` (e.g., -45 or -50) and/or raise `--min-content`.

**JSON file not recognized** — Make sure you're selecting the `_cuts.json` file, not the source media.
