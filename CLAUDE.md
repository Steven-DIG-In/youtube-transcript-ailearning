# YouTube Transcript → AI Learnings

Production ingest pipeline, live since 2026-04. Pulls YouTube videos from three sources — `queue.txt`, a Slack channel, and the `config.yml` watchlist (drained in that order) — extracts structured learnings via Claude, writes source/creator/resources pages to the AI Learnings wiki vault, and posts a daily digest to Slack. Runs unattended once a day.

## Running it

- Scheduled: launchd job `com.steven.ytingest` (plist checked in at repo root, installed to `~/Library/LaunchAgents/`) runs `.venv/bin/python -m src.main` daily at 10:30. Logs: `logs/launchd.stdout.log` / `logs/launchd.stderr.log`. Check it's loaded: `launchctl list | grep ytingest`.
- Manual run: `source .venv/bin/activate && python -m src.main` from the repo root.
- Tests: `pytest -q` (unit, no network) · `pytest -m integration` (live network). Config in `pyproject.toml`.
- Setup from scratch (venv, Slack app scopes, `.env`, plist install): `README.md`. Env vars: `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`, `VAULT_PATH`.

## Adding a video

- Terminal: `echo "https://www.youtube.com/watch?v=XXX" >> queue.txt` — queue.txt is a one-shot drop-box, truncated as each run drains it.
- Slack (works from the phone): paste the URL into the configured channel; the bot reacts with 📼 once ingested.
- Watchlist channels in `config.yml` are polled automatically (caps: `max_videos_per_run: 2`, 14-day lookback, min 60s duration).

## state.json semantics

Sole run state, atomic-write via temp file + `os.replace` (`src/state.py`). Keys:

- `ingested_video_ids` — dedupe map; delete an id to force re-ingest of that video
- `failed_videos` — retry ledger with attempt counts; after 3 failures a video moves to `dead_videos` and is never retried
- `proposed_categories` — Claude-proposed categories with sighting counts; 3 sightings auto-promotes, review via the Slack digest's review-queue section (rename/merge by editing `seed_categories` in `config.yml`)
- `slack_queue.last_message_ts` — Slack read cursor (plus cached `bot_user_id`)
- `undelivered_summaries` — digests that failed to post, retried next run

Timestamped `state.json.bak-*` files are manual pre-cleanup backups, not consumed by code.

## Output

- Vault pages land in `VAULT_PATH` → `/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/`.
- After each run, `vault_push.py` commits and pushes the vault from the wiki repo (never raises; standalone by design so cron can call it without src/ imports).
- Raw transcripts cache under `transcripts/`.

## Module map

`src/main.py` orchestrates (`run_once`); `fetch.py` (yt-dlp), `extract.py` (Claude), `write.py` (vault pages), `slack_queue.py` (channel drain + reactions), `notify.py` + `digest.py` (Slack summaries), `state.py`, `config.py`.

## Conventions

- Kebab-case filenames in the vault; English only, even for Portuguese-speaking contexts.
- Spec: `docs/superpowers/specs/2026-04-21-youtube-transcript-ingestion-design.md` · plan alongside it.

## Memory

- Cross-AI: `~/.claude/memory/projects/youtube-transcript-ailearning.md`
- Auto-memory entries are tagged `project_youtube_transcript_*` under `~/.claude/projects/-Users-steven-Vibe-Projects/memory/`
