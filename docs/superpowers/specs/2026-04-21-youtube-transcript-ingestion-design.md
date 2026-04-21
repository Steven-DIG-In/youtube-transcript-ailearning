# YouTube Transcript → AI Learnings Ingestion — Design

**Date:** 2026-04-21
**Author:** Steven (with Claude brainstorming)
**Status:** Design approved, pending implementation plan
**Project path:** `/Users/steven/Vibe Projects/youtube-transcript-ailearning/`
**Output vault:** `/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/`

---

## 1. Purpose

Ingest YouTube video transcripts into the AI Learnings wiki vault on a daily cron. Each run fetches new videos from a curated watchlist plus ad-hoc URLs submitted via a local file and a Slack channel, extracts structured learning content from each transcript via a single Claude call, and writes one source page + one creator page + new rows in a shared resources index per video. Summarises the run to Slack.

The pipeline produces the bounded, mechanical artifacts (source + creator + resources). It does **not** produce concept pages — those are synthesised manually in directed Claude sessions as a separate workflow (Lane C, out of scope for this design).

## 2. Goals

- Every YouTube video from watchlist / Slack / manual queue gets a source page in the vault with filtered learning content, categorised and cross-linked, within ~24 hours of publish.
- Each creator gets an entity page on first sighting, updated on subsequent sightings with append-only bio additions.
- Every resource URL mentioned (description + transcript name-drops) lands in a single searchable resources index.
- A daily Slack summary surfaces what was ingested, what failed, what needs your review (new categories, concept candidates), and raw transcript storage footprint.
- Idempotent and resumable: any failure mode has a defined "what the next run does about it" behaviour. No silent swallowing.

## 3. Non-goals (Lane B or Lane C — deferred)

### Lane B — v1.x follow-ons (same project, no redesign)
- Podcast ingestion adapter (RSS + Whisper, reuses extraction schema)
- Git migration (Mac-local → VPS or GHA host)
- Split public ingestion repo / private vault repo
- Concept candidate *flagging* in extraction output + Slack surfacing (runway for Lane C)

### Lane C — dedicated future design
- Concept *synthesis* — writing and updating concept pages across sources. Needs specialised agent attention (different prompts, many-to-one reads, contradiction detection, staleness management, drift prevention). Not a cron job. Will get its own brainstorm + spec.

