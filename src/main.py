from __future__ import annotations

from dataclasses import dataclass

from src.fetch import extract_video_id
from src.slack_queue import SlackQueueItem


@dataclass
class UrlCandidate:
    url: str
    video_id: str
    source: str  # "queue.txt" | "slack" | "watchlist"
    slack_item: SlackQueueItem | None = None


def build_unified_queue(
    *,
    queue_txt_urls: list[str],
    slack_items: list[SlackQueueItem],
    watchlist_urls: list[str],
    already_ingested: set[str],
) -> list[UrlCandidate]:
    seen: set[str] = set()
    out: list[UrlCandidate] = []

    def add(url: str, source: str, slack_item: SlackQueueItem | None = None) -> None:
        vid = extract_video_id(url)
        if not vid or vid in seen or vid in already_ingested:
            return
        seen.add(vid)
        out.append(UrlCandidate(url=url, video_id=vid, source=source,
                                slack_item=slack_item))

    for url in queue_txt_urls:
        add(url, "queue.txt")
    for item in slack_items:
        add(item.url, "slack", slack_item=item)
    for url in watchlist_urls:
        add(url, "watchlist")
    return out


# ---------------------------------------------------------------------------
# Task 33: drain_queue_txt
# ---------------------------------------------------------------------------
from pathlib import Path


def drain_queue_txt(path: Path) -> list[str]:
    if not path.exists():
        return []
    urls = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    path.write_text("")
    return urls


# ---------------------------------------------------------------------------
# Task 34: raw_storage_footprint
# ---------------------------------------------------------------------------
def raw_storage_footprint(raw_dir: Path) -> tuple[int, int]:
    if not raw_dir.exists():
        return 0, 0
    files = list(raw_dir.glob("*.transcript.txt"))
    return sum(f.stat().st_size for f in files), len(files)
