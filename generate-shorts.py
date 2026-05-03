#!/usr/bin/env python3
"""
YouTube Shorts Generator
Generates 1080x1920 vertical Shorts with animated waveforms and branded overlays.

Usage:
  python3 generate-shorts.py --phase 1        # Generate specific phase
  python3 generate-shorts.py --all            # Generate all Shorts
  python3 generate-shorts.py --all --tegaki   # Use handwriting animation for titles
"""

import argparse
import asyncio
import functools
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote

import librosa
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Paths — configure these for your setup
BASE_DIR = Path(os.environ.get("NSTC_BASE_DIR", Path(__file__).parent))
AUDIO_DIR = BASE_DIR / "audio"
ART_DIR = BASE_DIR / "art"
FONTS_DIR = BASE_DIR / "fonts"
SHORTS_DIR = BASE_DIR / "shorts"
TRACK_ANALYSIS_FILE = BASE_DIR / "track-analysis.json"
SCHEDULE_FILE = BASE_DIR / "shorts-schedule.json"
CATALOG_FILE = BASE_DIR / "catalog.json"
CHANNEL_PFP = ART_DIR / "channel-pfp.png"
TEGAKI_TEMPLATE = BASE_DIR / "tegaki-template.html"
TEGAKI_MODULES = BASE_DIR / "tegaki_modules"

# Tegaki settings
TEGAKI_PORT = 8769
TEGAKI_VIEWPORT_HEIGHT = 120
TEGAKI_ANIM_SECONDS = 4  # Duration of handwriting animation
TEGAKI_TITLE_Y = 200  # Y position of tegaki title in final composite

# Output settings
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
FPS = 30
CLIP_DURATION = 10  # seconds

# Brand colors (cream palette — customize for your channel)
CREAM_CENTER = (255, 240, 220)
CREAM_EDGE = (240, 200, 170)
TEXT_PRIMARY = (235, 225, 210)
TEXT_SECONDARY = (185, 175, 160)
TEXT_TERTIARY = (145, 135, 122)
TEXT_QUATERNARY = (155, 145, 132)
SEPARATOR_COLOR = (110, 100, 90)
PFP_BORDER = (200, 190, 175, 120)

# Waveform settings
BAR_COUNT = 50
BAR_WIDTH = 8
BAR_GAP = 10
WAVEFORM_HEIGHT = 100  # Max bar height in pixels
WAVEFORM_Y_CENTER = 1490  # Center Y of waveform bars
WAVEFORM_IDLE_MIN = 0.15  # Minimum bar height as fraction (idle pulse floor)
WAVEFORM_IDLE_SPEED = 2.0  # Idle pulse oscillation speed (Hz)

# Title punch-in animation settings
PUNCH_IN_DURATION_FRAMES = 45  # 1.5 seconds at 30fps
PUNCH_IN_FONT_SIZE = 72
PUNCH_IN_Y = 350  # Top third of frame
PUNCH_IN_HOLD_FRAMES = 60  # Hold for 2 seconds after punch-in
PUNCH_IN_FADE_OUT_FRAMES = 20  # Fade out over ~0.67 seconds

# Text overlay settings
TEXT_AREA_Y_START = 1920 - 680
TEXT_TITLE_SIZE = 58
TEXT_CHAPTER_SIZE = 34
TEXT_TAGLINE_SIZE = 28
TEXT_LINK_SIZE = 24
SEPARATOR_WIDTH = 160
PFP_SIZE = 90
PFP_POSITION = (30, 30)
PFP_OPACITY = 0.85


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    return (text.lower()
            .replace(":", "")
            .replace(",", "")
            .replace("'", "")
            .replace(" ", "-"))


def chapter_to_video_slug(chapter: str) -> str:
    """
    Convert chapter name to video filename slug.
    E.g., "Vol. 1: After the Last Train" -> "vol1-after-the-last-train"
    """
    if chapter.startswith("Vol. "):
        rest = chapter[5:]
        if ":" in rest:
            vol_num, subtitle = rest.split(":", 1)
            vol_num = vol_num.strip()
            subtitle = subtitle.strip()
            if "," in subtitle:
                subtitle = subtitle.split(",")[0].strip()
            return f"vol{vol_num}-{slugify(subtitle)}"

    return slugify(chapter)


