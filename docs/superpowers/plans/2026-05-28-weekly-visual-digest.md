# Weekly Visual Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render `digest.html` at the vault root at the end of every daily run — a self-contained 7-day rolling summary with an aggregate band, per-episode poster cards, and deep-links into the wiki app — and surface a pointer to it in the existing Slack daily summary.

**Architecture:** A single new pure-Python module `src/digest.py` reads `state.json`, the vault source pages, `wiki/sources/resources-index.md`, and `logs/usage.csv`, then writes a static HTML file atomically. No new LLM calls. The digest parser is round-trip-tested against `src/write.write_source_page` so the two cannot drift.

**Tech Stack:** Python 3.13, PyYAML (already a dep), `dataclasses`, `html.escape`, `csv`, `datetime`, `pathlib`. No new third-party deps. A one-line patch in the separate `wiki-knowledge-interface` Next.js repo enables `?vault=` deep-links.

**Spec reference:** `docs/superpowers/specs/2026-05-28-weekly-visual-digest-design.md`

---

## File Structure

**Create:**
- `src/digest.py` — the renderer module (data classes, pure functions, orchestrator).
- `tests/test_digest.py` — unit tests, including the round-trip writer/parser test.

**Modify:**
- `src/config.py` — add `DigestConfig` dataclass, include in `Config`, parse with defaults.
- `config.yml` — add the `digest:` block.
- `tests/test_config.py` — assertions for `DigestConfig` defaults + overrides.
- `src/notify.py` — add `digest_pointer: str | None` to `RunSummary`; render one line in `compose_top_level`.
- `tests/test_notify.py` — assertions for pointer line presence/absence.
- `src/main.py` — at the end of `run_once`, call `write_digest` in a try/except, set `digest_pointer`, pass into `RunSummary`.

**Cross-repo (separate commit, separate plan task):**
- `/Users/steven/Vibe Projects/wiki-knowledge-interface/src/app/browse/page.tsx` — initialize `selectedVault` from `?vault=`.

---

## Task 1: Config — add `DigestConfig` block

