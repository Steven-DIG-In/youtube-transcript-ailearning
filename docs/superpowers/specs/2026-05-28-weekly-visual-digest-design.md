# Weekly Visual Digest — Design

## 1. Purpose

Render a self-contained HTML "digest" page summarising the last 7 days of YouTube ingests so Steven can triage content volume at a glance. Generated deterministically at the end of every daily `run_once`; opened locally via a bookmarked `file://` URL; deep-links each item back into the Wiki Knowledge Interface for full reading.

## 2. Goals

- One bookmarkable artifact that always reflects the last 7 days, regardless of whether today had new ingests.
- Visual hierarchy that supports triage: aggregate band on top, per-episode poster cards below.
- No new LLM calls. Re-use the already-extracted structured data (summaries, takeaways, resources, categories).
- Offline-friendly and dependency-free: pure HTML + inline CSS + inline SVG, no CDN, no external JS.
- Round-trip safe: digest parser is tested against output of `src/write.py`, so the two cannot drift.

## 3. Non-goals

- LLM-driven narrative synthesis ("editor's letter" / cross-video themes). The aggregate widgets convey theme implicitly.
- Concept synthesis across the vault (Lane C, out of scope).
- A new web service or daemon. The digest is a static file.
- Dated archive of past digests. The single `digest.html` is overwritten each run.
- Mobile responsive design. Desktop-only is acceptable.
- A clickable Slack link. The Slack pointer references the local file path; see §9.

## 4. Architecture

New module `src/digest.py`, called from `src/main.run_once` after `save_state`. It runs unconditionally on every daily launchd execution (10:30) — i.e. also on days with zero new ingests.

```
state.json
vault/wiki/sources/*.md       ─┐
vault/wiki/sources/             ├──▶  src/digest.py  ──▶  vault/digest.html
  resources-index.md            │                         (atomic write)
logs/usage.csv                 ─┘                              │
                                                               ▼
                                                  Slack daily summary
                                                  (appended pointer line)
```

Generation is deterministic — same inputs produce the same HTML. No network calls during render.

## 5. Data sources

### 5.1 `state.json.ingested_video_ids`
Shape per entry: `{creator_slug, ingested_at (ISO 8601 UTC, "Z" suffix), source_page (vault-relative path)}`. The digest filters by `ingested_at >= now_utc - window_days` and sorts newest first. All windowing math is done in UTC; the human-readable date range in the header is rendered in local time for the user's reading convenience.

### 5.2 Vault source pages (`vault/wiki/sources/{creator_slug}--{video_slug}.md`)
Source pages are written by `src/write.write_source_page` and have a deterministic shape:

- YAML frontmatter: `title`, `video_id`, `video_url`, `creator` (wikilink), `published_at` (YYYY-MM-DD), `duration_seconds` (int), `categories` (list), `domain`, `tags`, `date_ingested`.
- Sections: `## Session Summary`, `## Instructions & How-To`, `## Resources Mentioned`, `## Key Takeaways`, `## Connections`.

The digest parser reads frontmatter via PyYAML and section bodies by header-anchored regex.

### 5.3 `vault/wiki/sources/resources-index.md`
Source pages render resources **flat** (no group label). Tools/Documentation/Articles grouping lives only in `resources-index.md`, with backlinks `[[source-slug]]`. The digest reuses `src.write._parse_resources_index` to find Tools-group entries that backlink to each in-window source slug.

### 5.4 `logs/usage.csv`
Per-Anthropic-call rows with `ts` (ISO 8601 UTC), `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`. Spend stat = sum of rows whose `ts` falls in the same UTC window as §5.1, priced with constants (see §11).

## 6. Output

- Path: `{VAULT_PATH}/digest.html` (vault root, alongside `index.md` and `log.md`).
- Write: atomic via tempfile + `os.replace` (mirrors `src.write._atomic_write`).
- Self-contained: single HTML file. All CSS inline in `<style>`. No `<script>`. No external `<link>` or font imports.
- All injected text passes through `html.escape` to prevent broken markup from titles, takeaways, or descriptions.

## 7. Page layout

### 7.1 Top bar
- Title: "AI Learnings — Last 7 Days"
- Subtitle: `{start_date}–{end_date} · {N} videos · {M} creators · generated {timestamp}`
- Top-right button: **⤢ Open vault** → `http://localhost:3000/browse?vault=AI%20Learnings`

