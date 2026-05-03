#!/usr/bin/env python3
"""
Upload YouTube Shorts from generated files.

Usage:
  python3 youtube-upload.py <video.mp4>           # Upload single Short
  python3 youtube-upload.py --phase 1             # Upload all Phase 1 Shorts
  python3 youtube-upload.py --all                 # Upload everything
  python3 youtube-upload.py --dry-run --phase 1   # Preview without uploading
"""
import json
import os
import sys
import time
import argparse
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = Path(os.environ.get("NSTC_BASE_DIR", Path(__file__).parent))
TOKEN_FILE = BASE_DIR / "youtube-token.json"
SHORTS_DIR = BASE_DIR / "shorts"
SCHEDULE_FILE = BASE_DIR / "shorts-schedule.json"


def get_youtube_client():
    """Build authenticated YouTube API client."""
    with open(TOKEN_FILE) as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"],
    )

    if creds.expired or not creds.valid:
        creds.refresh(Request())
        token_data["token"] = creds.token
        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f, indent=2)

    return build("youtube", "v3", credentials=creds)


def slot_to_publish_time(date_str: str, slot: str) -> str:
    """Convert date + slot to ISO 8601 publish time (Bangkok UTC+7 -> UTC)."""
    slot_hours = {"AM": 10, "PM": 16, "EVE": 20}
    hour_bkk = slot_hours.get(slot, 10)
    hour_utc = (hour_bkk - 7) % 24
    return f"{date_str}T{hour_utc:02d}:00:00Z"


def upload_short(youtube, video_path: Path, metadata_path: Path, dry_run: bool = False) -> bool:
    """Upload a single Short to YouTube as private with scheduled publish."""
    with open(metadata_path) as f:
        metadata = json.load(f)

    title = metadata["title"]
    description = metadata["description"]
    tags = metadata.get("tags", [])

    parts = video_path.stem.split("_", 2)
    date_str = parts[0]
    slot = parts[1]
    publish_at = slot_to_publish_time(date_str, slot)

    print(f"\n  Title: {title}")
    print(f"  File: {video_path.name}")
    print(f"  Scheduled: {publish_at} (slot: {slot})")
    print(f"  Tags: {', '.join(tags[:5])}")

    if dry_run:
        print(f"  [DRY RUN] Would upload {video_path.name} -> private, publish at {publish_at}")
        return True

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "10",  # Music
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Uploading... {pct}%", end="\r")

    video_id = response["id"]
    print(f"  Uploaded: https://youtube.com/shorts/{video_id}")

    metadata["youtube_id"] = video_id
    metadata["youtube_url"] = f"https://youtube.com/shorts/{video_id}"
    metadata["uploaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    return True


def find_shorts_for_phase(phase_num: int) -> list:
    """Find video/metadata pairs for a phase."""
    with open(SCHEDULE_FILE) as f:
        schedule = json.load(f)

    phase = schedule["phases"][phase_num - 1]
    pairs = []

    for short_data in phase["shorts"]:
        slug = short_data["track"].lower().replace(":", "").replace(",", "").replace("'", "").replace(" ", "-")
        date = short_data["date"]
        slot = short_data["slot"]

        video = SHORTS_DIR / f"{date}_{slot}_{slug}.mp4"
        meta = SHORTS_DIR / f"{date}_{slot}_{slug}.json"

        if video.exists() and meta.exists():
            pairs.append((video, meta))
        else:
            print(f"  WARNING: Missing files for {short_data['track']}")

    return pairs


def main():
    parser = argparse.ArgumentParser(description="Upload YouTube Shorts")
    parser.add_argument("video", nargs="?", help="Single video file to upload")
    parser.add_argument("--phase", type=int, help="Upload all Shorts from a phase")
    parser.add_argument("--all", action="store_true", help="Upload all generated Shorts")
    parser.add_argument("--dry-run", action="store_true", help="Preview without uploading")

    args = parser.parse_args()

    if not args.video and not args.phase and not args.all:
        parser.print_help()
        sys.exit(1)

    pairs = []

    if args.video:
        video = Path(args.video)
        meta = video.with_suffix(".json")
        if not video.exists():
            print(f"ERROR: Video not found: {video}")
            sys.exit(1)
        if not meta.exists():
            print(f"ERROR: Metadata not found: {meta}")
            sys.exit(1)
        pairs.append((video, meta))

    elif args.phase:
        pairs = find_shorts_for_phase(args.phase)

    elif args.all:
        with open(SCHEDULE_FILE) as f:
            schedule = json.load(f)
        for i in range(len(schedule["phases"])):
            pairs.extend(find_shorts_for_phase(i + 1))

    if not pairs:
        print("No Shorts found to upload.")
        sys.exit(1)

    print(f"{'=' * 60}")
    print(f"YouTube Shorts Upload {'(DRY RUN)' if args.dry_run else ''}")
    print(f"{'=' * 60}")
    print(f"Shorts to upload: {len(pairs)}")

    if not args.dry_run:
        youtube = get_youtube_client()
    else:
        youtube = None

    success = 0
    for i, (video, meta) in enumerate(pairs, 1):
        print(f"\n[{i}/{len(pairs)}]")
        try:
            if upload_short(youtube, video, meta, args.dry_run):
                success += 1
                if not args.dry_run and i < len(pairs):
                    print("  Waiting 5s before next upload...")
                    time.sleep(5)
        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\n{'=' * 60}")
    print(f"Done. {success}/{len(pairs)} uploaded.")


if __name__ == "__main__":
    main()