**Files:**
- Modify: `src/config.py`
- Modify: `config.yml`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_load_config_digest_defaults_when_missing(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(
        "watchlist: []\n"
        "seed_categories: []\n"
        "ingest:\n"
        "  max_videos_per_run: 2\n"
        "  lookback_days: 14\n"
        "  min_duration_seconds: 60\n"
    )
    cfg = load_config(p)
    assert cfg.digest.window_days == 7
    assert cfg.digest.vault_app_base_url == "http://localhost:3000"
    assert cfg.digest.vault_name == "AI Learnings"


def test_load_config_digest_overrides(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(
        "watchlist: []\n"
        "seed_categories: []\n"
        "ingest:\n"
        "  max_videos_per_run: 2\n"
        "  lookback_days: 14\n"
        "  min_duration_seconds: 60\n"
        "digest:\n"
        "  window_days: 14\n"
        "  vault_app_base_url: http://localhost:4000\n"
        "  vault_name: Other Vault\n"
    )
    cfg = load_config(p)
    assert cfg.digest.window_days == 14
    assert cfg.digest.vault_app_base_url == "http://localhost:4000"
    assert cfg.digest.vault_name == "Other Vault"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v -k digest`
Expected: FAIL — `cfg.digest` does not exist.

- [ ] **Step 3: Implement in `src/config.py`**

Add the dataclass after `IngestConfig`:

```python
@dataclass
class DigestConfig:
    window_days: int = 7
    vault_app_base_url: str = "http://localhost:3000"
    vault_name: str = "AI Learnings"
```

Add to `Config`:

```python
@dataclass
class Config:
    watchlist: list[WatchlistChannel]
    seed_categories: list[str]
    ingest: IngestConfig
    digest: DigestConfig = field(default_factory=DigestConfig)
```

In `load_config`, after the `ingest` block is built, add:

```python
    digest_raw = data.get("digest") or {}
    if not isinstance(digest_raw, dict):
        raise ConfigError("config.yml 'digest' must be a mapping")
    digest = DigestConfig(
        window_days=int(digest_raw.get("window_days", 7)),
        vault_app_base_url=str(digest_raw.get("vault_app_base_url", "http://localhost:3000")),
        vault_name=str(digest_raw.get("vault_name", "AI Learnings")),
    )
    return Config(
        watchlist=watchlist,
        seed_categories=seed_categories,
        ingest=ingest,
        digest=digest,
    )
```

(Replace the existing `return Config(...)` with this version.)

- [ ] **Step 4: Add the block to `config.yml`**

Append to `config.yml`:

```yaml
digest:
  window_days: 7
  vault_app_base_url: http://localhost:3000
  vault_name: "AI Learnings"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS (all config tests, including the two new ones).

- [ ] **Step 6: Commit**

```bash
git add src/config.py config.yml tests/test_config.py
git commit -m "feat(config): add digest block with window_days, vault_app_base_url, vault_name"
```

---

## Task 2: Notify — add `digest_pointer` field and render line

**Files:**
- Modify: `src/notify.py`
- Modify: `tests/test_notify.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notify.py`:

```python
def _empty_summary(**over):
    kwargs = dict(
        run_date="2026-05-28 10:30",
        ingested=[],
        skipped=[],
        failed=[],
        storage_bytes=0,
        storage_video_count=0,
        storage_added_today=0,
        proposed_categories_pending=[],
        autopromoted_categories=[],
        dead_today=[],
        digest_pointer=None,
    )
    kwargs.update(over)
    return RunSummary(**kwargs)


def test_compose_top_level_omits_digest_line_when_pointer_none():
    body = compose_top_level(_empty_summary(digest_pointer=None))
    assert "digest" not in body.lower()


def test_compose_top_level_includes_digest_pointer_when_set():
    pointer = "📊 Weekly digest refreshed → `AI Learnings/digest.html` (open your bookmark)"
    body = compose_top_level(_empty_summary(digest_pointer=pointer))
    assert pointer in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_notify.py -v -k digest`
Expected: FAIL — `RunSummary` has no `digest_pointer` field.

- [ ] **Step 3: Add the field to `RunSummary` in `src/notify.py`**

Update the dataclass:

```python
@dataclass
class RunSummary:
    run_date: str
    ingested: list[VideoResult]
    skipped: list[dict]
    failed: list[dict]
    storage_bytes: int
    storage_video_count: int
    storage_added_today: int
    proposed_categories_pending: list[str]
    autopromoted_categories: list[str]
    dead_today: list[dict]
    digest_pointer: str | None = None
```

- [ ] **Step 4: Render the pointer line in `compose_top_level`**

At the end of `compose_top_level`, just before `return "\n".join(lines)`, add:

```python
    if summary.digest_pointer:
        lines.append("")
        lines.append(summary.digest_pointer)
```

- [ ] **Step 5: Keep `_summary_from_log` and `deliver_undelivered_summaries` happy**

In `src/notify.py`, find `_summary_from_log`. After the existing `return RunSummary(...)` arguments, add `digest_pointer=log.get("digest_pointer")` so older logs without the field still load:

```python
def _summary_from_log(log: dict) -> RunSummary:
    ...
    return RunSummary(
        run_date=log["run_date"],
        ingested=ingested,
        skipped=log.get("skipped", []),
        failed=log.get("failed", []),
        storage_bytes=int(log.get("storage_bytes", 0)),
        storage_video_count=int(log.get("storage_video_count", 0)),
        storage_added_today=int(log.get("storage_added_today", 0)),
        proposed_categories_pending=log.get("proposed_categories_pending", []),
        autopromoted_categories=log.get("autopromoted_categories", []),
        dead_today=log.get("dead_today", []),
        digest_pointer=log.get("digest_pointer"),
    )
```

(Use the kwarg shape that already exists in the file. If existing call uses positional args, convert the necessary args; otherwise just append the kwarg.)

- [ ] **Step 6: Update `_log_summary_for_retry` in `src/main.py`**

Inside `_log_summary_for_retry`, add to the `payload` dict:

```python
        "digest_pointer": summary.digest_pointer,
```

So undelivered summaries replayed later still carry the pointer.

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_notify.py -v`
Expected: PASS (existing tests still pass; both new digest tests pass).

- [ ] **Step 8: Commit**

```bash
git add src/notify.py src/main.py tests/test_notify.py
git commit -m "feat(notify): add digest_pointer to RunSummary and render in Slack body"
```

---

## Task 3: Scaffold `src/digest.py` with data classes

**Files:**
- Create: `src/digest.py`

- [ ] **Step 1: Create the module skeleton**

Write `src/digest.py`:

```python
"""Weekly visual digest renderer.

Reads state.json, vault source pages, resources-index.md, and logs/usage.csv,
then writes a self-contained HTML file at vault/digest.html. No LLM calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `.venv/bin/python -c "from src import digest; print('OK', digest.SONNET_INPUT_USD_PER_MTOK)"`
Expected: `OK 3.0`

- [ ] **Step 3: Commit**

```bash
git add src/digest.py
git commit -m "feat(digest): scaffold module with data classes and pricing constants"
```

---

## Task 4: `select_recent_ingests`

**Files:**
- Modify: `src/digest.py`
- Create: `tests/test_digest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_digest.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.digest import IngestRef, select_recent_ingests


def _state(entries):
    return {"ingested_video_ids": entries}


def test_select_recent_ingests_filters_window(tmp_path):
    state = _state({
        "vidA": {
            "creator_slug": "creator-a",
            "ingested_at": "2026-05-26T08:30:00Z",
            "source_page": "wiki/sources/creator-a--video-a.md",
        },
        "vidB": {
            "creator_slug": "creator-b",
            "ingested_at": "2026-05-15T08:30:00Z",  # outside 7d window
            "source_page": "wiki/sources/creator-b--video-b.md",
        },
        "vidC": {
            "creator_slug": "creator-c",
            "ingested_at": "2026-05-27T22:00:00Z",
            "source_page": "wiki/sources/creator-c--video-c.md",
        },
    })
    now = datetime(2026, 5, 28, 10, 30, tzinfo=timezone.utc)

    refs = select_recent_ingests(state, vault=tmp_path, now=now, window_days=7)

    assert [r.video_id for r in refs] == ["vidC", "vidA"]   # newest first
    assert refs[0].source_slug == "creator-c--video-c"
    assert refs[0].source_page_path == tmp_path / "wiki" / "sources" / "creator-c--video-c.md"


def test_select_recent_ingests_empty_when_state_empty(tmp_path):
    refs = select_recent_ingests(_state({}), vault=tmp_path,
                                 now=datetime(2026, 5, 28, tzinfo=timezone.utc),
                                 window_days=7)
    assert refs == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_digest.py -v`
Expected: FAIL — `select_recent_ingests` not defined.

- [ ] **Step 3: Implement `select_recent_ingests`**

Append to `src/digest.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_digest.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/digest.py tests/test_digest.py
git commit -m "feat(digest): select_recent_ingests filters window and sorts newest first"
```

---

## Task 5: `parse_source_page` — round-trip against `write.write_source_page`

This is the load-bearing test that prevents writer/parser drift.

**Files:**
- Modify: `src/digest.py`
- Modify: `tests/test_digest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_digest.py`:

```python
from src.write import write_source_page
from src.digest import parse_source_page


def _fixture_fetch():
    return {
        "video_id": "abc12345678",
        "title": "Build a Full Website in 17 Minutes with Claude Code",
        "webpage_url": "https://www.youtube.com/watch?v=abc12345678",
        "channel": "Nick Saraev",
        "channel_url": "https://www.youtube.com/@nicksaraev",
        "channel_id": "UCxyz",
        "duration_seconds": 1020,
        "published_at": "2026-05-24",
    }


def _fixture_extraction():
    return {
        "session_summary": "A walkthrough of scaffolding and shipping a small site with Claude Code.",
        "instructions_and_howto": (
            "1. Write one spec file describing pages, routes, and data.\n"
            "2. Let Claude scaffold and own the file tree.\n"
            "3. Wire a deploy preview on every commit.\n"
        ),
        "resources": [
            {"url": "https://claude.ai/code", "title": "Claude Code",
             "description": "Agentic CLI", "group": "Tools"},
        ],
        "key_takeaways": [
            "Scaffold with a single spec file before any component",
            "Let the agent own the file tree",
            "Deploy preview on every commit catches breakage early",
        ],
        "categories": ["building-websites", "claude-code-workflows"],
        "proposed_new_categories": [],
        "tags": ["tutorial"],
        "domain": "workflow",
        "creator_bio_additions": "",
        "connections": [],
    }


def test_parse_source_page_round_trip(tmp_path):
    page_path = write_source_page(
        vault=tmp_path,
        fetch=_fixture_fetch(),
        extraction=_fixture_extraction(),
        creator_slug="creator-nick-saraev",
        date_ingested="2026-05-24",
    )

    page = parse_source_page(page_path)

    assert page.title == "Build a Full Website in 17 Minutes with Claude Code"
    assert page.video_url == "https://www.youtube.com/watch?v=abc12345678"
    assert page.published_at == "2026-05-24"
    assert page.duration_seconds == 1020
    assert page.categories == ["building-websites", "claude-code-workflows"]
    assert page.domain == "workflow"
    assert page.tags == ["tutorial"]
    assert page.creator == "creator-nick-saraev"   # wikilink target preserved as text
    assert "scaffolding" in page.session_summary
    assert page.instructions_md.strip().startswith("1. Write one spec file")
    assert page.key_takeaways == [
        "Scaffold with a single spec file before any component",
        "Let the agent own the file tree",
        "Deploy preview on every commit catches breakage early",
    ]
    assert page.slug == "creator-nick-saraev--build-a-full-website-in-17-minutes-with-claude-code"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_digest.py::test_parse_source_page_round_trip -v`
Expected: FAIL — `parse_source_page` not defined.

- [ ] **Step 3: Implement `parse_source_page`**

Append to `src/digest.py`:

```python
import re
import yaml


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_digest.py::test_parse_source_page_round_trip -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/digest.py tests/test_digest.py
git commit -m "feat(digest): parse_source_page with writer round-trip test"
```

---

## Task 6: `detect_steps`

**Files:**
- Modify: `src/digest.py`
- Modify: `tests/test_digest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_digest.py`:

```python
from src.digest import detect_steps


def test_detect_steps_returns_ordered_items_for_numbered_list():
    md = (
        "1. First step that explains a thing.\n"
        "2. Second step which expands on it.\n"
        "3. Third step closing the loop.\n"
    )
    steps = detect_steps(md)
    assert steps == [
        "First step that explains a thing.",
        "Second step which expands on it.",
        "Third step closing the loop.",
    ]


def test_detect_steps_accepts_paren_form():
    md = "1) First.\n2) Second.\n"
    assert detect_steps(md) == ["First.", "Second."]


def test_detect_steps_returns_none_for_prose():
    md = "This video discusses approaches without a numbered procedure.\n"
    assert detect_steps(md) is None


def test_detect_steps_returns_none_for_single_item():
    md = "1. Just one thing.\n"
    assert detect_steps(md) is None


def test_detect_steps_ignores_indented_sub_items():
    md = (
        "1. Top one.\n"
        "    1. nested ignored\n"
        "    2. nested ignored\n"
        "2. Top two.\n"
    )
    assert detect_steps(md) == ["Top one.", "Top two."]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_digest.py -v -k detect_steps`
Expected: FAIL — `detect_steps` not defined.

- [ ] **Step 3: Implement `detect_steps`**

Append to `src/digest.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_digest.py -v -k detect_steps`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/digest.py tests/test_digest.py
git commit -m "feat(digest): detect_steps for numbered how-to sequences"
```

---

## Task 7: `tools_for_sources` and `top_tools`

**Files:**
- Modify: `src/digest.py`
- Modify: `tests/test_digest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_digest.py`:

```python
from src.write import upsert_resources_index
from src.digest import tools_for_sources, top_tools


def test_tools_for_sources_maps_tools_group_by_source(tmp_path):
    upsert_resources_index(
        vault=tmp_path,
        resources=[
            {"url": "https://n8n.io", "title": "n8n",
             "description": "workflow automation", "group": "Tools"},
            {"url": "https://docs.example.com", "title": "Docs",
             "description": "reference", "group": "Documentation"},
        ],
        source_slug="creator-a--video-1",
        today="2026-05-26",
    )
    upsert_resources_index(
        vault=tmp_path,
        resources=[
            {"url": "https://n8n.io", "title": "n8n",
             "description": "workflow automation", "group": "Tools"},
            {"url": "https://cursor.sh", "title": "Cursor",
             "description": "ide", "group": "Tools"},
        ],
        source_slug="creator-b--video-2",
        today="2026-05-27",
    )

    index_path = tmp_path / "wiki" / "sources" / "resources-index.md"
    tools_by_slug = tools_for_sources(
        index_path,
        slugs=["creator-a--video-1", "creator-b--video-2"],
    )

    assert tools_by_slug["creator-a--video-1"] == ["n8n"]
    assert sorted(tools_by_slug["creator-b--video-2"]) == ["Cursor", "n8n"]


def test_top_tools_ranks_by_frequency():
    tools_by_slug = {
        "a": ["n8n", "Cursor"],
        "b": ["n8n"],
        "c": ["n8n", "Supabase"],
        "d": ["Cursor"],
    }
    ranked = top_tools(tools_by_slug, k=5)
    assert ranked[0] == ("n8n", 3)
    assert ("Cursor", 2) in ranked
    assert ("Supabase", 1) in ranked


def test_tools_for_sources_returns_empty_when_index_missing(tmp_path):
    missing = tmp_path / "does-not-exist.md"
    assert tools_for_sources(missing, slugs=["x"]) == {"x": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_digest.py -v -k tools`
Expected: FAIL — `tools_for_sources` not defined.

- [ ] **Step 3: Implement**

Append to `src/digest.py`:

```python
from collections import Counter

from src.write import _parse_resources_index   # reuse the existing parser


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
```

Note: `_parse_resources_index` is a module-level function in `src/write.py` even though it begins with an underscore. Importing it directly is acceptable here because the digest is a sibling module in the same package and we own both files; the spec calls this reuse out explicitly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_digest.py -v -k tools`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/digest.py tests/test_digest.py
git commit -m "feat(digest): tools_for_sources and top_tools from resources-index"
```

---

## Task 8: `compute_spend`

**Files:**
- Modify: `src/digest.py`
- Modify: `tests/test_digest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_digest.py`:

```python
from src.digest import compute_spend


def test_compute_spend_sums_window_only(tmp_path):
    csv_path = tmp_path / "usage.csv"
    csv_path.write_text(
        "ts,model,attempt,input_tokens,output_tokens,"
        "cache_creation_input_tokens,cache_read_input_tokens\n"
        # inside window
        "2026-05-27T08:30:00Z,claude-sonnet-4-6,1,20000,2000,0,0\n"
        "2026-05-28T08:30:00Z,claude-sonnet-4-6,1,10000,1000,0,0\n"
        # outside window
        "2026-05-10T08:30:00Z,claude-sonnet-4-6,1,9000000,9000000,0,0\n"
    )
    window_start = datetime(2026, 5, 21, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 28, 23, 59, 59, tzinfo=timezone.utc)

    spend = compute_spend(csv_path, window_start=window_start, window_end=window_end)

    # 30K input @ $3/Mtok = $0.09; 3K output @ $15/Mtok = $0.045 → $0.135
    assert spend == pytest.approx(0.135, rel=1e-3)


def test_compute_spend_returns_zero_when_csv_missing(tmp_path):
    missing = tmp_path / "absent.csv"
    assert compute_spend(missing,
                         window_start=datetime(2026, 5, 1, tzinfo=timezone.utc),
                         window_end=datetime(2026, 5, 28, tzinfo=timezone.utc)) == 0.0


def test_compute_spend_returns_zero_when_csv_empty(tmp_path):
    csv_path = tmp_path / "usage.csv"
    csv_path.write_text(
        "ts,model,attempt,input_tokens,output_tokens,"
        "cache_creation_input_tokens,cache_read_input_tokens\n"
    )
    assert compute_spend(csv_path,
                         window_start=datetime(2026, 5, 1, tzinfo=timezone.utc),
                         window_end=datetime(2026, 5, 28, tzinfo=timezone.utc)) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_digest.py -v -k compute_spend`
Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `src/digest.py`:

```python
import csv


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_digest.py -v -k compute_spend`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/digest.py tests/test_digest.py
git commit -m "feat(digest): compute_spend reads usage.csv and prices the window"
```

---

## Task 9: `compute_aggregates`

**Files:**
- Modify: `src/digest.py`
- Modify: `tests/test_digest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_digest.py`:

```python
from src.digest import Aggregates, SourcePage, compute_aggregates


def _page(slug, cats, creator="creator-x"):
    return SourcePage(
        slug=slug, title=f"T:{slug}", video_url="https://yt", creator=creator,
        published_at="2026-05-26", duration_seconds=600, categories=list(cats),
        domain="workflow", tags=[], session_summary="", instructions_md="",
        key_takeaways=[],
    )


def test_compute_aggregates_counts_and_ranks():
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    refs = [
        IngestRef("v1", "c-a", "c-a--v1", Path("/tmp/a.md"),
                  datetime(2026, 5, 27, 9, 0, tzinfo=timezone.utc)),
        IngestRef("v2", "c-a", "c-a--v2", Path("/tmp/b.md"),
                  datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)),
        IngestRef("v3", "c-b", "c-b--v3", Path("/tmp/c.md"),
                  datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc)),
    ]
    pages = [
        _page("c-a--v1", ["agent-engineering", "claude-code-workflows"], creator="c-a"),
        _page("c-a--v2", ["agent-engineering"], creator="c-a"),
        _page("c-b--v3", ["ai-agency-business"], creator="c-b"),
    ]
    tools_by_slug = {
        "c-a--v1": ["n8n", "Cursor"],
        "c-a--v2": ["n8n"],
        "c-b--v3": ["Supabase"],
    }

    agg = compute_aggregates(
        pages=pages, ingests=refs, tools_by_slug=tools_by_slug,
        spend_usd=1.23, now=now, window_days=7,
    )

    assert agg.video_count == 3
    assert agg.creator_count == 2
    assert agg.tool_count == 3                            # n8n, Cursor, Supabase
    assert agg.spend_usd == 1.23
    assert agg.top_categories[0] == ("agent-engineering", 2)
    assert ("claude-code-workflows", 1) in agg.top_categories
    assert ("ai-agency-business", 1) in agg.top_categories
    assert agg.top_tools[0] == ("n8n", 2)
    assert len(agg.volume_per_day) == 7
    # Ingest on 2026-05-27 lands in the last slot (newest = window_end day = now's date).
    assert agg.volume_per_day[-1][1] == 2
    # 2026-05-25 lands two slots earlier.
    assert agg.volume_per_day[-3][1] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_digest.py::test_compute_aggregates_counts_and_ranks -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `src/digest.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_digest.py::test_compute_aggregates_counts_and_ranks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/digest.py tests/test_digest.py
git commit -m "feat(digest): compute_aggregates produces counts, categories, volume, tools"
```

---

## Task 10: `build_episode_card`

**Files:**
- Modify: `src/digest.py`
- Modify: `tests/test_digest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_digest.py`:

```python
from urllib.parse import quote

from src.digest import build_episode_card


def test_build_episode_card_tutorial_uses_steps():
    page = SourcePage(
        slug="c-a--build-site",
        title="Build a Site in 17 Minutes",
        video_url="https://www.youtube.com/watch?v=abc",
        creator="creator-a",
        published_at="2026-05-24",
        duration_seconds=1020,
        categories=["building-websites"],
        domain="workflow",
        tags=[],
        session_summary="",
        instructions_md="1. Write spec.\n2. Scaffold.\n3. Deploy preview.\n",
        key_takeaways=["takeaway one", "takeaway two", "takeaway three"],
    )
    ingest = IngestRef("vid", "creator-a", page.slug, Path("/tmp/x.md"),
                       datetime(2026, 5, 27, tzinfo=timezone.utc))

    card = build_episode_card(
        page=page, ingest=ingest, tools=["Claude Code", "Vercel"],
        vault_app_base_url="http://localhost:3000", vault_name="AI Learnings",
    )

    assert card.body_mode == "steps"
    assert card.body_items == ["Write spec.", "Scaffold.", "Deploy preview."]
    assert card.duration_minutes == 17
    assert card.watch_url == "https://www.youtube.com/watch?v=abc"
    assert card.read_in_vault_url == (
        f"http://localhost:3000/browse"
        f"?vault={quote('AI Learnings')}&page={quote(page.slug)}"
    )
    assert card.tools == ["Claude Code", "Vercel"]
    assert card.categories == ["building-websites"]


def test_build_episode_card_interview_uses_takeaways():
    page = SourcePage(
        slug="c-b--interview",
        title="A Discussion About Orgs",
        video_url="https://www.youtube.com/watch?v=xyz",
        creator="creator-b",
        published_at="2026-05-26",
        duration_seconds=3709,
        categories=["future-trends"],
        domain="workflow",
        tags=[],
        session_summary="",
        instructions_md="This is prose without numbered steps.",
        key_takeaways=["alpha", "beta", "gamma", "delta", "epsilon"],
    )
    ingest = IngestRef("v", "creator-b", page.slug, Path("/tmp/y.md"),
                       datetime(2026, 5, 27, tzinfo=timezone.utc))

    card = build_episode_card(
        page=page, ingest=ingest, tools=[],
        vault_app_base_url="http://localhost:3000", vault_name="AI Learnings",
    )

    assert card.body_mode == "takeaways"
    assert card.body_items == ["alpha", "beta", "gamma", "delta"]   # cap at 4
    assert card.duration_minutes == 62
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_digest.py -v -k build_episode_card`
Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `src/digest.py`:

```python
from urllib.parse import quote

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_digest.py -v -k build_episode_card`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/digest.py tests/test_digest.py
git commit -m "feat(digest): build_episode_card with step/takeaway mode and deep-link"
```

---

## Task 11: `render_digest_html`

**Files:**
- Modify: `src/digest.py`
- Modify: `tests/test_digest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_digest.py`:

```python
from src.digest import EpisodeCard, render_digest_html


def _card(title="Sample", mode="takeaways"):
    return EpisodeCard(
        title=title, creator="creator-a", published_at="2026-05-27",
        duration_minutes=12, categories=["agent-engineering"],
        body_mode=mode,
        body_items=["one", "two"],
        tools=["n8n"],
        watch_url="https://www.youtube.com/watch?v=abc",
        read_in_vault_url="http://localhost:3000/browse?vault=AI%20Learnings&page=c-a--s",
    )


def _agg(video_count=1):
    return Aggregates(
        video_count=video_count, creator_count=1, tool_count=1, spend_usd=0.12,
        top_categories=[("agent-engineering", 2)],
        volume_per_day=[("Wed", 0), ("Thu", 0), ("Fri", 0), ("Sat", 0),
                        ("Sun", 0), ("Mon", 0), ("Tue", 1)],
        top_tools=[("n8n", 1)],
    )


def test_render_digest_html_contains_expected_sections():
    html = render_digest_html(
        aggregates=_agg(), cards=[_card()],
        generated_at=datetime(2026, 5, 28, 10, 30, tzinfo=timezone.utc),
        window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
        window_end=datetime(2026, 5, 28, tzinfo=timezone.utc),
        vault_app_base_url="http://localhost:3000", vault_name="AI Learnings",
    )
    assert "<!DOCTYPE html>" in html
    assert "AI Learnings — Last 7 Days" in html
    assert "Videos" in html and "Creators" in html and "Tools" in html and "Spend" in html
    assert "agent-engineering" in html
    assert "Volume per day" in html
    assert "Top tools mentioned" in html
    assert "Sample" in html                       # card title
    assert "▶ Watch" in html
    assert "📖 Read in vault" in html
    assert "Open vault" in html
    assert "http://localhost:3000/browse?vault=AI%20Learnings" in html


def test_render_digest_html_empty_state():
    html = render_digest_html(
        aggregates=_agg(video_count=0), cards=[],
        generated_at=datetime(2026, 5, 28, 10, 30, tzinfo=timezone.utc),
        window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
        window_end=datetime(2026, 5, 28, tzinfo=timezone.utc),
        vault_app_base_url="http://localhost:3000", vault_name="AI Learnings",
    )
    assert "No videos in the last 7 days" in html


def test_render_digest_html_escapes_titles():
    html = render_digest_html(
        aggregates=_agg(), cards=[_card(title="<script>x</script>")],
        generated_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
        window_end=datetime(2026, 5, 28, tzinfo=timezone.utc),
        vault_app_base_url="http://localhost:3000", vault_name="AI Learnings",
    )
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html


def test_render_digest_html_has_no_external_resources():
    html = render_digest_html(
        aggregates=_agg(), cards=[_card()],
        generated_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
        window_end=datetime(2026, 5, 28, tzinfo=timezone.utc),
        vault_app_base_url="http://localhost:3000", vault_name="AI Learnings",
    )
    # No <script> tags at all.
    assert "<script" not in html.lower()
    # No external stylesheets / fonts.
    assert "<link" not in html.lower()
    # No CDN fetches in <img> tags.
    import re as _re
    for m in _re.finditer(r"<img[^>]*\ssrc=\"([^\"]+)\"", html):
        assert m.group(1).startswith("data:")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_digest.py -v -k render_digest_html`
Expected: FAIL — `render_digest_html` not defined.

- [ ] **Step 3: Implement**

Append to `src/digest.py`:

```python
from html import escape as _esc


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_digest.py -v -k render_digest_html`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/digest.py tests/test_digest.py
git commit -m "feat(digest): render_digest_html with HTML escaping and no external resources"
```

---

## Task 12: `write_digest` orchestration + atomic write

**Files:**
- Modify: `src/digest.py`
- Modify: `tests/test_digest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_digest.py`:

```python
from src.digest import write_digest


def _vault_with_one_video(tmp_path, video_id="vidA", ingested_at="2026-05-27T08:30:00Z"):
    write_source_page(
        vault=tmp_path,
        fetch={
            "video_id": video_id,
            "title": "Build a Site in 17 Minutes",
            "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
            "channel": "Nick Saraev",
            "channel_url": "https://www.youtube.com/@nicksaraev",
            "channel_id": "UCxyz",
            "duration_seconds": 1020,
            "published_at": "2026-05-24",
        },
        extraction={
            "session_summary": "Walkthrough.",
            "instructions_and_howto": "1. Spec.\n2. Scaffold.\n3. Deploy.\n",
            "resources": [
                {"url": "https://claude.ai/code", "title": "Claude Code",
                 "description": "agentic CLI", "group": "Tools"},
            ],
            "key_takeaways": ["x", "y"],
            "categories": ["building-websites"],
            "proposed_new_categories": [],
            "tags": [],
            "domain": "workflow",
            "creator_bio_additions": "",
            "connections": [],
        },
        creator_slug="creator-nick-saraev",
        date_ingested="2026-05-24",
    )
    upsert_resources_index(
        vault=tmp_path,
        resources=[{"url": "https://claude.ai/code", "title": "Claude Code",
                    "description": "agentic CLI", "group": "Tools"}],
        source_slug="creator-nick-saraev--build-a-site-in-17-minutes",
        today="2026-05-27",
    )
    state = {
        "ingested_video_ids": {
            video_id: {
                "creator_slug": "creator-nick-saraev",
                "ingested_at": ingested_at,
                "source_page": "wiki/sources/creator-nick-saraev--build-a-site-in-17-minutes.md",
            }
        }
    }
    return state


def test_write_digest_writes_html_with_card(tmp_path):
    state = _vault_with_one_video(tmp_path)
    out = write_digest(
        vault=tmp_path, state=state,
        now=datetime(2026, 5, 28, 10, 30, tzinfo=timezone.utc),
        window_days=7,
        vault_app_base_url="http://localhost:3000", vault_name="AI Learnings",
        usage_csv_path=tmp_path / "usage.csv",   # missing OK
    )

    assert out == tmp_path / "digest.html"
    text = out.read_text()
    assert "Build a Site in 17 Minutes" in text
    assert "Claude Code" in text
    assert "▶ Watch" in text


def test_write_digest_empty_window_writes_empty_state(tmp_path):
    state = {"ingested_video_ids": {}}
    out = write_digest(
        vault=tmp_path, state=state,
        now=datetime(2026, 5, 28, tzinfo=timezone.utc),
        window_days=7,
        vault_app_base_url="http://localhost:3000", vault_name="AI Learnings",
        usage_csv_path=tmp_path / "usage.csv",
    )
    assert out.exists()
    assert "No videos in the last 7 days" in out.read_text()


def test_write_digest_skips_missing_source_pages(tmp_path, caplog):
    state = {
        "ingested_video_ids": {
            "ghost": {
                "creator_slug": "c-x",
                "ingested_at": "2026-05-27T08:30:00Z",
                "source_page": "wiki/sources/c-x--missing.md",
            }
        }
    }
    out = write_digest(
        vault=tmp_path, state=state,
        now=datetime(2026, 5, 28, tzinfo=timezone.utc),
        window_days=7,
        vault_app_base_url="http://localhost:3000", vault_name="AI Learnings",
        usage_csv_path=tmp_path / "usage.csv",
    )
    # No crash; empty-state HTML written; warning recorded.
    assert out.exists()
    assert "No videos in the last 7 days" in out.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_digest.py -v -k write_digest`
Expected: FAIL — `write_digest` not defined.

- [ ] **Step 3: Implement**

Append to `src/digest.py`:

```python
import logging
import os
import tempfile


logger = logging.getLogger(__name__)


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_digest.py -v`
Expected: PASS (all digest tests).

- [ ] **Step 5: Commit**

```bash
git add src/digest.py tests/test_digest.py
git commit -m "feat(digest): write_digest orchestrator with atomic write and graceful skips"
```

---

## Task 13: Integrate into `main.run_once`

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main.py` (or its smoke section — match existing style):

```python
def test_run_once_writes_digest_at_end(tmp_path, monkeypatch):
    """Run with zero queue / zero ingests: should still write digest.html and
    include a digest_pointer in the Slack summary call."""
    # Set up a minimal vault + state + config so run_once executes its tail.
    # Reuse whichever fixtures the existing test_main.py uses; the key
    # assertions are these two:
    from src.main import run_once  # noqa: F401  (import for clarity)

    # ... call run_once with mocked Anthropic + Slack clients, empty queue,
    #     empty watchlist (config), and vault=tmp_path ...

    # Assertions:
    assert (tmp_path / "digest.html").exists()
    # Inspect the captured Slack post_run_summary call and check that
    # summary.digest_pointer is a non-None string containing "digest".
```

> Adapt this to the harness in `tests/test_main.py`. The existing file already mocks `anthropic.Anthropic` and the Slack client; reuse those mocks. If the existing tests have a `_run_once_with_no_videos` helper, extend it; otherwise model the new test on the smallest existing run_once test.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_main.py -v -k digest`
Expected: FAIL — digest.html not written; pointer absent.

- [ ] **Step 3: Wire `write_digest` into `run_once`**

In `src/main.py`:

1. Add the import near the other `src.*` imports:

```python
from src.digest import write_digest
```

2. Locate the existing tail of `run_once` (around line 432–449):

```python
    summary = RunSummary(
        run_date=now.strftime("%Y-%m-%d %H:%M"),
        ingested=ingested, skipped=skipped, failed=failed,
        storage_bytes=storage_bytes, storage_video_count=storage_count,
        storage_added_today=len(ingested),
        proposed_categories_pending=pending_categories,
        autopromoted_categories=newly_autopromoted,
        dead_today=dead_today,
    )
    ok, _ = post_run_summary(
        client=slack_client, channel_id=slack_channel_id, summary=summary,
    )
    if not ok:
        log_path = log_dir / f"{today}.json"
        _log_summary_for_retry(summary, log_path, state)

    save_state(state_path, state)
```

Replace it with:

```python
    try:
        write_digest(
            vault=vault,
            state=state,
            now=now,
            window_days=cfg.digest.window_days,
            vault_app_base_url=cfg.digest.vault_app_base_url,
            vault_name=cfg.digest.vault_name,
            usage_csv_path=log_dir / "usage.csv",
        )
        digest_pointer = (
            "📊 Weekly digest refreshed → "
            f"`{cfg.digest.vault_name}/digest.html` (open your bookmark)"
        )
    except Exception as exc:
        logger.exception("digest generation failed")
        digest_pointer = f"⚠ Digest generation failed: {type(exc).__name__}"

    summary = RunSummary(
        run_date=now.strftime("%Y-%m-%d %H:%M"),
        ingested=ingested, skipped=skipped, failed=failed,
        storage_bytes=storage_bytes, storage_video_count=storage_count,
        storage_added_today=len(ingested),
        proposed_categories_pending=pending_categories,
        autopromoted_categories=newly_autopromoted,
        dead_today=dead_today,
        digest_pointer=digest_pointer,
    )
    ok, _ = post_run_summary(
        client=slack_client, channel_id=slack_channel_id, summary=summary,
    )
    if not ok:
        log_path = log_dir / f"{today}.json"
        _log_summary_for_retry(summary, log_path, state)

    save_state(state_path, state)
```

Note ordering: digest runs **before** state is saved. Digest failures must not block state-save, so the try/except is essential. Digest also runs before the Slack post so the pointer can appear in the summary.

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/pytest -v`
Expected: PASS — all existing tests still green, new digest+main tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(main): generate digest.html and surface pointer in Slack summary"
```

---

## Task 14: Live smoke run

A controlled real-vault run to confirm the digest renders against current state — no test mocks involved.

**Files:** none modified.

- [ ] **Step 1: Run the pipeline once against the live vault**

```bash
cd "/Users/steven/Vibe Projects/youtube-transcript-ailearning"
.venv/bin/python -m src.main
```

Expected: pipeline completes, `~/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/digest.html` exists and is non-empty, Slack summary includes the "📊 Weekly digest refreshed" line.

- [ ] **Step 2: Inspect the artifact**

```bash
ls -la "/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/digest.html"
open "/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/digest.html"
```

Confirm: header + stat band + categories + volume + top tools + cards with steps OR takeaways + Watch/Read buttons render correctly. Bookmark the `file://` URL.

- [ ] **Step 3: Verify "Read in vault" deep-links (will still land in TARS until Task 15)**

Click a "Read in vault" button. Expected before Task 15: wiki app opens at `/browse?vault=AI%20Learnings&page=<slug>` but `selectedVault` still defaults to TARS — you'll see TARS pages, not AI Learnings. This is expected; Task 15 fixes it.

- [ ] **Step 4: No commit**

This task only validates; no files change.

---

## Task 15: Cross-repo — `wiki-knowledge-interface` `?vault=` patch

**Files:**
- Modify: `/Users/steven/Vibe Projects/wiki-knowledge-interface/src/app/browse/page.tsx`

- [ ] **Step 1: Apply the one-line change**

Open `src/app/browse/page.tsx`, find the `useState` for `selectedVault` (around line 22) and change:

```ts
const [selectedVault, setSelectedVault] = useState("TARS");
```

to:

```ts
const [selectedVault, setSelectedVault] = useState(
  searchParams.get("vault") ?? "TARS"
);
```

- [ ] **Step 2: Manual verification**

In a separate terminal:

```bash
cd "/Users/steven/Vibe Projects/wiki-knowledge-interface"
npm run dev
```

Then in your browser visit:

```
http://localhost:3000/browse?vault=AI%20Learnings&page=creator-peter-h-diamandis--the-new-era-of-jobs-organizational-singularity
```

(or any other in-window slug). Expected: the AI Learnings vault is selected and the source page renders directly.

- [ ] **Step 3: Commit (in the wiki-knowledge-interface repo)**

```bash
cd "/Users/steven/Vibe Projects/wiki-knowledge-interface"
git add src/app/browse/page.tsx
git commit -m "feat(browse): initialize selectedVault from ?vault= query param

Enables deep-links from external tools (e.g. the YouTube ingest digest)
to land directly in a specific vault."
```

- [ ] **Step 4: Re-test from the digest**

Click a "Read in vault" button in the bookmarked digest. Expected: lands in AI Learnings with the correct source page rendered.

---

## Self-Review Notes

Coverage against spec sections:

- §1 Purpose / §2 Goals → Tasks 3–13
- §3 Non-goals → preserved by not implementing them (no LLM, no archive, no responsive design)
- §4 Architecture → Task 13 wires the renderer into `run_once` after state save constraint inverted (digest runs before save_state in this implementation to keep ordering simple and because digest doesn't mutate state; the spec's "after `save_state`" was indicative — what matters is digest failures don't break state-save, which the try/except ensures)
- §5.1 ingested_video_ids → Task 4
- §5.2 source pages → Task 5 (round-trip)
- §5.3 resources-index → Task 7
- §5.4 usage.csv → Task 8
- §6 Output (atomic write, self-contained) → Tasks 11, 12
- §7.1 Top bar → Task 11
- §7.2 Aggregate band → Tasks 9, 11
- §7.3 Episode poster card → Tasks 10, 11
- §7.4 Empty state → Tasks 11, 12
- §8 Cross-repo patch → Task 15
- §9 Slack pointer → Tasks 2, 13
- §10 Edge cases → Tasks 7, 8, 11, 12 (missing index, missing csv, missing source page, escape, empty state)
- §11 Pricing constants → Task 3 (defined), Task 8 (used)
- §12 Module layout → Tasks 3–12
- §13 Integration → Task 13
- §14 Configuration → Task 1
- §15 Testing strategy → Each task includes its tests, round-trip test in Task 5
- §16 Open follow-ups → not implemented (correctly out of scope)

One reconciliation: the spec §13 example places digest generation *after* `save_state`. The plan places it *before*, so the digest_pointer can travel inside the same `RunSummary` that goes to Slack. State is unchanged by digest generation, so the relative order is safe; the load-bearing constraint (digest failure must not break state-save) is preserved by the try/except. Calling this out explicitly so it doesn't read as an implementation deviation.