### Explicitly excluded from all lanes until demand appears
- Per-resource entity pages (flat resources-index instead; promote individually only when a URL gets significant coverage)
- Automatic concept-page writes in cron (too risky — silent wrong knowledge is the failure mode knowledge bases can't afford)
- Web UI for watchlist management (`config.yml` edit in a text editor is fine at solo scale)
- Transcript search / embedding pipeline (Next.js wiki interface's text search is sufficient)
- Thumbnails, screenshots, frame extraction
- Multi-language extraction (English-only prompt; non-English captions get translated-during-extraction, acceptable)
- Threshold-based storage alerts (passive reporting only)
- Multi-day retry queues / formal queue infrastructure
- Auto-refreshing creator bios (append-only with dated additions)

## 4. Architecture

### 4.1 Model

Monolith Python script. One `main.py` orchestrates all stages sequentially per cron run. No workers, no persistent queues, no services. Modules split for testability, not concurrency:

```
drain queue sources → for each URL: fetch → extract → write → record state
                   → post Slack summary
```

### 4.2 Project layout

```
youtube-transcript-ailearning/
├── CLAUDE.md
├── README.md                    # setup, watchlist editing, manual push
├── pyproject.toml               # or requirements.txt
├── .env.example                 # ANTHROPIC_API_KEY, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, VAULT_PATH
├── .env                         # gitignored
├── .gitignore                   # state.json, queue.txt, logs/, .env
├── config.yml                   # watchlist, seed categories, channel hints
├── state.json                   # dedup + polling state (gitignored)
├── queue.txt                    # manual-push URLs, drained each run (gitignored)
├── com.steven.ytingest.plist    # launchd job definition
├── logs/                        # rotating run logs (gitignored)
├── docs/
│   └── superpowers/specs/       # this design + future specs
└── src/
    ├── __init__.py
    ├── main.py                  # entry point launchd calls
    ├── fetch.py                 # yt-dlp self-update + metadata + captions
    ├── extract.py               # Claude call → structured JSON
    ├── write.py                 # source / creator / resources-index / index.md / log.md writers
    ├── slack_queue.py           # read channel messages, extract URLs, react-mark processed
    ├── notify.py                # post daily summary + threaded per-video replies
    ├── state.py                 # atomic read/write of state.json
    └── prompts/
        ├── extract.md           # extraction prompt template
        └── categories.md        # seed categories + rules for proposals
```

**Path hygiene:** vault location is read from `VAULT_PATH` env var, never hardcoded. This makes the Lane B "split public ingestion / private vault" move a ~5-minute swap.

### 4.3 Module responsibilities

| Module | Job | Writes | Calls |
|---|---|---|---|
| `main.py` | Orchestrate, catch-up undelivered Slack posts | `logs/{date}.json` | all below |
| `fetch.py` | Self-update yt-dlp, fetch metadata + captions + description for one video | nothing | yt-dlp CLI |
| `extract.py` | Build prompt context, call Claude with prompt caching, parse JSON | nothing | Claude API |
| `write.py` | Template structured JSON into markdown artifacts | source page, creator page, resources-index, index.md, log.md | filesystem |
| `slack_queue.py` | Read channel since `last_message_ts`, regex URLs, mark processed | state.json (ts + bot_id), Slack reactions | Slack Web API |
| `notify.py` | Compose + post daily summary and per-video threaded replies | Slack messages | Slack Web API |
| `state.py` | Atomic read/write helpers for `state.json` via temp-file + `os.replace()` | state.json | filesystem |

## 5. Configuration & state

### 5.1 `config.yml` (static, human-edited)

```yaml
watchlist:
  - url: https://www.youtube.com/@AnthropicAI
    default_categories: [optimising-ai, tool-combinations]
    min_duration_seconds: 120       # optional per-channel override
  - url: https://www.youtube.com/@someCreator
    default_categories: [building-websites]

seed_categories:
  - building-websites
  - optimising-ai
  - tool-combinations
  - future-trends

ingest:
  max_videos_per_run: 10            # backlog safety rail
  lookback_days: 14                 # first-sight cutoff for a new channel
  min_duration_seconds: 60          # global minimum, skips shorts
```

Channel-level `default_categories` is a **hint** seeded into the extraction prompt, not an override — the LLM can still propose additional categories per video. Hint reduces drift.

### 5.2 `state.json` (dynamic, script-written, gitignored)

```json
{
  "ingested_video_ids": {
    "<video_id>": {
      "ingested_at": "ISO8601",
      "source_page": "wiki/sources/creator-<creator-slug>--<video-slug>.md",
      "creator_slug": "<creator-slug>"
    }
  },
  "channels": {
    "<channel_url>": {
      "last_checked_at": "ISO8601",
      "last_seen_video_id": "<video_id>"
    }
  },
  "failed_videos": {
    "<video_id>": {
      "reason": "...",
      "attempts": N,
      "last_tried": "ISO8601"
    }
  },
  "dead_videos": {
    "<video_id>": {
      "reason": "...",
      "moved_dead_at": "ISO8601"
    }
  },
  "proposed_categories": {
    "<slug>": {
      "first_seen": "ISO8601",
      "sightings": N,
      "videos": ["<video_id>", "..."],
      "status": "pending | auto-promoted | merged | renamed"
    }
  },
  "slack_queue": {
    "last_message_ts": "1745174400.000123",
    "bot_user_id": "U0123ABC456"
  },
  "undelivered_summaries": [
    { "run_date": "ISO8601", "log_path": "logs/2026-04-20.json" }
  ]
}
```

**Writes via write-to-temp + `os.replace()`** for atomicity. A mid-crash never leaves corrupted JSON.

**Dedup key:** YouTube video ID (11 chars), not URL. URLs are extracted from any form (`youtube.com/watch?v=...`, `youtu.be/...`, with query params) and canonicalised to the ID before dedup check.

### 5.3 `queue.txt` (ephemeral manual push, gitignored)

One URL per line. Drained per run: read in full, each line attempted, each line's result (ingested / queued-for-retry / skipped) appended to `logs/{date}.json`. File is truncated at the end of a successful drain. If the run crashes mid-drain, the file stays and the next run retries the full contents — dedup catches already-ingested ones.

### 5.4 Queue unification

Per run, URLs from three sources are merged into one in-memory list in this order:

1. `queue.txt` drain
2. Slack channel read (messages since `slack_queue.last_message_ts`, excluding bot's own posts, regex-matched for YouTube URLs; thread replies count)
3. Watchlist poll (for each channel, walk feed until `last_seen_video_id` or `lookback_days` boundary)

Duplicates (same video ID across sources) are collapsed. `max_videos_per_run` caps the list; excess gets pushed to the next run via the `last_seen_video_id` boundary not advancing past unprocessed items.

## 6. Extraction & page schemas

### 6.1 Extraction prompt inputs

One Claude Sonnet 4.7 call per video. Prompt caching applied across videos in a single run — implementation decides which blocks are cache-worthy based on stability, with the static extraction schema + seed categories + system prompt as obvious candidates.

Context provided:
- Full transcript text
- Video metadata (title, description, channel name + URL, duration, published_at)
- Current creator page if one exists (so the LLM can emit `creator_bio_additions` rather than re-derive)
- Current resources-index (for dedup — avoids re-adding URLs already there)
- Seed + previously-accepted categories + channel-level `default_categories` hint

### 6.2 Expected JSON output

```json
{
  "session_summary": "2-3 paragraphs, third-person",
  "instructions_and_howto": "Markdown body — filtered of backstory, preserves code blocks verbatim, uses numbered lists where creator gave a sequence",
  "key_takeaways": ["terse bullet", "..."],
  "resources": [
    {
      "url": "https://...",
      "title": "...",
      "description": "one-line why it was mentioned",
      "group": "Tools | Documentation | Articles | Uncategorised"
    }
  ],
  "categories": ["optimising-ai", "tool-combinations"],
  "proposed_new_categories": [
    { "slug": "agent-orchestration", "rationale": "..." }
  ],
  "tags": ["prompt-caching", "sonnet-4-7"],
  "domain": "claude-code",
  "creator_bio_additions": "empty string or new biographical facts with date",
  "connections": [
    { "target": "concept-prompt-caching", "note": "creator demonstrated..." }
  ]
}
```

Unparseable JSON → retry 2× with the failed output echoed back. Still broken after retries → skip video, log full output, surface in Slack failures.

### 6.3 Source page schema

Written to `wiki/sources/creator-<creator-slug>--<video-slug>.md`. Double-dash prefix makes creator grouping visible in directory listings.

```yaml
---
title: "Video title verbatim"
type: source
source_type: video
source_platform: youtube
video_id: <11-char-id>
video_url: https://www.youtube.com/watch?v=<id>
creator: "[[creator-<slug>]]"
published_at: YYYY-MM-DD
duration_seconds: N
date_ingested: YYYY-MM-DD
raw_path: "raw/youtube/<video_id>.transcript.txt"
categories: [list]
domain: claude-code | prompt-eng | model-compare | sdk-api | workflow
tags: [list]
---

## Session Summary
...

## Instructions & How-To
...

## Resources Mentioned
- [Title](url) — description

## Key Takeaways
- ...

## Connections
- [[target-page]] — note
```

Extends the vault CLAUDE.md's `source_type: video` variant — adds `source_platform`, `video_id`, `video_url`, `duration_seconds`, `categories` frontmatter; adds `Instructions & How-To` and `Resources Mentioned` sections. Existing `source_type: article | transcript | notes | pdf | release-notes` schemas are unchanged. **Vault CLAUDE.md requires a patch** documenting the new variant.

### 6.4 Creator page schema (new entity type)

Written to `wiki/entities/creator-<name-slug>.md`. Created on first sighting, appended on subsequent sightings.

```yaml
---
title: "Creator Display Name"
type: entity
entity_type: creator
creator_platform: youtube
channel_url: https://www.youtube.com/@...
channel_id: UCr...
domain: [list of domains seen across sources]
created: YYYY-MM-DD
updated: YYYY-MM-DD
source_count: N
tags: [creator]
---

## About
...

## Themes
Auto-aggregated from categories across ingested sources.

## Sources
- [[creator-<slug>--video-1]] — 2026-04-15 — one-line summary
- [[creator-<slug>--video-2]] — 2026-04-10 — one-line summary
```

**Update semantics:** read existing page → pass to LLM as context → LLM emits `creator_bio_additions` (empty if nothing new). Additions get appended under `## About` with a date marker. Contradictions logged to `log.md` per vault rule *"Flag contradictions — never silently overwrite."*

### 6.5 Resources index (new page type)

Single flat file `wiki/sources/resources-index.md`. One row per unique URL across all sources. Grouped by small fixed taxonomy; new groups proposed same way as new categories (surfaced in Slack before auto-accepted).

```yaml
---
title: "Resources Index"
type: index
created: YYYY-MM-DD
updated: YYYY-MM-DD
entry_count: N
---

## Tools
- https://... — Title — description. Mentioned in: [[source-1]], [[source-2]]
## Documentation
- ...
## Articles
- ...
## Uncategorised
- ...
```

Rationale for flat file vs per-URL pages: 500+ pages after a few months with most having two lines is the failure mode. Flat index is skim-able. When a resource *earns* individual attention (mentioned in 10+ sources, say), it gets promoted to its own entity page manually.

### 6.6 index.md and log.md updates

Vault convention already defined. On every run, `index.md` updated with new source / entity / resource entries; `log.md` appended with operation records. Atomic writes.

## 7. Slack integration

### 7.1 Delivery mechanism

Slack app with bot token (not incoming webhook). Scopes:

- `chat:write` — post daily summary + threaded replies
- `channels:history` — read channel for URL drops
- `reactions:write` — mark processed messages with 📼

Single credential powers both read and write. `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` in `.env`.

Dedicated channel (e.g. `#ai-learnings`), not DM — pinnable, searchable, shareable with collaborators later without losing history.

### 7.2 Read — Slack as queue source

At run start:
1. Fetch messages with `ts > state.slack_queue.last_message_ts`
2. Exclude messages authored by the bot (filter on `state.slack_queue.bot_user_id`)
3. Regex-extract YouTube URLs from remaining messages (channel + thread replies)
4. Append to the unified URL queue
5. On successful processing, react to source message with 📼
6. Update `last_message_ts` to newest processed message

Failure to reach Slack at run start → skip Slack queue for this run, log, continue with watchlist + `queue.txt`. `last_message_ts` unchanged; next run retries.

### 7.3 Write — daily summary

One top-level message per run, posted at end-of-run. Threaded replies hold per-video detail. Even on zero-ingest days, post a terse heartbeat so silence means failure.

**Top-level shape:**
```
📼 AI Learnings — daily ingest · YYYY-MM-DD HH:MM
Ingested N new · skipped M · failed K

NEW
• "Title" — Creator — categories

SKIPPED
• "Title" — reason

STORAGE
raw/youtube: X MB (Y videos · +N today)

REVIEW QUEUE
• N proposed categories awaiting rename/merge: <slug>, <slug>
```

**Per-video threaded reply:**
```
"Title" — Creator
📂 wiki/sources/<filename>.md
📝 N takeaways · 🔗 M resources · 🏷 category, category
Takeaway 1
Takeaway 2
Takeaway 3
```

**Per-failure threaded reply:**
```
❌ "Title" — <video_id>
Reason: <reason>
Next: retry N of 3 | moved to dead
```

### 7.4 Catch-up semantics

If end-of-run Slack post fails, the full run summary is written to `logs/{date}.json` and recorded in `state.undelivered_summaries`. The next run, before its own summary, drains `undelivered_summaries` and posts catch-up messages with a "⚠ delayed from <date>" prefix. On successful delivery, entries are removed from state.

## 8. Failure modes

### 8.1 Per-video failures

| Condition | Behaviour | State | Recovery |
|---|---|---|---|
| yt-dlp metadata fetch fails (deleted / private / geo-blocked) | Skip, increment `failed_videos[id].attempts` | `failed_videos` | Retried next run; 3 attempts → `dead_videos` |
| No captions available | Skip, record reason | `failed_videos` | Same as above |
| Captions empty/malformed | Skip, log raw yt-dlp output | `failed_videos` | Same |
| LLM call fails (5xx / network / rate limit) | In-run retry 3× with exponential backoff; if still failing, leave in queue | `failed_videos` | Next run picks up; transcript already in `raw/`, no refetch |
| LLM returns invalid JSON | Retry 2× with failed output echoed back to the model; if still broken, skip + log full output | `failed_videos` | Prompt iteration; examine logs |
| Vault write fails (disk / perms) | Abort run; no partial writes | `last_run_error` | Manual fix; next run resumes |
| Video already ingested (dedup hit) | Silent skip; does not appear in Slack skip count | — | — |

### 8.2 Run-level failures

| Condition | Behaviour | Recovery |
|---|---|---|
| yt-dlp itself broken (YT change, yt-dlp not patched) | Self-update attempt → retry → if still broken, Slack-post 🚨 alert + abort | `pip install -U yt-dlp` or wait for upstream fix |
| Slack unreachable at summary post | Log summary to `logs/{date}.json`, add to `undelivered_summaries` | Next run posts catch-up |
| Slack unreachable at queue read | Skip Slack queue, continue | Next run retries |
| `ANTHROPIC_API_KEY` missing/invalid | Abort immediately, write `logs/{date}.error.log` | Manual `.env` fix; missing Slack heartbeat flags the failure |
| Cron didn't fire (Mac asleep) | launchd `StartCalendarInterval` runs on next wake | Automatic |
| Script killed mid-run | Atomic state.json means no corruption; partial vault writes stay (markdown tolerant) | Next run's dedup skips completed videos |

### 8.3 Dead-video policy

3 failed attempts → move to `dead_videos`. Dead videos:
- Stop being retried
- Surface once in Slack summary ("marked dead: ...")
- Require manual `state.json` edit to revive (rare; no CLI needed)

### 8.4 Atomic write discipline

`state.json` and `wiki/index.md` written via temp-file + `os.replace()`. Other vault writes (source page, creator page, log.md) are markdown and tolerant of mid-crash truncation — worst case is the next run notices source_count mismatch and patches forward.

## 9. Category hygiene

- LLM may propose new categories per video in `proposed_new_categories`.
- First sighting: recorded in `state.proposed_categories[slug]` with `status: pending`. Surfaced in Slack review queue.
- Sighting #3 without manual rename/merge: auto-promoted to seed list. Status becomes `auto-promoted`. Slack surfaces a one-off "ℹ category auto-promoted after 3 uses" message prompting edit of `config.yml` if rename/merge still desired.
- Manual merges: user edits `config.yml` (adds under `seed_categories`, optionally renames via a `category_aliases` map — deferred to Lane B if needed).

Same pattern applies to resource groups (Tools / Documentation / Articles / Uncategorised + proposals).

## 10. Execution environment

- **Host:** Mac, user account `steven`
- **Scheduler:** launchd via `com.steven.ytingest.plist` with `StartCalendarInterval` at 09:00 daily
- **Python:** 3.12+
- **Key dependencies:** `yt-dlp`, `anthropic`, `pyyaml`, `slack-sdk`
- **Secrets:** `.env` in project root; consumed by `python-dotenv`. Keys: `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`, `VAULT_PATH`
- **Logs:** `logs/{date}.json` per run + `logs/{date}.error.log` on fatal errors. Rotated / pruned by a later Lane B task if volume becomes an issue.

## 11. Decisions log

Captured for posterity — each decision is reversible but the reasoning should be preserved.

| # | Decision | Chosen | Rejected | Rationale |
|---|---|---|---|---|
| 1 | Trigger model | Hybrid: watchlist poll + manual push | Pure watchlist, pure manual | Coverage of high-signal channels + easy one-off grabs from phone/Slack |
| 2 | Autonomy level | Auto-write source + creator + resources; manual concept synthesis | Raw-only; fully autonomous including concepts | Bounded per-video writes are safe; concept synthesis is judgement-heavy, risks silent wrong knowledge |
| 3 | Transcript source | `yt-dlp` with self-update each run | YouTube Data API; `youtube-transcript-api` | Single call gives transcript + metadata + description; battle-tested against YT endpoint churn |
| 4 | Host | Mac launchd, daily | VPS cron; GitHub Actions | Vault is local, no sync round-trip, Mac almost always awake. Lane B migration is ~30min when needed |
| 5 | Podcast scope | Deferred to Lane B | Include in v1 | Adds fetcher + Whisper complexity. Same extraction schema transfers cleanly later |
| 6 | Slack integration | Bot token for read + write | Webhook (write-only) with later migration | One-time setup, mobile URL drop from phone, no dual-migration cost |
| 7 | Source page filename | `creator-<slug>--<video-slug>.md` | `<date>--<video-slug>.md` | Creator grouping in directory listings more valuable than chrono sort (handled via frontmatter) |
| 8 | Instructions length | Embed, no cap | Split to separate file over threshold | Source page is canonical; two-file reads have no ergonomic gain |
| 9 | Raw transcript retention | Keep indefinitely | Delete after write | ~100KB/video; cheap insurance for prompt iteration + re-extraction |
| 10 | Resources representation | Flat `resources-index.md` | Per-URL entity pages | 500+ two-line pages is the failure mode; promote manually when any URL earns it |
| 11 | Category proposal lifecycle | Flag 1-2, auto-promote at 3 with Slack notice | Auto-promote immediately; nag forever | Review window without nag fatigue |
| 12 | Zero-ingest day behaviour | Post heartbeat anyway | Silent | Absence-of-post = liveness signal for missed runs |
| 13 | Concept pages in cron | None (Lane C) | Full auto-write; candidate-flag-only in Lane B | Silent wrong knowledge is the vault-killer; candidate flagging in Lane B is runway |

## 12. Required vault CLAUDE.md patch

Lane A implementation includes a small edit to the vault's CLAUDE.md (`/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/CLAUDE.md`) documenting the new `source_type: video` variant (adds frontmatter fields, adds `Instructions & How-To` and `Resources Mentioned` sections) and the new `entity_type: creator`. Existing schemas untouched.

## 13. Implementation plan

Written separately via the superpowers:writing-plans skill following approval of this spec.