def find_video_source(track_name: str, source: str, catalog: dict) -> Optional[Path]:
    """Find the video file for a track."""
    slug = slugify(track_name)

    if source == "Single":
        video_path = ART_DIR / f"{slug}.mp4"
        return video_path if video_path.exists() else None

    for video in catalog["videos"]:
        if video["type"] == "mixtape" and source in video.get("chapter", ""):
            vol_slug = chapter_to_video_slug(video["chapter"])
            video_path = ART_DIR / f"{vol_slug}.mp4"
            return video_path if video_path.exists() else None

    return None


def extract_audio_clip(audio_file: Path, start: float, duration: float, output_file: Path) -> bool:
    """Extract audio clip using ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_file),
        "-ss", str(start),
        "-t", str(duration),
        "-q:a", "0",
        str(output_file)
    ]

    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR extracting audio: {e.stderr.decode()}")
        return False


def extract_video_clip(video_file: Path, start: float, duration: float, output_file: Path) -> bool:
    """Extract video clip and convert to vertical 1080x1920 format."""
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(video_file),
        "-t", str(duration),
        "-vf", "scale=-1:1920,crop=1080:1920:(iw-1080)/2:0",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-an",
        str(output_file)
    ]

    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR extracting video: {e.stderr.decode()}")
        return False


def generate_waveform_frames(audio_file: Path, output_dir: Path, total_frames: int) -> bool:
    """Generate animated waveform frames using librosa STFT analysis."""
    print(f"  Analyzing audio for waveform...")

    try:
        y, sr = librosa.load(str(audio_file), sr=22050, mono=True)
        D = librosa.stft(y, n_fft=2048, hop_length=512)
        magnitude = np.abs(D)

        hop_length = 512
        frames_per_video_frame = len(y) / total_frames / hop_length

        output_dir.mkdir(parents=True, exist_ok=True)

        for frame_idx in range(total_frames):
            img = Image.new("RGBA", (SHORTS_WIDTH, SHORTS_HEIGHT), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            audio_frame_idx = int(frame_idx * frames_per_video_frame)
            if audio_frame_idx >= magnitude.shape[1]:
                audio_frame_idx = magnitude.shape[1] - 1

            freq_bins = magnitude[:, audio_frame_idx]

            bin_size = len(freq_bins) // BAR_COUNT
            bars = []
            for i in range(BAR_COUNT):
                start_bin = i * bin_size
                end_bin = start_bin + bin_size
                bar_magnitude = np.mean(freq_bins[start_bin:end_bin])
                bars.append(bar_magnitude)

            max_bar = max(bars) if max(bars) > 0 else 1.0
            bars = [b / max_bar for b in bars]

            # Idle pulse: bars never flatline — gentle sine wave breathing
            time_sec = frame_idx / FPS
            for i in range(len(bars)):
                phase_offset = i * 0.15
                idle_pulse = WAVEFORM_IDLE_MIN * (0.6 + 0.4 * np.sin(
                    2 * np.pi * WAVEFORM_IDLE_SPEED * time_sec + phase_offset
                ))
                bars[i] = max(bars[i], idle_pulse)

            total_bar_width = BAR_COUNT * (BAR_WIDTH + BAR_GAP) - BAR_GAP
            x_start = (SHORTS_WIDTH - total_bar_width) // 2

            for i, bar_height_norm in enumerate(bars):
                bar_height = max(6, int(bar_height_norm * WAVEFORM_HEIGHT))

                distance_from_center = abs(i - BAR_COUNT / 2) / (BAR_COUNT / 2)
                r = int(CREAM_CENTER[0] * (1 - distance_from_center) + CREAM_EDGE[0] * distance_from_center)
                g = int(CREAM_CENTER[1] * (1 - distance_from_center) + CREAM_EDGE[1] * distance_from_center)
                b = int(CREAM_CENTER[2] * (1 - distance_from_center) + CREAM_EDGE[2] * distance_from_center)

                x = x_start + i * (BAR_WIDTH + BAR_GAP)
                y_top = WAVEFORM_Y_CENTER - bar_height // 2
                y_bottom = WAVEFORM_Y_CENTER + bar_height // 2

                draw.rounded_rectangle(
                    [(x, y_top), (x + BAR_WIDTH, y_bottom)],
                    radius=3,
                    fill=(r, g, b, 255)
                )

            frame_file = output_dir / f"frame_{frame_idx:04d}.png"
            img.save(frame_file)

            if frame_idx % 100 == 0:
                print(f"    Generated {frame_idx}/{total_frames} frames")

        print(f"  Generated {total_frames} waveform frames")
        return True

    except Exception as e:
        print(f"ERROR generating waveform: {e}")
        import traceback
        traceback.print_exc()
        return False


def create_text_overlay(
    track_name: str,
    chapter: str,
    is_teaser: bool = False,
    coming_date: str = "",
    use_tegaki: bool = False
) -> Path:
    """Create text overlay image — positioned in top third for first-frame hook."""
    img = Image.new("RGBA", (SHORTS_WIDTH, SHORTS_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_title = ImageFont.truetype(str(FONTS_DIR / "CormorantGaramond-SemiBold.ttf"), PUNCH_IN_FONT_SIZE)
    font_chapter = ImageFont.truetype(str(FONTS_DIR / "CrimsonPro-Regular.ttf"), TEXT_CHAPTER_SIZE)
    font_tagline = ImageFont.truetype(str(FONTS_DIR / "CrimsonPro-Regular.ttf"), TEXT_TAGLINE_SIZE)
    font_link = ImageFont.truetype(str(FONTS_DIR / "DMSans-Regular.ttf"), TEXT_LINK_SIZE)

    # Top gradient background
    for y in range(0, 550):
        if y < 80:
            alpha = 180
        else:
            progress = (y - 80) / (550 - 80)
            alpha = int(180 * (1 - progress) ** 1.5)
        draw.rectangle(
            [(0, y), (SHORTS_WIDTH, y + 1)],
            fill=(10, 8, 14, alpha)
        )

    current_y = 200

    if not use_tegaki:
        bbox = draw.textbbox((0, 0), track_name, font=font_title)
        text_width = bbox[2] - bbox[0]
        x_centered = (SHORTS_WIDTH - text_width) // 2
        draw.text((x_centered, current_y), track_name, fill=TEXT_PRIMARY, font=font_title)
        current_y += (bbox[3] - bbox[1]) + 20
    else:
        current_y = TEGAKI_TITLE_Y + TEGAKI_VIEWPORT_HEIGHT + 10

    # Separator line
    x_sep_start = (SHORTS_WIDTH - SEPARATOR_WIDTH) // 2
    current_y += 10
    draw.line(
        [(x_sep_start, current_y), (x_sep_start + SEPARATOR_WIDTH, current_y)],
        fill=SEPARATOR_COLOR,
        width=1
    )
    current_y += 20

    # Chapter name
    bbox = draw.textbbox((0, 0), chapter, font=font_chapter)
    text_width = bbox[2] - bbox[0]
    x_centered = (SHORTS_WIDTH - text_width) // 2
    draw.text((x_centered, current_y), chapter, fill=TEXT_SECONDARY, font=font_chapter)
    current_y += (bbox[3] - bbox[1]) + 14

    # Tagline
    tagline = "for the ones still awake."
    bbox = draw.textbbox((0, 0), tagline, font=font_tagline)
    text_width = bbox[2] - bbox[0]
    x_centered = (SHORTS_WIDTH - text_width) // 2
    draw.text((x_centered, current_y), tagline, fill=TEXT_TERTIARY, font=font_tagline)
    current_y += (bbox[3] - bbox[1]) + 12

    # Link text
    if is_teaser:
        link_text = f"Coming {coming_date}"
    else:
        link_text = "Full mixtape on YouTube"

    bbox = draw.textbbox((0, 0), link_text, font=font_link)
    text_width = bbox[2] - bbox[0]
    x_centered = (SHORTS_WIDTH - text_width) // 2
    draw.text((x_centered, current_y), link_text, fill=TEXT_QUATERNARY, font=font_link)

    text_overlay_file = SHORTS_DIR / "temp_text_overlay.png"
    img.save(text_overlay_file)
    return text_overlay_file


def create_pfp_overlay() -> Path:
    """Create circular PFP watermark overlay."""
    pfp = Image.open(CHANNEL_PFP).convert("RGBA")
    pfp = pfp.resize((PFP_SIZE, PFP_SIZE), Image.Resampling.LANCZOS)

    mask = Image.new("L", (PFP_SIZE, PFP_SIZE), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, PFP_SIZE, PFP_SIZE), fill=255)
    pfp.putalpha(mask)

    alpha = pfp.split()[3]
    alpha = alpha.point(lambda p: int(p * PFP_OPACITY))
    pfp.putalpha(alpha)

    overlay = Image.new("RGBA", (SHORTS_WIDTH, SHORTS_HEIGHT), (0, 0, 0, 0))

    border_img = Image.new("RGBA", (PFP_SIZE + 6, PFP_SIZE + 6), (0, 0, 0, 0))
    draw = ImageDraw.Draw(border_img)
    draw.ellipse((0, 0, PFP_SIZE + 6, PFP_SIZE + 6), outline=PFP_BORDER, width=2)

    overlay.paste(border_img, (PFP_POSITION[0] - 3, PFP_POSITION[1] - 3), border_img)
    overlay.paste(pfp, PFP_POSITION, pfp)

    pfp_overlay_file = SHORTS_DIR / "temp_pfp_overlay.png"
    overlay.save(pfp_overlay_file)
    return pfp_overlay_file


_tegaki_server_started = False

def _ensure_tegaki_server():
    """Start HTTP server for tegaki rendering (idempotent)."""
    global _tegaki_server_started
    if _tegaki_server_started:
        return
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(BASE_DIR)
    )
    server = http.server.HTTPServer(('127.0.0.1', TEGAKI_PORT), handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    _tegaki_server_started = True


async def generate_tegaki_title(track_name: str, output_dir: Path, total_frames: int) -> Optional[Path]:
    """Generate tegaki handwriting title animation as a MOV with alpha."""
    from playwright.async_api import async_playwright

    print(f"  Generating tegaki title: '{track_name}'...")

    tegaki_dir = output_dir / "tegaki"
    if tegaki_dir.exists():
        import shutil
        shutil.rmtree(tegaki_dir)
    tegaki_dir.mkdir(parents=True)

    _ensure_tegaki_server()

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={
                'width': SHORTS_WIDTH,
                'height': TEGAKI_VIEWPORT_HEIGHT
            })

            encoded_text = quote(track_name)
            url = f'http://127.0.0.1:{TEGAKI_PORT}/tegaki-template.html?text={encoded_text}'
            await page.goto(url)
            await page.wait_for_timeout(2000)

            anim_frames = FPS * TEGAKI_ANIM_SECONDS

            for i in range(total_frames):
                await page.screenshot(
                    path=str(tegaki_dir / f"frame_{i:04d}.png"),
                    omit_background=True
                )
                if i < anim_frames:
                    await page.wait_for_timeout(int(1000 / FPS))

            await browser.close()

        tegaki_video = output_dir / "tegaki.mov"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", str(tegaki_dir / "frame_%04d.png"),
            "-c:v", "qtrle",
            str(tegaki_video)
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        print(f"    Tegaki title generated ({total_frames} frames)")
        return tegaki_video

    except Exception as e:
        print(f"  ERROR generating tegaki title: {e}")
        import traceback
        traceback.print_exc()
        return None


def composite_final_video(
    video_clip: Path,
    audio_clip: Path,
    waveform_dir: Path,
    text_overlay: Path,
    pfp_overlay: Path,
    output_file: Path,
    total_frames: int,
    tegaki_video: Optional[Path] = None
) -> bool:
    """Composite all layers into final MP4 using ffmpeg."""
    print(f"  Compositing final video...")

    waveform_video = SHORTS_DIR / "temp_waveform.mov"
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", str(waveform_dir / "frame_%04d.png"),
        "-c:v", "qtrle",
        str(waveform_video)
    ]

    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"ERROR creating waveform video: {e.stderr.decode()}")
        return False

    if tegaki_video and tegaki_video.exists():
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_clip),
            "-i", str(waveform_video),
            "-i", str(text_overlay),
            "-i", str(pfp_overlay),
            "-i", str(tegaki_video),
            "-i", str(audio_clip),
            "-filter_complex",
            "[0:v]format=rgba[base];"
            "[base][1:v]overlay=0:0:format=auto[v1];"
            "[v1][2:v]overlay=0:0:format=auto[v2];"
            "[v2][3:v]overlay=0:0:format=auto[v3];"
            f"[v3][4:v]overlay=(W-w)/2:{TEGAKI_TITLE_Y}:format=auto[vout]",
            "-map", "[vout]",
            "-map", "5:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-t", str(CLIP_DURATION),
            str(output_file)
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_clip),
            "-i", str(waveform_video),
            "-i", str(text_overlay),
            "-i", str(pfp_overlay),
            "-i", str(audio_clip),
            "-filter_complex",
            "[0:v]format=rgba[base];"
            "[base][1:v]overlay=0:0:format=auto[v1];"
            "[v1][2:v]overlay=0:0:format=auto[v2];"
            "[v2][3:v]overlay=0:0:format=auto[vout]",
            "-map", "[vout]",
            "-map", "4:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-t", str(CLIP_DURATION),
            str(output_file)
        ]

    try:
        subprocess.run(cmd, capture_output=True, check=True)
        print(f"  Video saved: {output_file}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR compositing video: {e.stderr.decode()}")
        return False


def generate_metadata(short_data: dict, track_name: str, catalog: dict, output_file: Path) -> bool:
    """Generate metadata JSON for upload."""
    slug = slugify(track_name)

    description = ""
    parent_url = ""

    if short_data["source"] == "Single":
        for video in catalog["videos"]:
            if video["type"] == "single" and slugify(video["title"].split("—")[-1].strip()) == slug:
                description = video.get("description", "")
                parent_url = video.get("url", "")
                break
    else:
        for video in catalog["videos"]:
            if video["type"] == "mixtape" and short_data["source"] in video.get("chapter", ""):
                description = f"{track_name}\n\nFrom {video['chapter']}"
                parent_url = video.get("url", "") if video.get("url") else ""
                break

    if short_data["type"] == "teaser":
        coming_date = short_data["date"]
        metadata = {
            "title": f"NSTC — {track_name}",
            "description": f"{description}\n\nComing {coming_date}\n\n#lofi #lofihiphop #chill",
            "tags": ["lofi", "lofi hip hop", "chill beats", "study music", "late night music"],
            "type": "teaser",
            "coming_date": coming_date
        }
    else:
        full_desc = description
        if parent_url:
            full_desc += f"\n\nFull mixtape: {parent_url}"
        full_desc += "\n\n#lofi #lofihiphop #chill"

        metadata = {
            "title": f"NSTC — {track_name}",
            "description": full_desc,
            "tags": ["lofi", "lofi hip hop", "chill beats", "study music", "late night music"],
            "type": "catalog",
            "parent_video": parent_url
        }

    with open(output_file, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"  Metadata saved: {output_file}")
    return True


def generate_short(short_data: dict, track_analysis: dict, catalog: dict, use_tegaki: bool = False) -> bool:
    """Generate a single YouTube Short."""
    track_name = short_data["track"]
    track_slug = slugify(track_name)
    date = short_data["date"]
    slot = short_data["slot"]

    print(f"\n{'='*60}")
    print(f"Generating Short: {track_name}")
    print(f"Date: {date} | Slot: {slot} | Type: {short_data['type']} | Tegaki: {use_tegaki}")
    print(f"{'='*60}")

    if track_slug not in track_analysis:
        print(f"ERROR: No analysis found for track '{track_slug}'")
        return False

    analysis = track_analysis[track_slug]
    clip = analysis["clips"][0]
    clip_start = clip["start"]

    print(f"  Using clip: {clip['start_fmt']} - {clip['end_fmt']} (score: {clip['score']})")

    audio_file = AUDIO_DIR / f"{track_slug}.mp3"
    if not audio_file.exists():
        print(f"ERROR: Audio file not found: {audio_file}")
        return False

    video_source = find_video_source(track_name, short_data["source"], catalog)
    if not video_source or not video_source.exists():
        print(f"ERROR: Video file not found for {track_name} ({short_data['source']})")
        return False

    print(f"  Video source: {video_source.name}")

    temp_dir = SHORTS_DIR / f"temp_{track_slug}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Extract audio clip
    print(f"  Extracting audio clip...")
    audio_clip = temp_dir / "audio.mp3"
    if not extract_audio_clip(audio_file, clip_start, CLIP_DURATION, audio_clip):
        return False

    # Step 2: Extract video clip
    print(f"  Extracting video clip...")
    video_clip = temp_dir / "video.mp4"
    if not extract_video_clip(video_source, 0, CLIP_DURATION, video_clip):
        return False

    # Step 3: Generate waveform frames
    waveform_dir = temp_dir / "waveform"
    total_frames = FPS * CLIP_DURATION
    if not generate_waveform_frames(audio_clip, waveform_dir, total_frames):
        return False

    # Step 4: Create text overlay
    print(f"  Creating text overlay...")
    chapter = short_data["source"] if short_data["source"] != "Single" else "Future Memory Singles"
    is_teaser = short_data["type"] == "teaser"
    coming_date = short_data["date"] if is_teaser else ""
    text_overlay = create_text_overlay(track_name, chapter, is_teaser, coming_date, use_tegaki=use_tegaki)

    # Step 5: Create PFP overlay
    print(f"  Creating PFP overlay...")
    pfp_overlay = create_pfp_overlay()

    # Step 5.5: Generate tegaki title if enabled
    tegaki_video = None
    if use_tegaki:
        tegaki_video = asyncio.run(generate_tegaki_title(track_name, temp_dir, total_frames))
        if not tegaki_video:
            print(f"  WARNING: Tegaki failed, falling back to static title")
            text_overlay = create_text_overlay(track_name, chapter, is_teaser, coming_date, use_tegaki=False)

    # Step 6: Composite final video
    output_filename = f"{date}_{slot}_{track_slug}.mp4"
    output_file = SHORTS_DIR / output_filename

    if not composite_final_video(
        video_clip, audio_clip, waveform_dir, text_overlay, pfp_overlay,
        output_file, total_frames, tegaki_video=tegaki_video
    ):
        return False

    # Step 7: Generate metadata
    metadata_file = SHORTS_DIR / f"{date}_{slot}_{track_slug}.json"
    if not generate_metadata(short_data, track_name, catalog, metadata_file):
        return False

    # Cleanup temp files
    print(f"  Cleaning up temp files...")
    import shutil
    try:
        shutil.rmtree(temp_dir)
        text_overlay.unlink(missing_ok=True)
        pfp_overlay.unlink(missing_ok=True)
        (SHORTS_DIR / "temp_waveform.mov").unlink(missing_ok=True)
    except Exception as e:
        print(f"  WARNING: Cleanup failed: {e}")

    print(f"\nSHORT COMPLETE: {output_file.name}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate YouTube Shorts with animated waveforms")
    parser.add_argument("--phase", type=int, help="Phase number to generate (1-4)")
    parser.add_argument("--all", action="store_true", help="Generate all Shorts in schedule")
    parser.add_argument("--tegaki", action="store_true", help="Use tegaki handwriting animation for title")

    args = parser.parse_args()

    if not args.phase and not args.all:
        parser.print_help()
        sys.exit(1)

    print("Loading data files...")

    try:
        with open(TRACK_ANALYSIS_FILE) as f:
            track_analysis = json.load(f)
        print(f"  Loaded {len(track_analysis)} track analyses")
    except Exception as e:
        print(f"ERROR loading track analysis: {e}")
        sys.exit(1)

    try:
        with open(SCHEDULE_FILE) as f:
            schedule = json.load(f)
        print(f"  Loaded schedule ({schedule['total_shorts']} Shorts)")
    except Exception as e:
        print(f"ERROR loading schedule: {e}")
        sys.exit(1)

    try:
        with open(CATALOG_FILE) as f:
            catalog = json.load(f)
        print(f"  Loaded catalog ({len(catalog['videos'])} videos)")
    except Exception as e:
        print(f"ERROR loading catalog: {e}")
        sys.exit(1)

    SHORTS_DIR.mkdir(parents=True, exist_ok=True)

    shorts_to_generate = []

    if args.all:
        for phase in schedule["phases"]:
            shorts_to_generate.extend(phase["shorts"])
    else:
        phase_idx = args.phase - 1
        if phase_idx < 0 or phase_idx >= len(schedule["phases"]):
            print(f"ERROR: Invalid phase number. Available phases: 1-{len(schedule['phases'])}")
            sys.exit(1)

        phase = schedule["phases"][phase_idx]
        print(f"\nGenerating Phase {args.phase}: {phase['name']}")
        print(f"Dates: {phase['dates']}")
        print(f"Note: {phase['note']}\n")
        shorts_to_generate = phase["shorts"]

    total = len(shorts_to_generate)
    success_count = 0

    for idx, short_data in enumerate(shorts_to_generate, 1):
        print(f"\n{'#'*60}")
        print(f"Short {idx}/{total}")
        print(f"{'#'*60}")

        if generate_short(short_data, track_analysis, catalog, use_tegaki=args.tegaki):
            success_count += 1
        else:
            print(f"\nFAILED: {short_data['track']}")

    print(f"\n{'='*60}")
    print(f"GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"Success: {success_count}/{total}")
    print(f"Failed: {total - success_count}/{total}")
    print(f"Output directory: {SHORTS_DIR}")


if __name__ == "__main__":
    main()