### 7.2 Aggregate band (all four widgets)

| Widget | Source | Notes |
|---|---|---|
| **Stats** — Videos / Creators / Tools / Spend | state + resources-index + usage.csv | All counts scoped to the 7-day window |
| **Top categories** | source pages `categories` frontmatter | Horizontal bars, top 5 by frequency |
| **Volume per day** | `ingested_at` dates | 7-bar mini chart, weekday labels |
| **Top tools mentioned** | resources-index Tools group | Top 5 entries by # of in-window source backlinks |

### 7.3 Episode gallery — Poster card

One card per in-window video, newest first. Layout:

- Hook (top-right): big number = `round(duration_seconds / 60)` minutes; label "minutes".
- Chip row: category chips (color A) + duration chip (color B).
- Title (h3, max-width 74% to leave space for hook).
- Creator + published date line.
- **Body** — conditional:
  - **Numbered steps** if `Instructions & How-To` parses as an ordered list (regex: lines matching `^\s*\d+[.)] ` at top level, ≥2 such lines).
  - **Plain takeaways** (▸ bullets) otherwise, drawn from `## Key Takeaways`.
  - Cap at 4 items either way.
- Tool chips: Tools-group resources backlinked to this source slug, max 6.
- Buttons:
  - **▶ Watch** → frontmatter `video_url`
  - **📖 Read in vault** → `http://localhost:3000/browse?vault=AI%20Learnings&page={source-slug}`

### 7.4 Empty state

If zero videos in window: aggregate band renders with zeros; episode gallery is replaced by a single muted line "No videos in the last 7 days." The file is still written.

## 8. Cross-repo dependency — Wiki app `?vault=` patch

The "Read in vault" and "Open vault" links require `wiki-knowledge-interface/src/app/browse/page.tsx` to initialize `selectedVault` from `?vault=`. Today (`useState("TARS")`) it ignores the query param and always defaults to TARS, which would point Read-in-vault at the wrong vault.

Required change (one line):

```ts
const [selectedVault, setSelectedVault] = useState(searchParams.get("vault") ?? "TARS");
```

Tracked as a separate commit in the `wiki-knowledge-interface` repo. Until it lands, the deep-links still navigate (and `?page=` resolves), but the user lands in the TARS vault and has to manually switch. Acceptable degradation; the digest itself does not depend on the patch shipping first.

## 9. Slack pointer

Append one line to the existing daily Slack summary (built in `src/notify.py` via `post_run_summary`):

> 📊 Weekly digest refreshed → `AI Learnings/digest.html` (open your bookmark)

Caveat: Slack strips `file://` URLs, so this is informational text, not a clickable link. The user opens their pre-saved file:// bookmark in the browser.

If `digest.py` raises during generation, the Slack summary still posts but with the pointer line replaced by a single ⚠ line:

> ⚠ Digest generation failed: `{error class}` — see logs.

Digest failure must never block state-save or summary delivery.

## 10. Edge cases

