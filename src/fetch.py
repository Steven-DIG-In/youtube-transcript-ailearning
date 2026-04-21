from __future__ import annotations

import re
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)


def extract_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        return None
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif parsed.path.startswith("/shorts/"):
        candidate = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
    else:
        qs = parse_qs(parsed.query)
        candidate = qs.get("v", [""])[0]
    if _VIDEO_ID_RE.match(candidate):
        return candidate
    return None


def extract_youtube_urls_from_text(text: str) -> list[str]:
    results: list[str] = []
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:!?)")
        if extract_video_id(url) is not None:
            results.append(url)
    return results


def self_update_ytdlp() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-U", "--quiet", "yt-dlp"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp self-update failed: {result.stderr.strip() or 'unknown'}"
        )
