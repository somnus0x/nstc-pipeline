#!/usr/bin/env python3
"""
YouTube OAuth2 setup — two-step for headless servers.

Step 1: python3 youtube-auth.py url     -> prints auth URL
Step 2: python3 youtube-auth.py code XXXXX  -> exchanges code for token

Requires YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]

BASE_DIR = Path(os.environ.get("NSTC_BASE_DIR", Path(__file__).parent))
TOKEN_FILE = BASE_DIR / "youtube-token.json"

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/yt-analytics.readonly"
REDIRECT_URI = "http://localhost:1"


def step_url():
    """Generate auth URL."""
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code"
        f"&scope={SCOPES.replace(' ', '%20')}"
        "&access_type=offline"
        "&prompt=consent"
    )
    print(f"\nOpen this URL in your browser:\n\n{url}\n")
    print("Sign in -> Allow -> it will redirect to localhost (page won't load).")
    print("Copy the 'code' parameter from the URL bar.")
    print("Then run: python3 youtube-auth.py code YOUR_CODE\n")


def step_code(code: str):
    """Exchange auth code for tokens."""
    import urllib.request
    import urllib.parse

    data = urllib.parse.urlencode({
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req) as resp:
            token_data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"ERROR {e.code}: {error_body}")
        sys.exit(1)

    save_data = {
        "token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scopes": SCOPES.split(),
    }

    with open(TOKEN_FILE, "w") as f:
        json.dump(save_data, f, indent=2)
    os.chmod(TOKEN_FILE, 0o600)

    print(f"Token saved to {TOKEN_FILE}")
    print("YouTube upload ready.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 youtube-auth.py url|code <CODE>")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "url":
        step_url()
    elif cmd == "code":
        if len(sys.argv) < 3:
            print("Pass the auth code: python3 youtube-auth.py code YOUR_CODE")
            sys.exit(1)
        step_code(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
