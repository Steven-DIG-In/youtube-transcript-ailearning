"""Weekly visual digest renderer.

Reads state.json, vault source pages, resources-index.md, and logs/usage.csv,
then writes a self-contained HTML file at vault/digest.html. No LLM calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
