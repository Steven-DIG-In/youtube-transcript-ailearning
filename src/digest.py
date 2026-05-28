"""Weekly visual digest renderer.

Reads state.json, vault source pages, resources-index.md, and logs/usage.csv,
then writes a self-contained HTML file at vault/digest.html. No LLM calls.
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from src.write import _parse_resources_index


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


_SECTION_RE = re.compile(r"^## (?P<name>.+)$", re.MULTILINE)
_WIKILINK_RE = re.compile(r"^\[\[(.+)\]\]$")


def _split_sections(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(body))
    for i, m in enumerate(matches):
        name = m.group("name").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out[name] = body[start:end].strip()
    return out


def _bullet_items(section_text: str) -> list[str]:
    items: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def parse_source_page(path: Path) -> SourcePage:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise ValueError(f"source page missing frontmatter: {path}")
    fm_end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:fm_end]) or {}
    body = text[fm_end + 5:]
    sections = _split_sections(body)

    creator_raw = str(fm.get("creator", ""))
    wikimatch = _WIKILINK_RE.match(creator_raw)
    creator = wikimatch.group(1) if wikimatch else creator_raw

    return SourcePage(
        slug=path.stem,
        title=str(fm.get("title", "")),
        video_url=str(fm.get("video_url", "")),
        creator=creator,
        published_at=str(fm.get("published_at", "")),
        duration_seconds=int(fm.get("duration_seconds") or 0),
        categories=list(fm.get("categories") or []),
        domain=str(fm.get("domain", "")),
        tags=list(fm.get("tags") or []),
        session_summary=sections.get("Session Summary", ""),
        instructions_md=sections.get("Instructions & How-To", ""),
        key_takeaways=_bullet_items(sections.get("Key Takeaways", "")),
    )


_TOP_LEVEL_NUMBERED_RE = re.compile(r"^(\d+)[.)]\s+(.+?)$")


def detect_steps(instructions_md: str) -> list[str] | None:
    steps: list[str] = []
    for raw in instructions_md.splitlines():
        # Skip indented (sub-bullet / continuation) lines.
        if raw.startswith((" ", "\t")):
            continue
        m = _TOP_LEVEL_NUMBERED_RE.match(raw.rstrip())
        if not m:
            continue
        steps.append(m.group(2).strip())
    if len(steps) < 2:
        return None
    return steps


def tools_for_sources(
    index_path: Path,
    *,
    slugs: list[str],
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {s: [] for s in slugs}
    if not index_path.exists():
        return out
    _, groups = _parse_resources_index(index_path.read_text())
    tools = groups.get("Tools") or []
    slug_set = set(slugs)
    for entry in tools:
        for s in entry.get("sources", []):
            if s in slug_set:
                out[s].append(entry["title"])
    return out


def top_tools(
    tools_by_slug: dict[str, list[str]],
    *,
    k: int = 5,
) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for tools in tools_by_slug.values():
        counter.update(tools)
    return counter.most_common(k)


def compute_spend(
    usage_csv_path: Path,
    *,
    window_start: datetime,
    window_end: datetime,
) -> float:
    if not usage_csv_path.exists():
        return 0.0
    total = 0.0
    with usage_csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_raw = row.get("ts")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < window_start or ts > window_end:
                continue
            try:
                inp = int(row.get("input_tokens") or 0)
                out = int(row.get("output_tokens") or 0)
            except ValueError:
                continue
            total += inp / 1_000_000 * SONNET_INPUT_USD_PER_MTOK
            total += out / 1_000_000 * SONNET_OUTPUT_USD_PER_MTOK
    return round(total, 4)


_WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def compute_aggregates(
    *,
    pages: list[SourcePage],
    ingests: list[IngestRef],
    tools_by_slug: dict[str, list[str]],
    spend_usd: float,
    now: datetime,
    window_days: int,
) -> Aggregates:
    creators = {p.creator for p in pages}
    all_tools = {t for ts in tools_by_slug.values() for t in ts}

    cat_counter: Counter[str] = Counter()
    for p in pages:
        cat_counter.update(p.categories)

    # Volume per day: window_days slots, oldest first, newest = yesterday's date (incomplete today excluded).
    end_day = (now - timedelta(days=1)).date()
    days = [end_day - timedelta(days=i) for i in range(window_days - 1, -1, -1)]
    per_day: dict = {d: 0 for d in days}
    for r in ingests:
        d = r.ingested_at.date()
        if d in per_day:
            per_day[d] += 1
    volume = [(_WEEKDAY_ABBR[d.weekday()], per_day[d]) for d in days]

    return Aggregates(
        video_count=len(ingests),
        creator_count=len(creators),
        tool_count=len(all_tools),
        spend_usd=spend_usd,
        top_categories=cat_counter.most_common(5),
        volume_per_day=volume,
        top_tools=top_tools(tools_by_slug, k=5),
    )
