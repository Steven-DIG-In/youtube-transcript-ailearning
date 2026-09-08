from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import yt_dlp

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
    elif parsed.path.startswith("/embed/"):
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


SELF_UPDATE_TIMEOUT_SECONDS = 120


# The venv is uv-managed and has no pip, so `python -m pip` failed on every run
# from 2026-08 (daily 🚨 alert, yt-dlp frozen at 2026.06.09 while YouTube kept
# changing). launchd's PATH does not reach ~/.local/bin, hence the explicit
# fallback. Upgrading via `uv pip` deliberately sits outside uv.lock -- this is
# a runtime freshness bump, same intent as the old pip call, not a dependency
# change; `uv sync` would put the pinned version back.
_UV_FALLBACK = Path.home() / ".local" / "bin" / "uv"


def _uv_binary() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    return str(_UV_FALLBACK) if _UV_FALLBACK.exists() else None


def self_update_ytdlp() -> None:
    uv = _uv_binary()
    if uv is None:
        raise RuntimeError("yt-dlp self-update failed: uv not found on PATH or ~/.local/bin")
    try:
        result = subprocess.run(
            [uv, "pip", "install", "-U", "--quiet", "--python", sys.executable, "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=SELF_UPDATE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"yt-dlp self-update timed out after {SELF_UPDATE_TIMEOUT_SECONDS}s"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp self-update failed: {result.stderr.strip() or 'unknown'}"
        )


# ---------------------------------------------------------------------------
# Task 11: fetch_video wrapper
# ---------------------------------------------------------------------------


class FetchError(Exception):
    pass


@dataclass
class FetchResult:
    video_id: str
    title: str
    description: str
    channel: str
    channel_url: str
    channel_id: str
    duration_seconds: int
    published_at: str  # YYYY-MM-DD
    webpage_url: str
    transcript: str
    raw_transcript_path: Path


def _yyyymmdd_to_iso(value: str) -> str:
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"


def _vtt_to_plain_text(vtt: str) -> str:
    lines: list[str] = []
    for line in vtt.splitlines():
        stripped = line.strip()
        if (not stripped
                or stripped.startswith("WEBVTT")
                or "-->" in stripped
                or stripped.startswith("Kind:")
                or stripped.startswith("Language:")):
            continue
        cleaned = re.sub(r"<[^>]+>", "", stripped)
        if cleaned and (not lines or lines[-1] != cleaned):
            lines.append(cleaned)
    return "\n".join(lines)


_SUBTITLE_FETCH_TIMEOUT_SECONDS = 30


def _fetch_subtitle_url(url: str) -> str:
    with urlopen(url, timeout=_SUBTITLE_FETCH_TIMEOUT_SECONDS) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _load_transcript_for_video(info: dict) -> str | None:
    text = info.get("_transcript_text")
    if text:
        return text
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for source in (subs, auto):
        tracks = source.get("en") or source.get("en-US") or source.get("en-GB")
        if not tracks:
            continue
        for track in tracks:
            if track.get("ext") != "vtt":
                continue
            data = track.get("data")
            if not data:
                url = track.get("url")
                if not url:
                    continue
                try:
                    data = _fetch_subtitle_url(url)
                except Exception:
                    continue
            return _vtt_to_plain_text(data)
    return None


def fetch_video(url: str, *, raw_dir: Path) -> FetchResult:
    opts = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-GB"],
        "subtitlesformat": "vtt",
        "js_runtimes": {"node": {}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise FetchError(f"yt-dlp extract_info failed: {exc}") from exc

    transcript = _load_transcript_for_video(info)
    if not transcript:
        raise FetchError(f"no captions available for {info.get('id')}")

    try:
        video_id = info["id"]
        title = info["title"]
        upload_date = info["upload_date"]
    except KeyError as exc:
        raise FetchError(
            f"yt-dlp response missing expected field {exc} for URL: {url}"
        ) from exc

    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{video_id}.transcript.txt"
    raw_path.write_text(transcript)

    return FetchResult(
        video_id=video_id,
        title=title,
        description=info.get("description", ""),
        channel=info.get("channel", ""),
        channel_url=info.get("channel_url", ""),
        channel_id=info.get("channel_id", ""),
        duration_seconds=int(info.get("duration") or 0),
        published_at=_yyyymmdd_to_iso(upload_date),
        webpage_url=info.get("webpage_url", url),
        transcript=transcript,
        raw_transcript_path=raw_path,
    )


# ---------------------------------------------------------------------------
# Task 12: list_new_videos_for_channel
# ---------------------------------------------------------------------------


def list_new_videos_for_channel(
    channel_url: str,
    *,
    last_seen_video_id: str | None,
    lookback_days: int,
    now: str,  # YYYY-MM-DD
) -> list[dict]:
    opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            feed = ydl.extract_info(channel_url, download=False)
    except Exception as exc:
        raise FetchError(f"yt-dlp channel feed failed for {channel_url}: {exc}") from exc

    videos = _flatten_video_entries(feed.get("entries") or [])

    cutoff = (datetime.strptime(now, "%Y-%m-%d")
              - timedelta(days=lookback_days)).strftime("%Y%m%d")

    results: list[dict] = []
    for entry in videos:
        vid = entry.get("id")
        upload = entry.get("upload_date")
        if last_seen_video_id and vid == last_seen_video_id:
            break
        # Missing upload_date is common with extract_flat — trust feed
        # ordering (newest first) and let max_videos_per_run cap downstream.
        if not last_seen_video_id and upload and upload < cutoff:
            break
        results.append(entry)
    return results


def _flatten_video_entries(entries: list[dict]) -> list[dict]:
    """Descend into nested playlist entries (e.g. the Videos/Shorts split
    yt-dlp returns for a channel root URL) so callers iterate real videos."""
    out: list[dict] = []
    for entry in entries:
        if entry is None:
            continue
        if entry.get("_type") == "playlist":
            out.extend(_flatten_video_entries(entry.get("entries") or []))
        else:
            out.append(entry)
    return out