- **Source page missing** (referenced in state but file deleted): skip the entry, log a warning, continue.
- **Source page missing sections** (older format): degrade gracefully — empty takeaways, no step detection, etc.
- **`resources-index.md` missing or empty**: tool chips empty across the board; widget shows "—".
- **`logs/usage.csv` missing or empty**: spend shows "$0.00".
- **No how-to sequence in tutorial**: fall back to plain takeaways. Detection threshold: ≥2 top-level numbered list items.
- **All four widgets zero**: header band renders normally with zeros (don't suppress).
- **HTML in titles/takeaways**: escaped via `html.escape`; never trust-as-is.

## 11. Pricing constants

Module-level constants in `src/digest.py`:

```python
SONNET_INPUT_USD_PER_MTOK = 3.00
SONNET_OUTPUT_USD_PER_MTOK = 15.00
```

Spend formula (per row in usage.csv within window):

```
cost = input_tokens / 1e6 * SONNET_INPUT_USD_PER_MTOK
     + output_tokens / 1e6 * SONNET_OUTPUT_USD_PER_MTOK
```

Cache-creation and cache-read columns exist in the CSV for forward-compat but are zero today (prompt caching was removed in commit `7772d9a` — sub-1024-token static block); they are not yet priced. If caching is re-introduced, extend the formula here.

## 12. Module layout

`src/digest.py`:

```
# Data structures
@dataclass IngestRef               # video_id, creator_slug, source_slug, ingested_at, source_page_path
@dataclass SourcePage              # frontmatter fields + parsed sections
@dataclass EpisodeCard             # rendered fields ready for templating
@dataclass Aggregates              # counts, category dist, volume-per-day, top tools, spend

# Pure functions
select_recent_ingests(state, now, window_days=7) -> list[IngestRef]
parse_source_page(path: Path) -> SourcePage
detect_steps(instructions_md: str) -> list[str] | None
tools_for_sources(index_path: Path, slugs: list[str]) -> dict[str, list[str]]
top_tools(tools_by_slug: dict, k: int = 5) -> list[tuple[str, int]]
compute_spend(usage_csv_path: Path, window_start: datetime, window_end: datetime) -> float
compute_aggregates(pages, ingests, tools_by_slug, spend) -> Aggregates
build_episode_card(page, ingest, tools, vault_app_base_url: str, vault_name: str) -> EpisodeCard
render_digest_html(aggregates, cards, generated_at, window_start, window_end, vault_app_base_url, vault_name) -> str

# Orchestration / IO
write_digest(*, vault: Path, state: dict, now: datetime, window_days: int, vault_app_base_url: str, vault_name: str, usage_csv_path: Path) -> Path
```

All HTML rendering is plain f-strings + a small list of helpers; no template engine.

## 13. Integration with `main.run_once`

After `save_state(state_path, state)` at the end of `run_once`, wrap the digest call in try/except so failures don't break the run:

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
    digest_pointer = "📊 Weekly digest refreshed → `AI Learnings/digest.html` (open your bookmark)"
except Exception as exc:
    logger.exception("digest generation failed")
    digest_pointer = f"⚠ Digest generation failed: {type(exc).__name__}"
```

Pass `digest_pointer` into `post_run_summary` so it appears in the Slack body. The Slack template adds one new line at the bottom of the summary block.

## 14. Configuration

New `digest` block in `config.yml`:

```yaml
digest:
  window_days: 7
  vault_app_base_url: http://localhost:3000
  vault_name: "AI Learnings"
```

Loaded into the existing `Config` dataclass with sensible defaults if absent (window_days=7, base_url=http://localhost:3000, vault_name="AI Learnings").

## 15. Testing strategy

Unit tests under `tests/test_digest.py`:

- `test_select_recent_ingests_filters_window` — fixture state with ingested_at across 14 days; expect only ≤7-day entries, newest first.
- `test_parse_source_page_from_writer_output` — call `src.write.write_source_page` to produce a real page, then `parse_source_page` to read it back. Asserts the digest parser cannot drift from the writer.
- `test_detect_steps_finds_numbered_sequence` — feed a Markdown "1. … 2. … 3. …" block; expect ordered steps.
- `test_detect_steps_returns_none_for_prose` — feed prose paragraph; expect `None`.
- `test_tools_for_sources_uses_resources_index` — fixture resources-index.md → assert Tools-group entries map by source slug.
- `test_compute_spend_sums_window_only` — usage.csv with rows inside and outside window; expect only window rows priced.
- `test_compute_aggregates_counts_correctly` — small fixture set.
- `test_render_digest_html_contains_all_sections` — smoke: title, all 4 widgets, ≥1 card, both buttons present.
- `test_render_digest_html_escapes_titles` — title containing `<script>` is escaped in output.
- `test_render_digest_html_has_no_external_resources` — regex-assert no `http://`/`https://` in `<link>`/`<script>`/`<img>` tags, no CDN imports. (URLs in `href` for Watch / Read-in-vault are expected and exempt.)
- `test_write_digest_empty_window_writes_empty_state` — zero in-window videos: file still written, contains the empty-state copy.
- `test_write_digest_atomic` — temp file removed if the rename target exists midway (basic atomicity check).

The round-trip parser test is the load-bearing safeguard against the project's known "mocks hide real shapes" gap: if `write.py`'s output format ever changes, the digest parser test breaks loudly.

## 16. Open follow-ups (not blocking)

- After a few weeks of real digests, decide whether the **Volume per day** widget earns its slot or gets dropped (lowest a-priori signal of the four).
- Once `?vault=` deep-link lands in the wiki app, consider extending it to also accept `?vault_select=` for vault switching from anywhere in the app — out of scope here.
- If caching is reintroduced, extend §11 spend formula and add a "cache hit %" stat to the header band.
