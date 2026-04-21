from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

from src.extract import call_extract, render_extract_prompt
from src.fetch import extract_video_id, fetch_video
from src.slack_queue import SlackQueueItem
from src.state import mark_ingested, record_proposed_category
from src.write import (
    append_index_entries,
    append_log_entry,
    kebab_slug,
    upsert_creator_page,
    upsert_resources_index,
    write_source_page,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task 32: UrlCandidate + build_unified_queue
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Task 35: ProcessedVideo + process_one_video
# ---------------------------------------------------------------------------
@dataclass
class ProcessedVideo:
    video_id: str
    title: str
    creator: str
    creator_slug: str
    creator_is_new: bool
    source_page: str  # relative filename inside wiki/sources/
    categories: list[str]
    proposed_new_category_slugs: list[str]
    key_takeaways: list[str]
    resources_count: int


def _resources_index_snapshot(vault: Path) -> str:
    path = vault / "wiki" / "sources" / "resources-index.md"
    return path.read_text() if path.exists() else ""


def _existing_creator_page(vault: Path, channel: str) -> str:
    slug = f"creator-{kebab_slug(channel)}"
    path = vault / "wiki" / "entities" / f"{slug}.md"
    return path.read_text() if path.exists() else ""


def process_one_video(
    *,
    url: str,
    client: Anthropic,
    vault: Path,
    state: dict,
    seed_categories: list[str],
    channel_hint_categories: list[str],
    today: str,
    now_iso: str,
    model: str = "claude-sonnet-4-7",
) -> ProcessedVideo:
    raw_dir = vault / "raw" / "youtube"
    fetch_result = fetch_video(url, raw_dir=raw_dir)

    prompt = render_extract_prompt(
        title=fetch_result.title,
        channel=fetch_result.channel,
        channel_url=fetch_result.channel_url,
        published_at=fetch_result.published_at,
        duration_seconds=fetch_result.duration_seconds,
        description=fetch_result.description,
        channel_hint_categories=channel_hint_categories,
        seed_categories=seed_categories,
        existing_creator_page=_existing_creator_page(vault, fetch_result.channel),
        resources_index_snapshot=_resources_index_snapshot(vault),
        transcript=fetch_result.transcript,
    )
    extraction = call_extract(client, prompt=prompt, model=model)

    creator_slug_pre = f"creator-{kebab_slug(fetch_result.channel)}"
    creator_existed = (vault / "wiki" / "entities" / f"{creator_slug_pre}.md").exists()

    creator_slug, _ = upsert_creator_page(
        vault=vault,
        channel=fetch_result.channel,
        channel_url=fetch_result.channel_url,
        channel_id=fetch_result.channel_id,
        video_title=fetch_result.title,
        video_slug=kebab_slug(fetch_result.title),
        video_summary=extraction["session_summary"],
        video_published_at=fetch_result.published_at,
        video_domain=extraction["domain"],
        categories=extraction["categories"],
        creator_bio_additions=extraction["creator_bio_additions"],
        today=today,
    )
    source_path = write_source_page(
        vault=vault,
        fetch=fetch_result.__dict__,
        extraction=extraction,
        creator_slug=creator_slug,
        date_ingested=today,
    )
    source_slug = source_path.stem
    upsert_resources_index(
        vault=vault,
        resources=extraction["resources"],
        source_slug=source_slug,
        today=today,
    )
    append_index_entries(
        vault=vault,
        source_slug=source_slug,
        source_title=fetch_result.title,
        creator_slug=creator_slug,
        creator_name=fetch_result.channel,
        creator_is_new=not creator_existed,
    )
    append_log_entry(
        vault=vault,
        timestamp=now_iso,
        message=f"Ingested {fetch_result.video_id} → {source_slug}",
    )

    proposed_slugs: list[str] = []
    for p in extraction["proposed_new_categories"]:
        record_proposed_category(
            state,
            slug=p["slug"],
            video_id=fetch_result.video_id,
            now=now_iso,
        )
        proposed_slugs.append(p["slug"])
    mark_ingested(
        state,
        video_id=fetch_result.video_id,
        source_page=f"wiki/sources/{source_path.name}",
        creator_slug=creator_slug,
        ingested_at=now_iso,
    )

    return ProcessedVideo(
        video_id=fetch_result.video_id,
        title=fetch_result.title,
        creator=fetch_result.channel,
        creator_slug=creator_slug,
        creator_is_new=not creator_existed,
        source_page=source_path.name,
        categories=extraction["categories"],
        proposed_new_category_slugs=proposed_slugs,
        key_takeaways=extraction["key_takeaways"],
        resources_count=len(extraction["resources"]),
    )
