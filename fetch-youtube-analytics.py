#!/usr/bin/env python3
"""
Fetch YouTube Analytics for your channel.
Writes channel stats, per-video performance, traffic sources, and concerns
to a JSON file for consumption by other tools.

Usage:
  python3 fetch-youtube-analytics.py
  NSTC_BASE_DIR=/path/to/data python3 fetch-youtube-analytics.py
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE_DIR = Path(os.environ.get("NSTC_BASE_DIR", Path(__file__).parent))
TOKEN_FILE = BASE_DIR / "youtube-token.json"
OUTPUT_FILE = BASE_DIR / "youtube-analytics.json"


def get_creds():
    with open(TOKEN_FILE) as f:
        td = json.load(f)
    creds = Credentials(
        token=td["token"], refresh_token=td["refresh_token"],
        token_uri=td["token_uri"], client_id=td["client_id"],
        client_secret=td["client_secret"], scopes=td["scopes"],
    )
    if creds.expired or not creds.valid:
        creds.refresh(Request())
        td["token"] = creds.token
        with open(TOKEN_FILE, "w") as f:
            json.dump(td, f, indent=2)
    return creds


def fetch():
    creds = get_creds()
    yt = build("youtube", "v3", credentials=creds)
    yta = build("youtubeAnalytics", "v2", credentials=creds)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d7 = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    d14 = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    d28 = (datetime.now(timezone.utc) - timedelta(days=28)).strftime("%Y-%m-%d")

    # Channel stats
    ch = yt.channels().list(part="statistics", mine=True).execute()
    stats = ch["items"][0]["statistics"]

    # 7-day vs prev 7-day
    week_now = yta.reports().query(
        ids="channel==MINE", startDate=d7, endDate=today,
        metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,likes",
    ).execute()
    week_prev = yta.reports().query(
        ids="channel==MINE", startDate=d14, endDate=d7,
        metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,likes",
    ).execute()

    def sum_rows(resp):
        rows = resp.get("rows", [[0, 0, 0, 0, 0]])
        if not rows:
            return [0, 0, 0, 0, 0]
        return rows[0] if len(rows) == 1 else [sum(r[i] for r in rows) for i in range(5)]

    wn = sum_rows(week_now)
    wp = sum_rows(week_prev)

    channel_data = {
        "subscribers": int(stats.get("subscriberCount", 0)),
        "total_views": int(stats.get("viewCount", 0)),
        "total_videos": int(stats.get("videoCount", 0)),
        "7d_views": wn[0],
        "7d_watch_hours": round(wn[1] / 60, 1),
        "7d_subs_gained": wn[2],
        "7d_subs_lost": wn[3],
        "7d_likes": wn[4],
        "prev_7d_views": wp[0],
        "prev_7d_watch_hours": round(wp[1] / 60, 1),
        "view_trend": "up" if wn[0] > wp[0] else "down" if wn[0] < wp[0] else "flat",
    }

    # Per-video performance (last 28 days)
    vid_perf = yta.reports().query(
        ids="channel==MINE", startDate=d28, endDate=today,
        metrics="views,estimatedMinutesWatched,averageViewDuration,likes",
        dimensions="video",
        sort="-views",
        maxResults=25,
    ).execute()

    video_ids = [row[0] for row in vid_perf.get("rows", [])]
    video_meta = {}
    if video_ids:
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            vids = yt.videos().list(
                part="snippet,contentDetails", id=",".join(batch)
            ).execute()
            for v in vids.get("items", []):
                dur = v["contentDetails"]["duration"]
                m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', dur)
                secs = 0
                if m:
                    secs = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)
                title = v["snippet"]["title"]
                is_short = secs <= 180 and ("—" not in title or secs <= 90)
                video_meta[v["id"]] = {
                    "title": title,
                    "published": v["snippet"]["publishedAt"][:10],
                    "duration_sec": secs,
                    "is_short": is_short,
                }

    videos = []
    shorts = []
    for row in vid_perf.get("rows", []):
        vid_id = row[0]
        meta = video_meta.get(vid_id, {})
        entry = {
            "id": vid_id,
            "title": meta.get("title", "Unknown"),
            "published": meta.get("published", ""),
            "duration_sec": meta.get("duration_sec", 0),
            "views": row[1],
            "watch_min": round(row[2], 1),
            "avg_view_duration_sec": row[3],
            "likes": row[4],
        }

        if meta.get("is_short", False):
            dur = meta.get("duration_sec", 10) or 10
            watch_through = min(row[3] / dur, 1.0) if dur > 0 else 0
            entry["swipe_away_rate"] = round(1 - watch_through, 3)
            entry["watch_through_pct"] = round(watch_through * 100, 1)
            shorts.append(entry)
        else:
            videos.append(entry)

    # Traffic sources
    traffic = yta.reports().query(
        ids="channel==MINE", startDate=d28, endDate=today,
        metrics="views",
        dimensions="insightTrafficSourceType",
        sort="-views",
    ).execute()

    traffic_sources = {}
    for row in traffic.get("rows", []):
        traffic_sources[row[0]] = row[1]

    # Top performers
    all_content = sorted(videos + shorts, key=lambda x: x["views"], reverse=True)
    top = all_content[:3] if all_content else []

    # Concerns
    concerns = []
    for s in shorts:
        if s.get("swipe_away_rate", 0) > 0.85 and s["views"] > 20:
            concerns.append(f"High swipe-away ({s['swipe_away_rate']*100:.0f}%) on \"{s['title']}\"")
    if channel_data["view_trend"] == "down":
        pct = round((1 - channel_data["7d_views"] / max(channel_data["prev_7d_views"], 1)) * 100)
        concerns.append(f"Views down {pct}% week-over-week ({channel_data['7d_views']} vs {channel_data['prev_7d_views']})")

    output = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channel": channel_data,
        "videos": videos,
        "shorts": shorts,
        "traffic_sources": traffic_sources,
        "top_performers": [{"title": t["title"], "views": t["views"], "type": "short" if t.get("swipe_away_rate") is not None else "video"} for t in top],
        "concerns": concerns,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Analytics written to {OUTPUT_FILE}")
    print(f"  Channel: {channel_data['subscribers']} subs, {channel_data['total_views']} views")
    print(f"  7d: {channel_data['7d_views']} views ({channel_data['view_trend']}), +{channel_data['7d_subs_gained']} subs")
    print(f"  Videos: {len(videos)} | Shorts: {len(shorts)}")
    if concerns:
        print(f"  Concerns: {len(concerns)}")
        for c in concerns:
            print(f"    - {c}")


if __name__ == "__main__":
    fetch()
