"""Weekly visual digest renderer.

Reads state.json, vault source pages, resources-index.md, and logs/usage.csv,
then writes a self-contained HTML file at vault/digest.html. No LLM calls.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape as _esc
from pathlib import Path
from urllib.parse import quote

import yaml

from src.write import _parse_resources_index

logger = logging.getLogger(__name__)


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

    # Volume per day: window_days slots, oldest first, newest = now's UTC date.
    # Today's ingests (from this run) DO belong in the last slot — the pipeline
    # runs at 10:30 and the digest renders right after, so "today" is meaningful.
    end_day = now.date()
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


_BODY_CAP = 4
_TOOL_CAP = 6


def build_episode_card(
    *,
    page: SourcePage,
    ingest: IngestRef,
    tools: list[str],
    vault_app_base_url: str,
    vault_name: str,
) -> EpisodeCard:
    steps = detect_steps(page.instructions_md)
    if steps is not None:
        body_mode = "steps"
        body_items = steps[:_BODY_CAP]
    else:
        body_mode = "takeaways"
        body_items = page.key_takeaways[:_BODY_CAP]

    deep_link = (
        f"{vault_app_base_url.rstrip('/')}/browse"
        f"?vault={quote(vault_name)}&page={quote(page.slug)}"
    )

    return EpisodeCard(
        title=page.title,
        creator=page.creator,
        published_at=page.published_at,
        duration_minutes=round(page.duration_seconds / 60),
        categories=list(page.categories),
        body_mode=body_mode,
        body_items=body_items,
        tools=list(tools[:_TOOL_CAP]),
        watch_url=page.video_url,
        read_in_vault_url=deep_link,
    )


_DIGEST_CSS = """
* { box-sizing:border-box; margin:0; padding:0; }
body { background:#0a0c10; color:#c7cbd6; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; line-height:1.5; padding:32px; }
.wrap { max-width:1040px; margin:0 auto; }
.top { display:flex; justify-content:space-between; align-items:flex-end; border-bottom:1px solid #20242e; padding-bottom:18px; margin-bottom:24px; }
.top .h { font-size:1.6rem; font-weight:800; color:#fff; }
.top .sub { font-size:.8rem; color:#8b90a0; margin-top:4px; }
.openvault { font-size:.78rem; font-weight:600; padding:9px 15px; border-radius:9px; background:#1b2533; color:#9fc0ff; border:1px solid #2b3140; text-decoration:none; }
.band { display:grid; grid-template-columns:1.1fr 1fr; gap:16px; margin-bottom:14px; }
.panel { background:#0f1115; border:1px solid #20242e; border-radius:14px; padding:16px; }
.panel .lab { font-size:.62rem; text-transform:uppercase; letter-spacing:.06em; color:#8b90a0; margin-bottom:12px; }
.stat-row { display:flex; gap:10px; }
.stat { flex:1; background:#171a21; border-radius:10px; padding:12px 8px; text-align:center; }
.stat .n { font-size:1.5rem; font-weight:700; color:#e8eaf0; line-height:1; }
.stat .l { font-size:.58rem; text-transform:uppercase; letter-spacing:.04em; color:#8b90a0; margin-top:6px; }
.bar-row { display:flex; align-items:center; gap:8px; margin:6px 0; font-size:.7rem; }
.bar-row .name { width:130px; text-align:right; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:#c7cbd6; }
.bar-track { flex:1; height:13px; background:#171a21; border-radius:7px; overflow:hidden; }
.bar-fill { height:100%; background:linear-gradient(90deg,#5b8cff,#7c5bff); border-radius:7px; }
.bar-row .v { width:24px; color:#8b90a0; text-align:right; }
.spark { display:flex; align-items:flex-end; gap:6px; height:58px; margin-top:6px; }
.spark .col { flex:1; background:linear-gradient(180deg,#7c5bff,#5b8cff); border-radius:4px 4px 0 0; min-height:4px; position:relative; }
.spark .col span { position:absolute; bottom:-15px; left:0; right:0; text-align:center; font-size:.55rem; color:#8b90a0; }
.tool-row { display:flex; justify-content:space-between; font-size:.72rem; padding:4px 0; border-bottom:1px solid #20242e; }
.tool-row:last-child { border:none; }
.tool-row .c { color:#7c5bff; font-weight:600; }
.section-lab { font-size:.7rem; text-transform:uppercase; letter-spacing:.06em; color:#8b90a0; margin:18px 0 14px; }
.ep { background:#0f1115; border:1px solid #20242e; border-radius:14px; padding:20px; position:relative; margin-bottom:16px; }
.ep .hook { position:absolute; top:20px; right:22px; text-align:right; }
.ep .hook .big { font-size:2.6rem; font-weight:800; color:#fff; line-height:1; }
.ep .hook small { display:block; font-size:.58rem; font-weight:600; text-transform:uppercase; letter-spacing:.08em; color:#8b90a0; margin-top:4px; }
.chiprow { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
.chip { font-size:.6rem; text-transform:uppercase; letter-spacing:.04em; padding:3px 8px; border-radius:999px; background:#1b2533; color:#7fa8ff; }
.chip.dur { background:#241b33; color:#b78fff; }
.ep h3 { font-size:1.28rem; color:#e8eaf0; margin:.1rem 0 .2rem; max-width:74%; line-height:1.2; }
.ep .creator { font-size:.74rem; color:#8b90a0; margin-bottom:14px; }
.take { font-size:.82rem; margin:6px 0; padding-left:18px; position:relative; }
.take:before { content:"▸"; position:absolute; left:0; color:#7c5bff; }
.step { display:flex; gap:10px; align-items:flex-start; margin:7px 0; font-size:.82rem; }
.step .num { flex-shrink:0; width:21px; height:21px; border-radius:50%; background:#7c5bff; color:#fff; font-size:.7rem; font-weight:700; display:flex; align-items:center; justify-content:center; }
.tools { display:flex; gap:6px; flex-wrap:wrap; margin-top:14px; }
.tool { font-size:.68rem; padding:3px 9px; border:1px solid #2b3140; border-radius:7px; color:#c7cbd6; }
.btns { display:flex; gap:10px; margin-top:16px; }
.btn { font-size:.74rem; font-weight:600; padding:8px 14px; border-radius:8px; text-decoration:none; }
.btn.watch { background:#7c5bff; color:#fff; }
.btn.read { background:#1b2533; color:#9fc0ff; border:1px solid #2b3140; }
.empty { text-align:center; padding:48px 0; color:#5a5f6e; font-style:italic; }
.foot { text-align:center; font-size:.68rem; color:#5a5f6e; margin-top:24px; }
"""


def _render_stat(n: object, label: str) -> str:
    return f'<div class="stat"><div class="n">{_esc(str(n))}</div><div class="l">{_esc(label)}</div></div>'


def _render_bar_row(name: str, value: int, max_value: int) -> str:
    pct = (value / max_value * 100) if max_value else 0
    return (
        f'<div class="bar-row"><div class="name">{_esc(name)}</div>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.0f}%"></div></div>'
        f'<div class="v">{value}</div></div>'
    )


def _render_card(card: EpisodeCard) -> str:
    chips = "".join(f'<span class="chip">{_esc(c)}</span>' for c in card.categories)
    chips += f'<span class="chip dur">{card.duration_minutes} min</span>'
    if card.body_mode == "steps":
        body_html = "".join(
            f'<div class="step"><div class="num">{i+1}</div><div>{_esc(item)}</div></div>'
            for i, item in enumerate(card.body_items)
        )
    else:
        body_html = "".join(f'<div class="take">{_esc(item)}</div>' for item in card.body_items)
    tool_html = "".join(f'<span class="tool">{_esc(t)}</span>' for t in card.tools)
    tools_block = f'<div class="tools">{tool_html}</div>' if card.tools else ""
    return (
        '<div class="ep">'
        f'<div class="hook"><div class="big">{card.duration_minutes}</div><small>minutes</small></div>'
        f'<div class="chiprow">{chips}</div>'
        f'<h3>{_esc(card.title)}</h3>'
        f'<div class="creator">{_esc(card.creator)} · {_esc(card.published_at)}</div>'
        f'{body_html}'
        f'{tools_block}'
        '<div class="btns">'
        f'<a class="btn watch" href="{_esc(card.watch_url)}">▶ Watch</a>'
        f'<a class="btn read" href="{_esc(card.read_in_vault_url)}">📖 Read in vault</a>'
        '</div></div>'
    )


def render_digest_html(
    *,
    aggregates: Aggregates,
    cards: list[EpisodeCard],
    generated_at: datetime,
    window_start: datetime,
    window_end: datetime,
    vault_app_base_url: str,
    vault_name: str,
) -> str:
    # Stat band
    stat_html = (
        _render_stat(aggregates.video_count, "Videos")
        + _render_stat(aggregates.creator_count, "Creators")
        + _render_stat(aggregates.tool_count, "Tools")
        + _render_stat(f"${aggregates.spend_usd:.2f}", "Spend")
    )

    # Top categories
    max_cat = max((c for _, c in aggregates.top_categories), default=0)
    cat_html = "".join(
        _render_bar_row(slug, count, max_cat) for slug, count in aggregates.top_categories
    ) or '<div class="bar-row"><div class="name">—</div></div>'

    # Volume per day
    max_vol = max((c for _, c in aggregates.volume_per_day), default=0) or 1
    cols = "".join(
        f'<div class="col" style="height:{(c / max_vol * 100):.0f}%"><span>{_esc(d)}</span></div>'
        for d, c in aggregates.volume_per_day
    )

    # Top tools
    tools_html = "".join(
        f'<div class="tool-row"><span>{_esc(name)}</span><span class="c">×{count}</span></div>'
        for name, count in aggregates.top_tools
    ) or '<div class="tool-row"><span>—</span><span class="c"></span></div>'

    # Gallery
    if cards:
        gallery_lab = f'<div class="section-lab">{len(cards)} episode{"s" if len(cards) != 1 else ""} · newest first</div>'
        gallery_html = "".join(_render_card(c) for c in cards)
    else:
        gallery_lab = ""
        gallery_html = '<div class="empty">No videos in the last 7 days.</div>'

    # Header
    open_vault_url = f"{vault_app_base_url.rstrip('/')}/browse?vault={quote(vault_name)}"
    date_range = (
        f"{window_start.astimezone().strftime('%-d %b')}–"
        f"{window_end.astimezone().strftime('%-d %b %Y')}"
    )
    gen_label = generated_at.astimezone().strftime("%-d %b %H:%M")
    sub = (
        f"{_esc(date_range)} · {aggregates.video_count} videos · "
        f"{aggregates.creator_count} creators · generated {_esc(gen_label)}"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Learnings — Last 7 Days</title>
<style>{_DIGEST_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div>
      <div class="h">AI Learnings — Last 7 Days</div>
      <div class="sub">{sub}</div>
    </div>
    <a class="openvault" href="{_esc(open_vault_url)}">⤢ Open vault</a>
  </div>

  <div class="band">
    <div class="panel">
      <div class="lab">This week</div>
      <div class="stat-row">{stat_html}</div>
      <div class="lab" style="margin-top:18px;">Top categories</div>
      {cat_html}
    </div>
    <div class="panel">
      <div class="lab">Volume per day</div>
      <div class="spark">{cols}</div>
      <div class="lab" style="margin-top:26px;">Top tools mentioned</div>
      {tools_html}
    </div>
  </div>

  {gallery_lab}
  {gallery_html}

  <div class="foot">Generated by youtube-transcript-ailearning · src/digest.py · self-contained, offline-friendly</div>
</div>
</body>
</html>
"""


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_digest(
    *,
    vault: Path,
    state: dict,
    now: datetime,
    window_days: int,
    vault_app_base_url: str,
    vault_name: str,
    usage_csv_path: Path,
) -> Path:
    refs = select_recent_ingests(state, vault=vault, now=now, window_days=window_days)

    pages: list[SourcePage] = []
    kept_refs: list[IngestRef] = []
    for ref in refs:
        if not ref.source_page_path.exists():
            logger.warning("digest: source page missing, skipping: %s", ref.source_page_path)
            continue
        try:
            pages.append(parse_source_page(ref.source_page_path))
            kept_refs.append(ref)
        except Exception as exc:
            logger.warning("digest: failed to parse %s: %s", ref.source_page_path, exc)

    slugs = [p.slug for p in pages]
    index_path = vault / "wiki" / "sources" / "resources-index.md"
    tools_by_slug = tools_for_sources(index_path, slugs=slugs)

    window_start = now - timedelta(days=window_days)
    spend = compute_spend(usage_csv_path, window_start=window_start, window_end=now)

    aggregates = compute_aggregates(
        pages=pages, ingests=kept_refs, tools_by_slug=tools_by_slug,
        spend_usd=spend, now=now, window_days=window_days,
    )

    cards = [
        build_episode_card(
            page=page, ingest=ref, tools=tools_by_slug.get(page.slug, []),
            vault_app_base_url=vault_app_base_url, vault_name=vault_name,
        )
        for page, ref in zip(pages, kept_refs)
    ]

    html = render_digest_html(
        aggregates=aggregates, cards=cards,
        generated_at=now,
        window_start=window_start, window_end=now,
        vault_app_base_url=vault_app_base_url, vault_name=vault_name,
    )

    out = vault / "digest.html"
    _atomic_write(out, html)
    return out
