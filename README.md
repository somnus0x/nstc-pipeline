# YouTube Shorts Pipeline

End-to-end pipeline for generating, uploading, and tracking YouTube Shorts — built entirely with Claude Code.

Originally created for [Nostalgic for Things to Come](https://youtube.com/playlist?list=PL2PeLi-e1H_PhBhPPWLrEzO3sp3pb2W3H), a lofi channel where music is made on train rides and everything else is automated.

## What it does

1. **`generate-shorts.py`** — Takes audio files + video loops, generates vertical 1080x1920 Shorts with animated waveforms, text overlays, and branded visuals using ffmpeg + librosa + Pillow
2. **`youtube-upload.py`** — Uploads Shorts to YouTube as private with scheduled publish times (OAuth2, resumable uploads)
3. **`fetch-youtube-analytics.py`** — Pulls channel stats, per-video performance, traffic sources, and flags concerns (high swipe-away rates, declining views)
4. **`youtube-auth.py`** — Two-step OAuth2 setup for headless servers

## Pipeline flow

```
Suno (make music) → audio/*.mp3
                          ↓
              generate-shorts.py
              (librosa STFT → waveform frames)
              (ffmpeg composite → 1080x1920 MP4)
                          ↓
              youtube-upload.py
              (OAuth2 → private + scheduled publish)
                          ↓
              fetch-youtube-analytics.py
              (views, retention, swipe-away → JSON)
                          ↓
              Analyze → adjust layout → repeat
```

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt
apt install ffmpeg  # or brew install ffmpeg

# 2. Configure YouTube API
cp .env.example .env
# Add your YouTube OAuth client ID and secret from Google Cloud Console
# Required APIs: YouTube Data API v3, YouTube Analytics API

# 3. Authenticate
python3 youtube-auth.py url    # Opens auth URL
python3 youtube-auth.py code YOUR_CODE  # Saves token

# 4. Prepare your data
mkdir -p audio art fonts
# Put your audio files in audio/
# Put your video loops in art/
# Put your fonts in fonts/
```

## Directory structure

```
├── audio/              # Source audio files (.mp3)
├── art/                # Background video loops (.mp4, ~5 sec each)
│   └── channel-pfp.png # Channel profile picture for watermark
├── fonts/              # Typography (TTF files)
├── shorts/             # Generated output (MP4 + JSON metadata)
├── catalog.json        # Video catalog (titles, URLs, chapters)
├── track-analysis.json # Peak segment analysis per track
├── shorts-schedule.json# Upload schedule (dates, slots, phases)
└── youtube-token.json  # OAuth token (auto-generated, gitignored)
```

## Usage

```bash
# Generate Shorts for a specific phase
python3 generate-shorts.py --phase 1

# Generate all Shorts
python3 generate-shorts.py --all

# With handwriting animation titles (requires playwright)
python3 generate-shorts.py --all --tegaki

# Upload (dry run first)
python3 youtube-upload.py --dry-run --phase 1
python3 youtube-upload.py --phase 1

# Fetch analytics
python3 fetch-youtube-analytics.py
```

## Customization

### Colors
Edit the brand color constants in `generate-shorts.py`:
```python
CREAM_CENTER = (255, 240, 220)  # Waveform bar color (center)
CREAM_EDGE = (240, 200, 170)    # Waveform bar color (edges)
TEXT_PRIMARY = (235, 225, 210)   # Title text
```

### Waveform
```python
BAR_COUNT = 50          # Number of frequency bars
WAVEFORM_HEIGHT = 100   # Max bar height in pixels
WAVEFORM_Y_CENTER = 1490  # Vertical position
WAVEFORM_IDLE_MIN = 0.15  # Minimum bar height (idle breathing)
```

### Scheduling slots
Upload slots map to Bangkok time (UTC+7). Edit `slot_to_publish_time()` for your timezone:
```python
slot_hours = {"AM": 10, "PM": 16, "EVE": 20}
```

## Data files

### `track-analysis.json`
Peak segment analysis for each track. The generator picks the highest-scored 10-second clip:
```json
{
  "track-slug": {
    "clips": [
      {"start": 45.0, "end": 55.0, "score": 0.87, "start_fmt": "0:45", "end_fmt": "0:55"}
    ]
  }
}
```

### `shorts-schedule.json`
Defines phases with dates, slots, and track assignments:
```json
{
  "total_shorts": 43,
  "phases": [
    {
      "name": "Phase 1",
      "dates": "Apr 16-17",
      "shorts": [
        {"track": "Empty Train Home", "source": "Single", "type": "catalog", "date": "2026-04-16", "slot": "AM"}
      ]
    }
  ]
}
```

## What I learned from 500 views

- Evocative names outperform abstract ones ("After the Last Train" > "Neon Sleepwalk")
- Moving text overlay from bottom to top improved watch-through
- 150 views is the algorithm's audition cap — swipe-away rate under 70% is the gate

## Dependencies

- Python 3.10+
- ffmpeg (with libx264 + aac)
- librosa, numpy, Pillow
- Google API client libraries
- Playwright (optional, for tegaki handwriting animation)

## License

MIT
