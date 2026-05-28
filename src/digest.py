"""Weekly visual digest renderer.

Reads state.json, vault source pages, resources-index.md, and logs/usage.csv,
then writes a self-contained HTML file at vault/digest.html. No LLM calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


SONNET_INPUT_USD_PER_MTOK = 3.00
SONNET_OUTPUT_USD_PER_MTOK = 15.00


@dataclass
class IngestRef:
    video_id: str
    creator_slug: str
    source_slug: str          # filename without .md
    source_page_path: Path    # absolute path to the .md file
    ingested_at: datetime     # UTC


@dataclass
class SourcePage:
    slug: str
    title: str
    video_url: str
    creator: str              # display name from frontmatter, may be wikilink-stripped
    published_at: str         # YYYY-MM-DD
    duration_seconds: int
    categories: list[str]
    domain: str
    tags: list[str]
    session_summary: str
    instructions_md: str
    key_takeaways: list[str]


@dataclass
class EpisodeCard:
    title: str
    creator: str
    published_at: str
    duration_minutes: int
    categories: list[str]
    body_mode: str            # "steps" | "takeaways"
    body_items: list[str]
    tools: list[str]
    watch_url: str
    read_in_vault_url: str


@dataclass
class Aggregates:
    video_count: int
    creator_count: int
    tool_count: int           # distinct tools across window
    spend_usd: float
    top_categories: list[tuple[str, int]]    # [(slug, count), ...] top 5
    volume_per_day: list[tuple[str, int]]    # [(weekday_label, count), ...] 7 entries
    top_tools: list[tuple[str, int]]         # [(name, count), ...] top 5


def select_recent_ingests(
    state: dict,
    *,
    vault: Path,
    now: datetime,
    window_days: int,
) -> list[IngestRef]:
    cutoff = now - timedelta(days=window_days)
    refs: list[IngestRef] = []
    for vid, entry in (state.get("ingested_video_ids") or {}).items():
        ts_raw = entry.get("ingested_at")
        if not ts_raw:
            continue
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < cutoff:
            continue
        source_page = entry["source_page"]            # e.g. "wiki/sources/foo.md"
        source_slug = Path(source_page).stem
        refs.append(IngestRef(
            video_id=vid,
            creator_slug=entry.get("creator_slug", ""),
            source_slug=source_slug,
            source_page_path=vault / source_page,
            ingested_at=ts,
        ))
    refs.sort(key=lambda r: r.ingested_at, reverse=True)
    return refs
