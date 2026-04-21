# YouTube Transcript → AI Learnings

Ingests YouTube videos from a watchlist, Slack channel drops, and a local queue file;
extracts structured learning content via Claude; writes source + creator + resources
pages to the AI Learnings wiki vault; posts a daily summary to Slack.

Spec: `docs/superpowers/specs/2026-04-21-youtube-transcript-ingestion-design.md`
Plan: `docs/superpowers/plans/2026-04-21-youtube-transcript-ingestion.md`

## One-time setup

1. **Python + deps**
   ```bash
   python3.13 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

2. **Slack app**
   - Create at https://api.slack.com/apps → "From scratch" → pick your workspace
   - Under "OAuth & Permissions", add bot token scopes:
     - `chat:write`
     - `channels:history`
     - `reactions:write`
   - Install to workspace, copy the `xoxb-...` bot token
   - Invite the bot to the channel you want ingest posts in:
     `/invite @YourBotName` in the channel

3. **`.env`**
   ```bash
   cp .env.example .env
   # then fill:
   # ANTHROPIC_API_KEY=sk-ant-...
   # SLACK_BOT_TOKEN=xoxb-...
   # SLACK_CHANNEL_ID=C0123ABCDEF   (Slack channel ID, not the #name)
   # VAULT_PATH=/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings
   ```

4. **Seed `config.yml`** — edit the `watchlist:` list with channels you want polled.

5. **Load launchd job**
   ```bash
   cp com.steven.ytingest.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.steven.ytingest.plist
   ```
   Verify:
   ```bash
   launchctl list | grep ytingest
   ```

## Adding a video ad-hoc

**From terminal:**
```bash
echo "https://www.youtube.com/watch?v=XXX" >> queue.txt
```

**From Slack (including phone):** just paste the YouTube URL into the configured
channel. The bot will react with 📼 on the next cron run after ingestion.

## Manual run

```bash
source .venv/bin/activate
python -m src.main
```

## Reviewing proposed categories

Check the daily Slack summary's **REVIEW QUEUE** section. To rename or merge a
proposed category, edit `seed_categories` in `config.yml` and optionally rename
the category across existing source pages (do this manually — no automated
rewrite in v1).

## Stopping / updating the launchd job

```bash
launchctl unload ~/Library/LaunchAgents/com.steven.ytingest.plist
# edit the plist, then:
launchctl load ~/Library/LaunchAgents/com.steven.ytingest.plist
```

## Tests

```bash
pytest -q              # unit tests, no network
pytest -m integration  # any integration tests, live network
```
