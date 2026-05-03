# YouTube Shorts Pipeline

Free, open-source pipeline for generating, uploading, and tracking YouTube Shorts — built entirely with Claude Code. No paid tools required beyond the music generation.

Originally created for [Nostalgic for Things to Come](https://youtube.com/playlist?list=PL2PeLi-e1H_PhBhPPWLrEzO3sp3pb2W3H), a lofi channel where music is made on train rides and everything else is automated.

**This is free. It will always be free.**

## What it does

1. **`generate-shorts.py`** — Takes audio files + video loops, generates vertical 1080x1920 Shorts with animated waveforms, text overlays, and branded visuals using ffmpeg + librosa + Pillow
2. **`youtube-upload.py`** — Uploads Shorts to YouTube as private with scheduled publish times (OAuth2, resumable uploads)
3. **`fetch-youtube-analytics.py`** — Pulls channel stats, per-video performance, traffic sources, and flags concerns (high swipe-away rates, declining views)
4. **`youtube-auth.py`** — Two-step OAuth2 setup for headless servers

## Full pipeline — from zero to YouTube channel

### Step 1: Make music with Suno

[Suno](https://suno.com) generates full tracks from text prompts. Free tier gives you 50 credits/day (about 10 songs).

```
Prompt examples:
- "lofi hip hop, late night study vibes, vinyl crackle, warm piano"
- "chill beats, rainy city, muted trumpet, lo-fi drum machine"
- "ambient lofi, train station at midnight, soft Rhodes piano"
```

Tips:
- Extend tracks to 2-4 minutes for mixtape-length content
- Download as MP3, rename to a slug: `empty-train-home.mp3`, `neon-sleepwalk.mp3`
- Drop all audio files into `audio/`

### Step 2: Create video loops with Midjourney + Runway

Your Shorts need a background video. Here's the workflow:

**Midjourney (image)**
```
Prompt: "lofi anime style, empty train car at night, warm light through windows,
        soft grain, studio ghibli color palette, 16:9 --ar 9:16 --v 6"
```

- Generate 9:16 vertical images that match your track mood
- Download the upscaled version

**Runway Gen-3 (image → video)**
- Upload your Midjourney image to [Runway](https://runwayml.com)
- Use "Image to Video" with Gen-3 Alpha Turbo
- Set duration to 5 seconds (the pipeline loops it automatically)
- Subtle motion works best: rain, floating particles, gentle camera drift
- Download as MP4, save to `art/track-slug.mp4`

**Free alternatives:**
- [Pika](https://pika.art) — free tier, image-to-video
- [Kling](https://klingai.com) — generous free credits
- [LumaLabs Dream Machine](https://lumalabs.ai) — free tier available
- Static image fallback — the pipeline works with still images too (just won't have motion)

### Step 3: Set up the pipeline

```bash
# Install dependencies
pip install -r requirements.txt
apt install ffmpeg  # or brew install ffmpeg

# Configure YouTube API
cp .env.example .env
# Add your YouTube OAuth client ID and secret from Google Cloud Console
# Required APIs: YouTube Data API v3, YouTube Analytics API

# Authenticate
python3 youtube-auth.py url    # Opens auth URL
python3 youtube-auth.py code YOUR_CODE  # Saves token

# Prepare your data
mkdir -p audio art fonts shorts
# audio/ — your Suno MP3s
# art/ — your Midjourney+Runway video loops (5 sec MP4s)
# art/channel-pfp.png — your channel profile picture
# fonts/ — TTF files for text overlays
```

### Step 4: Configure your content

Create three JSON files:

**`track-analysis.json`** — Peak segments per track (which 10 seconds to use for the Short):
```json
{
  "empty-train-home": {
    "clips": [
      {"start": 45.0, "end": 55.0, "score": 0.87, "start_fmt": "0:45", "end_fmt": "0:55"}
    ]
  }
}
```
Tip: Listen to each track, find the best 10-second moment, note the timestamp.

**`shorts-schedule.json`** — Upload schedule:
```json
{
  "total_shorts": 5,
  "phases": [
    {
      "name": "Phase 1",
      "dates": "Week 1",
      "note": "First batch",
      "shorts": [
        {"track": "Empty Train Home", "source": "Single", "type": "catalog", "date": "2026-05-10", "slot": "AM"}
      ]
    }
  ]
}
```

**`catalog.json`** — Video metadata:
```json
{
  "videos": [
    {
      "type": "single",
      "title": "NSTC — Empty Train Home",
      "chapter": "",
      "description": "Late night lofi for the ones still awake.",
      "url": "https://youtube.com/watch?v=xxx"
    }
  ]
}
```

### Step 5: Generate, upload, track

```bash
# Generate Shorts
python3 generate-shorts.py --phase 1

# Preview upload without actually uploading
python3 youtube-upload.py --dry-run --phase 1

# Upload for real (private + scheduled)
python3 youtube-upload.py --phase 1

# Check how they're doing
python3 fetch-youtube-analytics.py
```

## Pipeline flow

```
Suno (make music on train)
    ↓
audio/*.mp3

Midjourney + Runway (create video loops)
    ↓
art/*.mp4

    ↓ ↓ ↓

generate-shorts.py
├── librosa STFT → animated waveform frames
├── Pillow → text overlay + PFP watermark
└── ffmpeg → composite 1080x1920 MP4

    ↓

youtube-upload.py
└── OAuth2 → private + scheduled publish

    ↓

fetch-youtube-analytics.py
└── views, retention, swipe-away → JSON

    ↓

Analyze → adjust layout → repeat
```

## Directory structure

```
├── audio/              # Source audio files (.mp3) from Suno
├── art/                # Background video loops (.mp4, ~5 sec) from MJ+Runway
│   └── channel-pfp.png # Channel profile picture for watermark
├── fonts/              # Typography (TTF files)
├── shorts/             # Generated output (MP4 + JSON metadata)
├── catalog.json        # Video catalog (titles, URLs, chapters)
├── track-analysis.json # Peak segment analysis per track
├── shorts-schedule.json# Upload schedule (dates, slots, phases)
└── youtube-token.json  # OAuth token (auto-generated, gitignored)
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

## What I learned from 500 views

- Evocative names outperform abstract ones ("After the Last Train" > "Neon Sleepwalk")
- Moving text overlay from bottom to top improved watch-through
- 150 views is the algorithm's audition cap — swipe-away rate under 70% is the gate
- You don't need a million views to learn from data. You need a pipeline that collects it.

## Dependencies

- Python 3.10+
- ffmpeg (with libx264 + aac)
- librosa, numpy, Pillow
- Google API client libraries
- Playwright (optional, for tegaki handwriting animation)

## Cost

- **Suno**: Free tier (50 credits/day) or $10/mo for Pro
- **Midjourney**: $10/mo (or use free alternatives like Pika/Kling)
- **Runway**: Free tier available (or use free alternatives)
- **YouTube API**: Free
- **This pipeline**: Free, forever

Everything except Suno has a free path. Total cost to run a channel: $0-20/mo.

## License

MIT
