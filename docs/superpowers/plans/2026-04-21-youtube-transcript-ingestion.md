# YouTube Transcript → AI Learnings Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily cron-driven pipeline that fetches YouTube videos from watchlist + Slack + manual queue, extracts structured learning content via Claude, writes source/creator/resources artifacts to the AI Learnings vault, and posts a Slack summary.

**Architecture:** Monolith Python script with modules split for testability (fetch / extract / write / slack_queue / notify / state). Run by Mac launchd at 09:00 daily. Atomic state.json for dedup. Prompt-cached single Claude call per video. All paths via env vars.

**Tech Stack:** Python 3.12+, `yt-dlp`, `anthropic`, `pyyaml`, `slack-sdk`, `python-dotenv`, `pytest`, `pytest-mock`.

**Authoritative spec:** `docs/superpowers/specs/2026-04-21-youtube-transcript-ingestion-design.md` — especially the decisions log (Section 11) for resolved questions.

**Path conventions used below:**
- Project root: `/Users/steven/Vibe Projects/youtube-transcript-ailearning/`
- Vault: `/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/`
- All `git` commands assume the repo is the project root unless stated.

---

## Phase 1 — Bootstrap

### Task 1: Initialise project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `config.yml`
- Create: `src/__init__.py`
- Create: `src/prompts/__init__.py` (empty marker so `prompts` is a package if needed — actually prompts are `.md`, so no marker needed; skip this file)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/` (directory)
- Create: `logs/.gitkeep`

- [ ] **Step 1: Initialise git repo**

Run:
```bash
cd "/Users/steven/Vibe Projects/youtube-transcript-ailearning"
git init
git branch -M main
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "youtube-transcript-ailearning"
version = "0.1.0"
description = "Ingest YouTube transcripts into the AI Learnings wiki vault"
requires-python = ">=3.12"
dependencies = [
    "yt-dlp>=2024.8.6",
    "anthropic>=0.39.0",
    "pyyaml>=6.0",
    "slack-sdk>=3.27.0",
    "python-dotenv>=1.0.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: live-network tests (deselect with -m 'not integration')",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["src*"]
```

- [ ] **Step 3: Write `.gitignore`**

```
.env
state.json
queue.txt
logs/*
!logs/.gitkeep
__pycache__/
*.pyc
.pytest_cache/
tests/fixtures/_scratch/
.venv/
```

- [ ] **Step 4: Write `.env.example`**

```
ANTHROPIC_API_KEY=
SLACK_BOT_TOKEN=
SLACK_CHANNEL_ID=
VAULT_PATH=/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings
```

- [ ] **Step 5: Write `config.yml`** (starter; watchlist populated by Steven manually later)

```yaml
watchlist: []

seed_categories:
  - building-websites
  - optimising-ai
  - tool-combinations
  - future-trends

ingest:
  max_videos_per_run: 10
  lookback_days: 14
  min_duration_seconds: 60
```

- [ ] **Step 6: Create package markers**

```bash
mkdir -p src tests tests/fixtures logs
touch src/__init__.py tests/__init__.py logs/.gitkeep
```

- [ ] **Step 7: Write minimal `tests/conftest.py`**

```python
import json
from pathlib import Path

import pytest


@pytest.fixture
def temp_state_path(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


@pytest.fixture
def temp_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "analyses").mkdir(parents=True)
    (vault / "raw" / "youtube").mkdir(parents=True)
    (vault / "index.md").write_text(
        "# Index\n\n## Entities\n\n## Concepts\n\n## Sources\n\n## Analyses\n"
    )
    (vault / "log.md").write_text("# Log\n")
    return vault


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


def load_fixture_json(fixtures_dir: Path, name: str):
    return json.loads((fixtures_dir / name).read_text())
```

- [ ] **Step 8: Create venv and install**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
Expected: successful install, no errors.

- [ ] **Step 9: Smoke-test pytest**

Run: `pytest -q`
Expected: `no tests ran` (or similar "collected 0 items"). Confirms pytest discovers nothing and exits cleanly.

- [ ] **Step 10: Commit**

```bash
git add .
git commit -m "chore: scaffold project — pyproject, config, gitignore, conftest"
```

---

## Phase 2 — state.py (atomic state I/O + dedup)

### Task 2: state.py — load when file missing returns default shape

**Files:**
- Create: `src/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
from pathlib import Path

from src.state import DEFAULT_STATE, load_state


def test_load_state_missing_file_returns_default(temp_state_path: Path):
    result = load_state(temp_state_path)
    assert result == DEFAULT_STATE
    assert "ingested_video_ids" in result
    assert "channels" in result
    assert "failed_videos" in result
    assert "dead_videos" in result
    assert "proposed_categories" in result
    assert "slack_queue" in result
    assert "undelivered_summaries" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state.py::test_load_state_missing_file_returns_default -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError` because `src.state` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# src/state.py
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_STATE: dict[str, Any] = {
    "ingested_video_ids": {},
    "channels": {},
    "failed_videos": {},
    "dead_videos": {},
    "proposed_categories": {},
    "slack_queue": {"last_message_ts": None, "bot_user_id": None},
    "undelivered_summaries": [],
}


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(DEFAULT_STATE)
    return json.loads(path.read_text())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_state.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat(state): load returns default shape when file missing"
```

### Task 3: state.py — atomic save round-trips

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_state.py
from src.state import load_state, save_state


def test_save_state_round_trips(temp_state_path):
    data = {
        "ingested_video_ids": {"abc12345678": {"ingested_at": "2026-04-21T09:00:00Z"}},
        "channels": {},
        "failed_videos": {},
        "dead_videos": {},
        "proposed_categories": {},
        "slack_queue": {"last_message_ts": "1745.0", "bot_user_id": "U1"},
        "undelivered_summaries": [],
    }
    save_state(temp_state_path, data)
    assert load_state(temp_state_path) == data


def test_save_state_uses_atomic_rename(temp_state_path, tmp_path):
    # Write once, then verify that a failed write does not corrupt the original.
    initial = {"ingested_video_ids": {"v1": {}}, "channels": {}, "failed_videos": {},
               "dead_videos": {}, "proposed_categories": {},
               "slack_queue": {"last_message_ts": None, "bot_user_id": None},
               "undelivered_summaries": []}
    save_state(temp_state_path, initial)
    # Simulate interrupted write by ensuring no temp artifact remains.
    leftover_tmp = [p for p in tmp_path.iterdir() if p.name.startswith("state.json.tmp")]
    assert leftover_tmp == []
    assert load_state(temp_state_path) == initial
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_state.py -v`
Expected: FAIL — `save_state` not defined.

- [ ] **Step 3: Add atomic save implementation**

```python
# append to src/state.py
import os
import tempfile


def save_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".tmp.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_state.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat(state): atomic save via temp-file + rename"
```

### Task 4: state.py — is_ingested + mark_ingested

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_state.py
from src.state import is_ingested, mark_ingested


def test_is_ingested_false_when_absent():
    state = {"ingested_video_ids": {}}
    assert is_ingested(state, "abc12345678") is False


def test_mark_ingested_then_is_ingested_true():
    state = {"ingested_video_ids": {}}
    mark_ingested(
        state,
        video_id="abc12345678",
        source_page="wiki/sources/creator-foo--video-bar.md",
        creator_slug="creator-foo",
        ingested_at="2026-04-21T09:00:00Z",
    )
    assert is_ingested(state, "abc12345678") is True
    assert state["ingested_video_ids"]["abc12345678"]["source_page"].endswith("video-bar.md")
    assert state["ingested_video_ids"]["abc12345678"]["creator_slug"] == "creator-foo"
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_state.py -v`
Expected: FAIL — `is_ingested` / `mark_ingested` not defined.

- [ ] **Step 3: Implementation**

```python
# append to src/state.py
def is_ingested(state: dict[str, Any], video_id: str) -> bool:
    return video_id in state["ingested_video_ids"]


def mark_ingested(
    state: dict[str, Any],
    *,
    video_id: str,
    source_page: str,
    creator_slug: str,
    ingested_at: str,
) -> None:
    state["ingested_video_ids"][video_id] = {
        "ingested_at": ingested_at,
        "source_page": source_page,
        "creator_slug": creator_slug,
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_state.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat(state): is_ingested and mark_ingested helpers"
```

### Task 5: state.py — record_failure + dead-video promotion

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_state.py
from src.state import record_failure, DEAD_THRESHOLD


def test_record_failure_increments_attempts():
    state = {"failed_videos": {}, "dead_videos": {}}
    record_failure(state, video_id="v1", reason="no captions", now="2026-04-21T09:00:00Z")
    record_failure(state, video_id="v1", reason="no captions", now="2026-04-22T09:00:00Z")
    assert state["failed_videos"]["v1"]["attempts"] == 2
    assert state["failed_videos"]["v1"]["reason"] == "no captions"
    assert state["failed_videos"]["v1"]["last_tried"] == "2026-04-22T09:00:00Z"
    assert "v1" not in state["dead_videos"]


def test_record_failure_moves_to_dead_after_threshold():
    state = {"failed_videos": {}, "dead_videos": {}}
    for i in range(DEAD_THRESHOLD):
        record_failure(state, video_id="v1", reason="no captions", now=f"2026-04-2{i+1}T09:00:00Z")
    assert "v1" not in state["failed_videos"]
    assert "v1" in state["dead_videos"]
    assert state["dead_videos"]["v1"]["reason"] == "no captions"
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_state.py -v`
Expected: FAIL — `record_failure` / `DEAD_THRESHOLD` undefined.

- [ ] **Step 3: Implementation**

```python
# append to src/state.py
DEAD_THRESHOLD = 3


def record_failure(
    state: dict[str, Any],
    *,
    video_id: str,
    reason: str,
    now: str,
) -> None:
    existing = state["failed_videos"].get(video_id, {"attempts": 0})
    attempts = existing["attempts"] + 1
    if attempts >= DEAD_THRESHOLD:
        state["dead_videos"][video_id] = {
            "reason": reason,
            "moved_dead_at": now,
        }
        state["failed_videos"].pop(video_id, None)
        return
    state["failed_videos"][video_id] = {
        "reason": reason,
        "attempts": attempts,
        "last_tried": now,
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_state.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat(state): record_failure and dead-video promotion after 3 attempts"
```

### Task 6: state.py — category proposal lifecycle

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_state.py
from src.state import record_proposed_category, CATEGORY_AUTOPROMOTE_THRESHOLD


def test_proposed_category_first_sighting_is_pending():
    state = {"proposed_categories": {}}
    record_proposed_category(
        state,
        slug="agent-orchestration",
        video_id="v1",
        now="2026-04-21T09:00:00Z",
    )
    entry = state["proposed_categories"]["agent-orchestration"]
    assert entry["sightings"] == 1
    assert entry["status"] == "pending"
    assert entry["videos"] == ["v1"]
    assert entry["first_seen"] == "2026-04-21T09:00:00Z"


def test_proposed_category_autopromotes_at_threshold():
    state = {"proposed_categories": {}}
    for i in range(CATEGORY_AUTOPROMOTE_THRESHOLD):
        record_proposed_category(
            state,
            slug="agent-orchestration",
            video_id=f"v{i}",
            now=f"2026-04-2{i+1}T09:00:00Z",
        )
    assert state["proposed_categories"]["agent-orchestration"]["status"] == "auto-promoted"
    assert state["proposed_categories"]["agent-orchestration"]["sightings"] == CATEGORY_AUTOPROMOTE_THRESHOLD


def test_proposed_category_dedup_videos():
    state = {"proposed_categories": {}}
    record_proposed_category(state, slug="x", video_id="v1", now="2026-04-21T09:00:00Z")
    record_proposed_category(state, slug="x", video_id="v1", now="2026-04-22T09:00:00Z")
    assert state["proposed_categories"]["x"]["videos"] == ["v1"]
    assert state["proposed_categories"]["x"]["sightings"] == 1
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `record_proposed_category` / `CATEGORY_AUTOPROMOTE_THRESHOLD` undefined.

- [ ] **Step 3: Implementation**

```python
# append to src/state.py
CATEGORY_AUTOPROMOTE_THRESHOLD = 3


def record_proposed_category(
    state: dict[str, Any],
    *,
    slug: str,
    video_id: str,
    now: str,
) -> None:
    entry = state["proposed_categories"].get(slug)
    if entry is None:
        state["proposed_categories"][slug] = {
            "first_seen": now,
            "sightings": 1,
            "videos": [video_id],
            "status": "pending",
        }
        return
    if video_id in entry["videos"]:
        return
    entry["videos"].append(video_id)
    entry["sightings"] += 1
    if entry["sightings"] >= CATEGORY_AUTOPROMOTE_THRESHOLD and entry["status"] == "pending":
        entry["status"] = "auto-promoted"
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_state.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat(state): proposed-category lifecycle with auto-promote at 3 sightings"
```

---

## Phase 3 — fetch.py (yt-dlp wrapper)

### Task 7: fetch.py — video ID extraction from URLs

**Files:**
- Create: `src/fetch.py`
- Create: `tests/test_fetch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch.py
import pytest

from src.fetch import extract_video_id


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc123", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
])
def test_extract_video_id(url, expected):
    assert extract_video_id(url) == expected


def test_extract_video_id_rejects_non_youtube():
    assert extract_video_id("https://vimeo.com/12345") is None
    assert extract_video_id("not a url") is None
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `extract_video_id` undefined.

- [ ] **Step 3: Implementation**

```python
# src/fetch.py
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        return None
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif parsed.path.startswith("/shorts/"):
        candidate = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
    else:
        qs = parse_qs(parsed.query)
        candidate = qs.get("v", [""])[0]
    if _VIDEO_ID_RE.match(candidate):
        return candidate
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_fetch.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fetch.py tests/test_fetch.py
git commit -m "feat(fetch): canonical video ID extraction from any YouTube URL form"
```

### Task 8: fetch.py — regex URLs from text blob (Slack messages, queue.txt)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_fetch.py
from src.fetch import extract_youtube_urls_from_text


def test_extract_urls_from_text_single():
    text = "Check this out: https://www.youtube.com/watch?v=dQw4w9WgXcQ — great video."
    assert extract_youtube_urls_from_text(text) == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


def test_extract_urls_from_text_multiple_forms():
    text = (
        "1) https://youtu.be/aaaaaaaaaaa\n"
        "2) also https://www.youtube.com/watch?v=bbbbbbbbbbb&t=42\n"
        "3) vimeo https://vimeo.com/ignoreme"
    )
    urls = extract_youtube_urls_from_text(text)
    assert len(urls) == 2
    assert any("aaaaaaaaaaa" in u for u in urls)
    assert any("bbbbbbbbbbb" in u for u in urls)


def test_extract_urls_from_text_empty():
    assert extract_youtube_urls_from_text("no links here") == []
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `extract_youtube_urls_from_text` undefined.

- [ ] **Step 3: Implementation**

```python
# append to src/fetch.py
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)


def extract_youtube_urls_from_text(text: str) -> list[str]:
    results: list[str] = []
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:!?)")
        if extract_video_id(url) is not None:
            results.append(url)
    return results
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_fetch.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fetch.py tests/test_fetch.py
git commit -m "feat(fetch): extract YouTube URLs from arbitrary text"
```

### Task 9: fetch.py — yt-dlp self-update

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_fetch.py
from unittest.mock import patch

from src.fetch import self_update_ytdlp


def test_self_update_runs_pip_install(mocker):
    mock_run = mocker.patch("src.fetch.subprocess.run")
    mock_run.return_value.returncode = 0
    self_update_ytdlp()
    mock_run.assert_called_once()
    args = mock_run.call_args.args[0]
    assert "pip" in args
    assert "install" in args
    assert "-U" in args
    assert "yt-dlp" in args


def test_self_update_raises_on_failure(mocker):
    mock_run = mocker.patch("src.fetch.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "network error"
    with pytest.raises(RuntimeError, match="yt-dlp self-update failed"):
        self_update_ytdlp()
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `self_update_ytdlp` undefined.

- [ ] **Step 3: Implementation**

```python
# append to src/fetch.py
import subprocess
import sys


def self_update_ytdlp() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-U", "--quiet", "yt-dlp"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp self-update failed: {result.stderr.strip() or 'unknown'}"
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_fetch.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fetch.py tests/test_fetch.py
git commit -m "feat(fetch): yt-dlp self-update wrapper with failure handling"
```

### Task 10: fetch.py — capture fixture for a real video

This task produces a fixture file used by downstream tests. Running against a live video is intentional — once captured, the fixture is reused and tests do not re-hit the network.

**Files:**
- Create: `tests/fixtures/sample-video.json`
- Create: `tests/fixtures/sample-transcript.txt`

- [ ] **Step 1: Pick a stable public video and capture yt-dlp output**

Use the Anthropic "Building effective agents" talk or a similarly stable video. Replace `<URL>` with the chosen URL below.

Run:
```bash
cd "/Users/steven/Vibe Projects/youtube-transcript-ailearning"
source .venv/bin/activate
yt-dlp --skip-download --write-auto-sub --write-sub --sub-lang en --sub-format vtt \
    --print-json --no-simulate \
    -o "tests/fixtures/_scratch/%(id)s" \
    "<URL>" > tests/fixtures/_scratch/raw-metadata.json
```

- [ ] **Step 2: Convert captured metadata to the slim fixture shape**

Only capture fields the pipeline uses. Write by hand based on the scratch file — do not dump the full yt-dlp output:

```json
// tests/fixtures/sample-video.json
{
  "id": "REPLACE_WITH_CAPTURED_ID",
  "title": "Building effective agents",
  "description": "Description verbatim. Links: https://example.com/tool https://docs.example.com",
  "channel": "Anthropic",
  "channel_url": "https://www.youtube.com/@AnthropicAI",
  "channel_id": "UCrDwWp7EBBv4NwvScIpBDOA",
  "duration": 1847,
  "upload_date": "20260415",
  "webpage_url": "https://www.youtube.com/watch?v=REPLACE_WITH_CAPTURED_ID"
}
```

- [ ] **Step 3: Extract plain-text transcript from the VTT**

Run:
```bash
python -c "
import re, pathlib
vtt = list(pathlib.Path('tests/fixtures/_scratch').glob('*.vtt'))[0]
text = vtt.read_text()
lines = []
for line in text.splitlines():
    if not line.strip() or line.startswith('WEBVTT') or '-->' in line or line.startswith('Kind:') or line.startswith('Language:'):
        continue
    cleaned = re.sub(r'<[^>]+>', '', line).strip()
    if cleaned and (not lines or lines[-1] != cleaned):
        lines.append(cleaned)
pathlib.Path('tests/fixtures/sample-transcript.txt').write_text('\n'.join(lines))
print('wrote', len(lines), 'lines')
"
```
Expected: "wrote N lines" with N > 100. Inspect the resulting file briefly to confirm it reads as connected text.

- [ ] **Step 4: Verify fixtures load cleanly**

Run:
```bash
python -c "import json, pathlib; print(json.loads(pathlib.Path('tests/fixtures/sample-video.json').read_text())['title'])"
python -c "import pathlib; print(len(pathlib.Path('tests/fixtures/sample-transcript.txt').read_text()), 'chars')"
```
Expected: prints the title and a character count > 1000.

- [ ] **Step 5: Commit fixtures**

```bash
git add tests/fixtures/sample-video.json tests/fixtures/sample-transcript.txt
git commit -m "test(fetch): capture fixture video metadata and transcript"
```

### Task 11: fetch.py — fetch_video() wrapper returns shaped result from yt-dlp

- [ ] **Step 1: Write the failing test (uses mocked yt-dlp Python API)**

```python
# append to tests/test_fetch.py
import json
from pathlib import Path

from src.fetch import FetchResult, fetch_video, FetchError


def test_fetch_video_returns_shaped_result_on_success(mocker, fixtures_dir, tmp_path):
    metadata = json.loads((fixtures_dir / "sample-video.json").read_text())
    transcript = (fixtures_dir / "sample-transcript.txt").read_text()

    def fake_extract_info(url, download):
        # yt-dlp returns subtitles via a separate download, but for this wrapper we
        # stub both metadata and transcript resolution in one mock boundary.
        return {**metadata, "_transcript_text": transcript}

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return fake_extract_info(url, download)

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FakeYDL)
    mocker.patch("src.fetch._load_transcript_for_video",
                 return_value=transcript)

    result = fetch_video("https://www.youtube.com/watch?v=" + metadata["id"],
                        raw_dir=tmp_path / "raw" / "youtube")
    assert isinstance(result, FetchResult)
    assert result.video_id == metadata["id"]
    assert result.title == metadata["title"]
    assert result.duration_seconds == metadata["duration"]
    assert result.published_at == "2026-04-15"
    assert result.transcript == transcript
    assert result.raw_transcript_path.exists()
    assert result.raw_transcript_path.read_text() == transcript


def test_fetch_video_raises_when_no_captions(mocker, fixtures_dir, tmp_path):
    metadata = json.loads((fixtures_dir / "sample-video.json").read_text())

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return metadata

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FakeYDL)
    mocker.patch("src.fetch._load_transcript_for_video", return_value=None)

    with pytest.raises(FetchError, match="no captions"):
        fetch_video(metadata["webpage_url"], raw_dir=tmp_path / "raw" / "youtube")
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `FetchResult` / `fetch_video` / `FetchError` undefined.

- [ ] **Step 3: Implementation**

```python
# append to src/fetch.py
import yt_dlp
from dataclasses import dataclass
from pathlib import Path


class FetchError(Exception):
    pass


@dataclass
class FetchResult:
    video_id: str
    title: str
    description: str
    channel: str
    channel_url: str
    channel_id: str
    duration_seconds: int
    published_at: str  # YYYY-MM-DD
    webpage_url: str
    transcript: str
    raw_transcript_path: Path


def _yyyymmdd_to_iso(value: str) -> str:
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"


def _load_transcript_for_video(info: dict) -> str | None:
    text = info.get("_transcript_text")
    if text:
        return text
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for source in (subs, auto):
        tracks = source.get("en") or source.get("en-US") or source.get("en-GB")
        if not tracks:
            continue
        for track in tracks:
            if track.get("ext") == "vtt" and track.get("data"):
                return _vtt_to_plain_text(track["data"])
    return None


def _vtt_to_plain_text(vtt: str) -> str:
    lines: list[str] = []
    for line in vtt.splitlines():
        stripped = line.strip()
        if (not stripped
                or stripped.startswith("WEBVTT")
                or "-->" in stripped
                or stripped.startswith("Kind:")
                or stripped.startswith("Language:")):
            continue
        cleaned = re.sub(r"<[^>]+>", "", stripped)
        if cleaned and (not lines or lines[-1] != cleaned):
            lines.append(cleaned)
    return "\n".join(lines)


def fetch_video(url: str, *, raw_dir: Path) -> FetchResult:
    opts = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-GB"],
        "subtitlesformat": "vtt",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise FetchError(f"yt-dlp extract_info failed: {exc}") from exc

    transcript = _load_transcript_for_video(info)
    if not transcript:
        raise FetchError(f"no captions available for {info.get('id')}")

    video_id = info["id"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{video_id}.transcript.txt"
    raw_path.write_text(transcript)

    return FetchResult(
        video_id=video_id,
        title=info["title"],
        description=info.get("description", ""),
        channel=info.get("channel", ""),
        channel_url=info.get("channel_url", ""),
        channel_id=info.get("channel_id", ""),
        duration_seconds=int(info.get("duration") or 0),
        published_at=_yyyymmdd_to_iso(info["upload_date"]),
        webpage_url=info.get("webpage_url", url),
        transcript=transcript,
        raw_transcript_path=raw_path,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_fetch.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fetch.py tests/test_fetch.py
git commit -m "feat(fetch): fetch_video wrapper returning shaped FetchResult"
```

### Task 12: fetch.py — list_new_videos_for_channel (watchlist polling)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_fetch.py
from src.fetch import list_new_videos_for_channel


def test_list_new_videos_stops_at_last_seen(mocker):
    feed = {
        "entries": [
            {"id": "v3", "upload_date": "20260421"},
            {"id": "v2", "upload_date": "20260418"},
            {"id": "v1", "upload_date": "20260410"},
        ]
    }

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return feed

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FakeYDL)
    new = list_new_videos_for_channel(
        "https://www.youtube.com/@Foo",
        last_seen_video_id="v2",
        lookback_days=30,
        now="2026-04-21",
    )
    assert [v["id"] for v in new] == ["v3"]


def test_list_new_videos_respects_lookback_when_no_last_seen(mocker):
    feed = {
        "entries": [
            {"id": "v3", "upload_date": "20260421"},
            {"id": "v2", "upload_date": "20260415"},
            {"id": "v1", "upload_date": "20260301"},
        ]
    }

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return feed

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FakeYDL)
    new = list_new_videos_for_channel(
        "https://www.youtube.com/@Foo",
        last_seen_video_id=None,
        lookback_days=14,
        now="2026-04-21",
    )
    assert [v["id"] for v in new] == ["v3", "v2"]
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/fetch.py
from datetime import datetime, timedelta


def list_new_videos_for_channel(
    channel_url: str,
    *,
    last_seen_video_id: str | None,
    lookback_days: int,
    now: str,  # YYYY-MM-DD
) -> list[dict]:
    opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        feed = ydl.extract_info(channel_url, download=False)
    entries = feed.get("entries") or []

    cutoff = (datetime.strptime(now, "%Y-%m-%d")
              - timedelta(days=lookback_days)).strftime("%Y%m%d")

    results: list[dict] = []
    for entry in entries:
        vid = entry.get("id")
        upload = entry.get("upload_date") or "00000000"
        if last_seen_video_id and vid == last_seen_video_id:
            break
        if not last_seen_video_id and upload < cutoff:
            break
        results.append(entry)
    return results
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_fetch.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fetch.py tests/test_fetch.py
git commit -m "feat(fetch): list_new_videos_for_channel with last-seen + lookback cutoffs"
```

---

## Phase 4 — Prompts

### Task 13: Write the extraction prompt template

**Files:**
- Create: `src/prompts/extract.md`

- [ ] **Step 1: Write prompt template**

```markdown
# src/prompts/extract.md
You are an extraction agent for the AI Learnings wiki vault. You read a YouTube video
transcript plus metadata and return a single JSON object describing the video's learning
content, filtered of filler, backstory, and unrelated asides.

## Rules

1. **Filter aggressively.** Drop: long creator bios in the first few minutes, sponsor reads,
   "please like and subscribe" asides, chatter between sections. Keep: instructions,
   how-to steps, specific claims, resource mentions, demonstrated patterns.
2. **Preserve code blocks and commands verbatim.** Never paraphrase them.
3. **Session summary** is 2-3 paragraphs in third-person describing what the video is about
   and what a viewer walks away with. Do not start with "In this video..." — start with
   the subject.
4. **Instructions & how-to** is structured: numbered list when the creator gave a sequence,
   bulleted otherwise, with sub-bullets for elaboration. Retain code/command blocks.
5. **Resources** come from two sources: the video description (URLs listed there), and
   name-drops in the transcript. For each resource give a one-line description grounded
   in the creator's framing. Use the provided Resources Index snapshot to skip URLs that
   are already indexed.
6. **Categories** must be chosen from the seeded list where they fit. You MAY propose new
   category slugs in `proposed_new_categories` when none of the seeds fit. Use kebab-case.
   Use the channel's default category hints as a soft prior.
7. **Creator bio additions** must be non-empty only if the video reveals biographical
   detail not already in the provided existing creator page (e.g. new employer, new project,
   change of role). Date every addition. Emit `""` if nothing to add.
8. **Domain** must be one of: `claude-code`, `prompt-eng`, `model-compare`, `sdk-api`,
   `workflow`.
9. **Connections** are wikilinks to existing concept/entity pages the video is demonstrating
   or contradicting. Format target slugs in kebab-case; do not invent wikilink targets that
   don't plausibly exist — it is valid to return an empty list.

## Required JSON schema

Return ONLY a single JSON object matching this schema. No prose before or after.

```json
{
  "session_summary": "string",
  "instructions_and_howto": "string (markdown)",
  "key_takeaways": ["string", "..."],
  "resources": [
    {
      "url": "string",
      "title": "string",
      "description": "string",
      "group": "Tools | Documentation | Articles | Uncategorised"
    }
  ],
  "categories": ["string"],
  "proposed_new_categories": [
    {"slug": "string", "rationale": "string"}
  ],
  "tags": ["string"],
  "domain": "claude-code | prompt-eng | model-compare | sdk-api | workflow",
  "creator_bio_additions": "string (empty if no additions)",
  "connections": [
    {"target": "string", "note": "string"}
  ]
}
```

## Inputs

### Video metadata
Title: {{title}}
Channel: {{channel}} ({{channel_url}})
Published: {{published_at}}
Duration: {{duration_seconds}}s

### Video description
{{description}}

### Channel default category hints
{{channel_hint_categories}}

### Seeded + accepted categories
{{seed_categories}}

### Existing creator page (may be empty)
{{existing_creator_page}}

### Resources Index snapshot (for dedup)
{{resources_index_snapshot}}

### Transcript
{{transcript}}
```

- [ ] **Step 2: Commit**

```bash
git add src/prompts/extract.md
git commit -m "feat(prompts): extraction prompt template"
```

### Task 14: Write the categories rules doc

**Files:**
- Create: `src/prompts/categories.md`

- [ ] **Step 1: Write**

```markdown
# src/prompts/categories.md
## Seed categories (v1)

- `building-websites` — front-end, frameworks, deployment, CMS
- `optimising-ai` — caching, thinking, model selection, latency, cost
- `tool-combinations` — integrating multiple tools (Claude + Stitch + Supabase etc.)
- `future-trends` — industry predictions, hot-topic debates, new product launches

## Proposing new categories

- Only propose when none of the seeds plausibly fit
- Use kebab-case, lowercase
- First sighting is recorded with status `pending` and surfaced in the daily Slack summary
- Sighting #3 auto-promotes the slug to the seed list (status becomes `auto-promoted`)
- User may rename or merge at any time by editing `config.yml`
```

- [ ] **Step 2: Commit**

```bash
git add src/prompts/categories.md
git commit -m "docs(prompts): seed categories and proposal lifecycle"
```

---

## Phase 5 — extract.py (Claude call + parsing)

### Task 15: extract.py — prompt rendering (pure function)

**Files:**
- Create: `src/extract.py`
- Create: `tests/test_extract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extract.py
from pathlib import Path

import pytest

from src.extract import render_extract_prompt


def test_render_extract_prompt_interpolates_all_placeholders():
    rendered = render_extract_prompt(
        title="How Prompt Caching Works",
        channel="Anthropic",
        channel_url="https://www.youtube.com/@AnthropicAI",
        published_at="2026-04-15",
        duration_seconds=1847,
        description="Docs: https://docs.anthropic.com/caching",
        channel_hint_categories=["optimising-ai"],
        seed_categories=["optimising-ai", "building-websites"],
        existing_creator_page="",
        resources_index_snapshot="(empty)",
        transcript="Welcome everyone...",
    )
    assert "How Prompt Caching Works" in rendered
    assert "https://www.youtube.com/@AnthropicAI" in rendered
    assert "2026-04-15" in rendered
    assert "1847s" in rendered
    assert "optimising-ai" in rendered
    assert "Welcome everyone..." in rendered
    # placeholders must all be filled
    assert "{{" not in rendered
    assert "}}" not in rendered


def test_render_extract_prompt_handles_empty_creator_page():
    rendered = render_extract_prompt(
        title="t", channel="c", channel_url="u",
        published_at="2026-04-15", duration_seconds=10,
        description="", channel_hint_categories=[],
        seed_categories=[], existing_creator_page="",
        resources_index_snapshot="", transcript="x",
    )
    assert "{{" not in rendered
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `render_extract_prompt` undefined.

- [ ] **Step 3: Implementation**

```python
# src/extract.py
from __future__ import annotations

from pathlib import Path

_PROMPT_PATH = Path(__file__).parent / "prompts" / "extract.md"


def render_extract_prompt(
    *,
    title: str,
    channel: str,
    channel_url: str,
    published_at: str,
    duration_seconds: int,
    description: str,
    channel_hint_categories: list[str],
    seed_categories: list[str],
    existing_creator_page: str,
    resources_index_snapshot: str,
    transcript: str,
) -> str:
    template = _PROMPT_PATH.read_text()
    replacements = {
        "title": title,
        "channel": channel,
        "channel_url": channel_url,
        "published_at": published_at,
        "duration_seconds": str(duration_seconds),
        "description": description or "(empty)",
        "channel_hint_categories": ", ".join(channel_hint_categories) or "(none)",
        "seed_categories": ", ".join(seed_categories) or "(none)",
        "existing_creator_page": existing_creator_page or "(none)",
        "resources_index_snapshot": resources_index_snapshot or "(empty)",
        "transcript": transcript,
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_extract.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/extract.py tests/test_extract.py
git commit -m "feat(extract): render prompt template with all context placeholders"
```

### Task 16: extract.py — response parsing + validation

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_extract.py
import json

from src.extract import ExtractionError, parse_extraction_response


VALID_RESPONSE = {
    "session_summary": "s",
    "instructions_and_howto": "i",
    "key_takeaways": ["t"],
    "resources": [{"url": "https://x", "title": "X", "description": "d", "group": "Tools"}],
    "categories": ["optimising-ai"],
    "proposed_new_categories": [],
    "tags": ["prompt-caching"],
    "domain": "claude-code",
    "creator_bio_additions": "",
    "connections": [],
}


def test_parse_extraction_response_accepts_valid_json():
    result = parse_extraction_response(json.dumps(VALID_RESPONSE))
    assert result == VALID_RESPONSE


def test_parse_extraction_response_strips_fencing():
    fenced = "```json\n" + json.dumps(VALID_RESPONSE) + "\n```"
    result = parse_extraction_response(fenced)
    assert result == VALID_RESPONSE


def test_parse_extraction_response_raises_on_invalid_json():
    with pytest.raises(ExtractionError, match="not valid JSON"):
        parse_extraction_response("this is not json")


def test_parse_extraction_response_raises_on_missing_required_field():
    broken = {**VALID_RESPONSE}
    del broken["session_summary"]
    with pytest.raises(ExtractionError, match="missing required field"):
        parse_extraction_response(json.dumps(broken))


def test_parse_extraction_response_raises_on_bad_domain():
    bad = {**VALID_RESPONSE, "domain": "unknown-domain"}
    with pytest.raises(ExtractionError, match="domain"):
        parse_extraction_response(json.dumps(bad))


def test_parse_extraction_response_raises_on_bad_resource_group():
    bad = {**VALID_RESPONSE,
           "resources": [{"url": "https://x", "title": "X", "description": "d", "group": "Unknown"}]}
    with pytest.raises(ExtractionError, match="resource group"):
        parse_extraction_response(json.dumps(bad))
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/extract.py
import json
import re


class ExtractionError(Exception):
    pass


_REQUIRED_FIELDS = (
    "session_summary", "instructions_and_howto", "key_takeaways",
    "resources", "categories", "proposed_new_categories",
    "tags", "domain", "creator_bio_additions", "connections",
)

_VALID_DOMAINS = {"claude-code", "prompt-eng", "model-compare", "sdk-api", "workflow"}
_VALID_RESOURCE_GROUPS = {"Tools", "Documentation", "Articles", "Uncategorised"}


def parse_extraction_response(raw: str) -> dict:
    cleaned = raw.strip()
    fence_match = re.match(r"^```(?:json)?\s*\n(.*?)\n```$", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"response not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtractionError("response JSON is not an object")
    for field in _REQUIRED_FIELDS:
        if field not in data:
            raise ExtractionError(f"missing required field: {field}")
    if data["domain"] not in _VALID_DOMAINS:
        raise ExtractionError(f"invalid domain: {data['domain']}")
    for res in data["resources"]:
        if res.get("group") not in _VALID_RESOURCE_GROUPS:
            raise ExtractionError(
                f"invalid resource group: {res.get('group')!r}"
            )
    return data
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_extract.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/extract.py tests/test_extract.py
git commit -m "feat(extract): response parser with JSON-fence stripping and schema validation"
```

### Task 17: extract.py — Claude call with retry on invalid JSON

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_extract.py
from unittest.mock import MagicMock

from src.extract import call_extract


def _fake_message(text: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_call_extract_succeeds_on_first_valid_response(mocker):
    client = MagicMock()
    client.messages.create.return_value = _fake_message(json.dumps(VALID_RESPONSE))
    result = call_extract(client, prompt="p", model="claude-sonnet-4-7")
    assert result == VALID_RESPONSE
    assert client.messages.create.call_count == 1


def test_call_extract_retries_invalid_json_up_to_twice(mocker):
    client = MagicMock()
    client.messages.create.side_effect = [
        _fake_message("not json"),
        _fake_message(json.dumps(VALID_RESPONSE)),
    ]
    result = call_extract(client, prompt="p", model="claude-sonnet-4-7")
    assert result == VALID_RESPONSE
    assert client.messages.create.call_count == 2


def test_call_extract_raises_after_all_retries(mocker):
    client = MagicMock()
    client.messages.create.return_value = _fake_message("still not json")
    with pytest.raises(ExtractionError):
        call_extract(client, prompt="p", model="claude-sonnet-4-7")
    assert client.messages.create.call_count == 3  # initial + 2 retries
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `call_extract` undefined.

- [ ] **Step 3: Implementation**

```python
# append to src/extract.py
MAX_JSON_RETRIES = 2
MAX_OUTPUT_TOKENS = 8000


def call_extract(client, *, prompt: str, model: str) -> dict:
    last_raw: str | None = None
    for attempt in range(MAX_JSON_RETRIES + 1):
        if attempt == 0:
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": last_raw or ""},
                {"role": "user", "content":
                    "That response was not valid JSON matching the required schema. "
                    "Return ONLY the JSON object, no prose and no fences."},
            ]
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=messages,
        )
        raw = response.content[0].text
        last_raw = raw
        try:
            return parse_extraction_response(raw)
        except ExtractionError as exc:
            if attempt == MAX_JSON_RETRIES:
                raise ExtractionError(
                    f"extraction failed after {MAX_JSON_RETRIES + 1} attempts: {exc}"
                ) from exc
    raise AssertionError("unreachable")
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_extract.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/extract.py tests/test_extract.py
git commit -m "feat(extract): Claude call with echo-back retry on invalid JSON"
```

### Task 18: extract.py — wire prompt caching on the system prompt

The spec (Section 6.1) defers cache-block selection to implementation. We'll cache one block holding the static extraction instructions (everything from the prompt template up to but excluding the per-video inputs). This keeps the cache key stable across videos in a run.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_extract.py
from src.extract import split_prompt_for_caching


def test_split_prompt_separates_static_from_variable():
    full = render_extract_prompt(
        title="t", channel="c", channel_url="u",
        published_at="2026-04-15", duration_seconds=10,
        description="d", channel_hint_categories=[],
        seed_categories=["optimising-ai"],
        existing_creator_page="", resources_index_snapshot="",
        transcript="xx",
    )
    static, variable = split_prompt_for_caching(full)
    assert "## Rules" in static
    assert "## Required JSON schema" in static
    assert "## Inputs" not in static
    assert "## Inputs" in variable
    assert "xx" in variable  # transcript is in variable block
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `split_prompt_for_caching` undefined.

- [ ] **Step 3: Implementation**

```python
# append to src/extract.py
_SPLIT_MARKER = "## Inputs"


def split_prompt_for_caching(rendered: str) -> tuple[str, str]:
    idx = rendered.index(_SPLIT_MARKER)
    return rendered[:idx].rstrip(), rendered[idx:]
```

- [ ] **Step 4: Update `call_extract` to use split + cache_control**

Replace the `messages = [...]` construction in `call_extract` with:

```python
        static, variable = split_prompt_for_caching(prompt)
        if attempt == 0:
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": static,
                     "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": variable},
                ],
            }]
        else:
            messages = [
                {"role": "user", "content": [
                    {"type": "text", "text": static,
                     "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": variable},
                ]},
                {"role": "assistant", "content": last_raw or ""},
                {"role": "user", "content":
                    "That response was not valid JSON matching the required schema. "
                    "Return ONLY the JSON object, no prose and no fences."},
            ]
```

- [ ] **Step 5: Re-run all extract tests**

Run: `pytest tests/test_extract.py -v`
Expected: all PASS (the mock ignores cache_control, so behaviour is unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/extract.py tests/test_extract.py
git commit -m "feat(extract): split static/variable prompt and apply ephemeral cache_control"
```

---

## Phase 6 — write.py (vault writers)

### Task 19: write.py — slug helpers

**Files:**
- Create: `src/write.py`
- Create: `tests/test_write.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_write.py
import pytest

from src.write import kebab_slug


@pytest.mark.parametrize("raw,expected", [
    ("Anthropic AI", "anthropic-ai"),
    ("How Prompt Caching Actually Works", "how-prompt-caching-actually-works"),
    ("  Leading/trailing  ", "leading-trailing"),
    ("With !@# punctuation?", "with-punctuation"),
    ("Mix CASE and numbers 2026", "mix-case-and-numbers-2026"),
])
def test_kebab_slug(raw, expected):
    assert kebab_slug(raw) == expected
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `kebab_slug` undefined.

- [ ] **Step 3: Implementation**

```python
# src/write.py
from __future__ import annotations

import re
from pathlib import Path


def kebab_slug(value: str) -> str:
    lowered = value.lower().strip()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    return cleaned.strip("-")
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_write.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/write.py tests/test_write.py
git commit -m "feat(write): kebab-slug helper for filenames"
```

### Task 20: write.py — source page writer

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_write.py
from pathlib import Path

import yaml

from src.write import write_source_page


def _fetch_result_dict(**overrides):
    base = {
        "video_id": "abc12345678",
        "title": "How Prompt Caching Works",
        "description": "desc",
        "channel": "Anthropic",
        "channel_url": "https://www.youtube.com/@AnthropicAI",
        "channel_id": "UCx",
        "duration_seconds": 1847,
        "published_at": "2026-04-15",
        "webpage_url": "https://www.youtube.com/watch?v=abc12345678",
        "raw_transcript_path": Path("raw/youtube/abc12345678.transcript.txt"),
    }
    base.update(overrides)
    return base


def _extraction_dict(**overrides):
    base = {
        "session_summary": "Summary paragraph one.\n\nSummary paragraph two.",
        "instructions_and_howto": "1. First step.\n2. Second step.",
        "key_takeaways": ["Takeaway one", "Takeaway two"],
        "resources": [
            {"url": "https://docs.anthropic.com", "title": "Anthropic Docs",
             "description": "official docs", "group": "Documentation"}
        ],
        "categories": ["optimising-ai", "tool-combinations"],
        "proposed_new_categories": [],
        "tags": ["prompt-caching", "sonnet-4-7"],
        "domain": "claude-code",
        "creator_bio_additions": "",
        "connections": [{"target": "concept-prompt-caching", "note": "demonstrated"}],
    }
    base.update(overrides)
    return base


def test_write_source_page_creates_file_with_correct_name(temp_vault):
    path = write_source_page(
        vault=temp_vault,
        fetch=_fetch_result_dict(),
        extraction=_extraction_dict(),
        creator_slug="creator-anthropic",
        date_ingested="2026-04-21",
    )
    assert path.exists()
    assert path.name == "creator-anthropic--how-prompt-caching-works.md"
    assert path.parent == temp_vault / "wiki" / "sources"


def test_write_source_page_frontmatter_fields(temp_vault):
    path = write_source_page(
        vault=temp_vault,
        fetch=_fetch_result_dict(),
        extraction=_extraction_dict(),
        creator_slug="creator-anthropic",
        date_ingested="2026-04-21",
    )
    text = path.read_text()
    assert text.startswith("---\n")
    front_end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:front_end])
    assert fm["type"] == "source"
    assert fm["source_type"] == "video"
    assert fm["source_platform"] == "youtube"
    assert fm["video_id"] == "abc12345678"
    assert fm["creator"] == "[[creator-anthropic]]"
    assert fm["published_at"] == "2026-04-15"
    assert fm["duration_seconds"] == 1847
    assert fm["categories"] == ["optimising-ai", "tool-combinations"]
    assert fm["domain"] == "claude-code"
    assert fm["raw_path"] == "raw/youtube/abc12345678.transcript.txt"


def test_write_source_page_sections_present(temp_vault):
    path = write_source_page(
        vault=temp_vault,
        fetch=_fetch_result_dict(),
        extraction=_extraction_dict(),
        creator_slug="creator-anthropic",
        date_ingested="2026-04-21",
    )
    text = path.read_text()
    assert "## Session Summary" in text
    assert "## Instructions & How-To" in text
    assert "## Resources Mentioned" in text
    assert "## Key Takeaways" in text
    assert "## Connections" in text
    assert "[Anthropic Docs](https://docs.anthropic.com)" in text
    assert "[[concept-prompt-caching]]" in text
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/write.py
import yaml


def _yaml_frontmatter(data: dict) -> str:
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{body}\n---\n"


def write_source_page(
    *,
    vault: Path,
    fetch: dict,
    extraction: dict,
    creator_slug: str,
    date_ingested: str,
) -> Path:
    video_slug = kebab_slug(fetch["title"])
    filename = f"{creator_slug}--{video_slug}.md"
    path = vault / "wiki" / "sources" / filename
    path.parent.mkdir(parents=True, exist_ok=True)

    fm = {
        "title": fetch["title"],
        "type": "source",
        "source_type": "video",
        "source_platform": "youtube",
        "video_id": fetch["video_id"],
        "video_url": fetch["webpage_url"],
        "creator": f"[[{creator_slug}]]",
        "published_at": fetch["published_at"],
        "duration_seconds": fetch["duration_seconds"],
        "date_ingested": date_ingested,
        "raw_path": f"raw/youtube/{fetch['video_id']}.transcript.txt",
        "categories": extraction["categories"],
        "domain": extraction["domain"],
        "tags": extraction["tags"],
    }
    parts = [
        _yaml_frontmatter(fm),
        "\n## Session Summary\n",
        extraction["session_summary"].strip() + "\n",
        "\n## Instructions & How-To\n",
        extraction["instructions_and_howto"].strip() + "\n",
        "\n## Resources Mentioned\n",
    ]
    if extraction["resources"]:
        for res in extraction["resources"]:
            parts.append(
                f"- [{res['title']}]({res['url']}) — {res['description']}\n"
            )
    else:
        parts.append("_None._\n")
    parts.append("\n## Key Takeaways\n")
    for t in extraction["key_takeaways"]:
        parts.append(f"- {t}\n")
    parts.append("\n## Connections\n")
    if extraction["connections"]:
        for c in extraction["connections"]:
            parts.append(f"- [[{c['target']}]] — {c['note']}\n")
    else:
        parts.append("_None._\n")
    path.write_text("".join(parts))
    return path
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_write.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/write.py tests/test_write.py
git commit -m "feat(write): source page writer with YAML frontmatter and all sections"
```

### Task 21: write.py — creator page (create first, append on subsequent)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_write.py
from src.write import upsert_creator_page


def _creator_inputs(**overrides):
    base = {
        "vault": None,
        "channel": "Anthropic",
        "channel_url": "https://www.youtube.com/@AnthropicAI",
        "channel_id": "UCx",
        "video_title": "How Prompt Caching Works",
        "video_slug": "how-prompt-caching-works",
        "video_summary": "About prompt caching.",
        "video_published_at": "2026-04-15",
        "video_domain": "claude-code",
        "categories": ["optimising-ai"],
        "creator_bio_additions": "",
        "today": "2026-04-21",
    }
    base.update(overrides)
    return base


def test_upsert_creator_page_creates_new(temp_vault):
    inputs = _creator_inputs(vault=temp_vault)
    slug, path = upsert_creator_page(**inputs)
    assert slug == "creator-anthropic"
    assert path == temp_vault / "wiki" / "entities" / "creator-anthropic.md"
    assert path.exists()
    text = path.read_text()
    assert "entity_type: creator" in text
    assert "source_count: 1" in text
    assert "## About" in text
    assert "## Themes" in text
    assert "## Sources" in text
    assert "[[creator-anthropic--how-prompt-caching-works]]" in text


def test_upsert_creator_page_appends_new_source(temp_vault):
    first = _creator_inputs(vault=temp_vault)
    upsert_creator_page(**first)
    second = _creator_inputs(
        vault=temp_vault,
        video_title="Another Video",
        video_slug="another-video",
        video_summary="Other stuff.",
        video_published_at="2026-04-20",
        today="2026-04-21",
    )
    slug, path = upsert_creator_page(**second)
    text = path.read_text()
    assert "source_count: 2" in text
    assert "[[creator-anthropic--how-prompt-caching-works]]" in text
    assert "[[creator-anthropic--another-video]]" in text


def test_upsert_creator_page_appends_bio_additions_with_date(temp_vault):
    first = _creator_inputs(vault=temp_vault)
    upsert_creator_page(**first)
    second = _creator_inputs(
        vault=temp_vault,
        video_title="Second Video",
        video_slug="second-video",
        creator_bio_additions="Joined the DevRel team in April 2026.",
        today="2026-04-21",
    )
    _, path = upsert_creator_page(**second)
    text = path.read_text()
    assert "Joined the DevRel team in April 2026." in text
    assert "2026-04-21" in text
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/write.py
def upsert_creator_page(
    *,
    vault: Path,
    channel: str,
    channel_url: str,
    channel_id: str,
    video_title: str,
    video_slug: str,
    video_summary: str,
    video_published_at: str,
    video_domain: str,
    categories: list[str],
    creator_bio_additions: str,
    today: str,
) -> tuple[str, Path]:
    creator_slug = f"creator-{kebab_slug(channel)}"
    path = vault / "wiki" / "entities" / f"{creator_slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    source_line = (
        f"- [[{creator_slug}--{video_slug}]] — {video_published_at} — "
        f"{video_summary.splitlines()[0] if video_summary else ''}"
    )

    if not path.exists():
        fm = {
            "title": channel,
            "type": "entity",
            "entity_type": "creator",
            "creator_platform": "youtube",
            "channel_url": channel_url,
            "channel_id": channel_id,
            "domain": [video_domain],
            "created": today,
            "updated": today,
            "source_count": 1,
            "tags": ["creator"],
        }
        bio = creator_bio_additions.strip() or "_First sighting — bio to be appended as more videos are ingested._"
        themes = ", ".join(categories) or "_none yet_"
        content = (
            _yaml_frontmatter(fm)
            + f"\n## About\n{bio}\n\n## Themes\n{themes}\n\n## Sources\n{source_line}\n"
        )
        path.write_text(content)
        return creator_slug, path

    existing = path.read_text()
    fm_end = existing.index("\n---\n", 4)
    fm = yaml.safe_load(existing[4:fm_end])
    fm["updated"] = today
    fm["source_count"] = int(fm.get("source_count", 0)) + 1
    domains = set(fm.get("domain") or [])
    domains.add(video_domain)
    fm["domain"] = sorted(domains)
    body = existing[fm_end + 5 :]

    if creator_bio_additions.strip():
        addition = f"\n_Added {today}:_ {creator_bio_additions.strip()}\n"
        body = body.replace("## About\n", f"## About\n", 1)
        # Insert addition after existing About content but before next header.
        about_idx = body.index("## About\n") + len("## About\n")
        next_header = body.index("\n## ", about_idx)
        body = body[:next_header] + addition + body[next_header:]

    themes_header = "## Themes\n"
    themes_start = body.index(themes_header) + len(themes_header)
    themes_end = body.index("\n## ", themes_start)
    current_themes = {t.strip() for t in body[themes_start:themes_end].split(",")}
    current_themes.discard("_none yet_")
    current_themes.update(categories)
    new_themes_block = ", ".join(sorted(t for t in current_themes if t))
    body = body[:themes_start] + new_themes_block + body[themes_end:]

    body = body.rstrip() + "\n" + source_line + "\n"
    path.write_text(_yaml_frontmatter(fm) + body)
    return creator_slug, path
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_write.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/write.py tests/test_write.py
git commit -m "feat(write): creator page upsert — create new, append on subsequent"
```

### Task 22: write.py — resources index upsert

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_write.py
from src.write import upsert_resources_index


def test_upsert_resources_index_creates_file(temp_vault):
    upsert_resources_index(
        vault=temp_vault,
        resources=[
            {"url": "https://docs.anthropic.com", "title": "Docs",
             "description": "official", "group": "Documentation"},
        ],
        source_slug="creator-x--video-y",
        today="2026-04-21",
    )
    path = temp_vault / "wiki" / "sources" / "resources-index.md"
    assert path.exists()
    text = path.read_text()
    assert "type: index" in text
    assert "entry_count: 1" in text
    assert "## Documentation" in text
    assert "https://docs.anthropic.com" in text
    assert "[[creator-x--video-y]]" in text


def test_upsert_resources_index_appends_without_duplicating_url(temp_vault):
    upsert_resources_index(
        vault=temp_vault,
        resources=[
            {"url": "https://docs.anthropic.com", "title": "Docs",
             "description": "official", "group": "Documentation"},
        ],
        source_slug="creator-x--first",
        today="2026-04-21",
    )
    upsert_resources_index(
        vault=temp_vault,
        resources=[
            {"url": "https://docs.anthropic.com", "title": "Docs",
             "description": "official", "group": "Documentation"},
            {"url": "https://github.com/yt-dlp/yt-dlp", "title": "yt-dlp",
             "description": "cli", "group": "Tools"},
        ],
        source_slug="creator-x--second",
        today="2026-04-22",
    )
    path = temp_vault / "wiki" / "sources" / "resources-index.md"
    text = path.read_text()
    # URL appears only once even though submitted twice
    assert text.count("https://docs.anthropic.com") == 1
    # second source is cited
    assert "[[creator-x--second]]" in text
    assert "## Tools" in text
    assert "yt-dlp" in text
    assert "entry_count: 2" in text
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/write.py
_RESOURCE_GROUPS_ORDERED = ("Tools", "Documentation", "Articles", "Uncategorised")


def _parse_resources_index(text: str) -> tuple[dict, dict[str, list[dict]]]:
    """Returns (frontmatter, {group: [entry_dict, ...]}). Each entry has keys:
    url, title, description, sources (list of source slugs)."""
    if not text.startswith("---\n"):
        return {"title": "Resources Index", "type": "index",
                "created": "", "updated": "", "entry_count": 0}, {g: [] for g in _RESOURCE_GROUPS_ORDERED}
    fm_end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:fm_end])
    body = text[fm_end + 5 :]

    groups: dict[str, list[dict]] = {g: [] for g in _RESOURCE_GROUPS_ORDERED}
    current: str | None = None
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped[3:].strip()
            continue
        if current is None or not stripped.startswith("- "):
            continue
        # format: - <url> — <title> — <desc>. Mentioned in: [[slug]], [[slug]]
        try:
            body_part = stripped[2:]
            url_part, rest = body_part.split(" — ", 1)
            title_part, rest = rest.split(" — ", 1)
            desc_part, mention_part = rest.split(". Mentioned in:", 1)
            slugs = re.findall(r"\[\[([^\]]+)\]\]", mention_part)
            groups.setdefault(current, []).append({
                "url": url_part.strip(),
                "title": title_part.strip(),
                "description": desc_part.strip(),
                "sources": slugs,
            })
        except ValueError:
            continue
    return fm, groups


def _render_resources_index(fm: dict, groups: dict[str, list[dict]]) -> str:
    parts = [_yaml_frontmatter(fm)]
    for group in _RESOURCE_GROUPS_ORDERED:
        entries = groups.get(group) or []
        if not entries:
            continue
        parts.append(f"\n## {group}\n")
        for e in entries:
            mentions = ", ".join(f"[[{s}]]" for s in e["sources"])
            parts.append(
                f"- {e['url']} — {e['title']} — {e['description']}. Mentioned in: {mentions}\n"
            )
    return "".join(parts)


def upsert_resources_index(
    *,
    vault: Path,
    resources: list[dict],
    source_slug: str,
    today: str,
) -> Path:
    path = vault / "wiki" / "sources" / "resources-index.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    fm, groups = _parse_resources_index(existing)
    if not fm.get("created"):
        fm["created"] = today
    fm["updated"] = today

    for res in resources:
        group = res["group"]
        existing_entry = next(
            (e for e in groups.get(group, []) if e["url"] == res["url"]), None
        )
        if existing_entry:
            if source_slug not in existing_entry["sources"]:
                existing_entry["sources"].append(source_slug)
        else:
            groups.setdefault(group, []).append({
                "url": res["url"],
                "title": res["title"],
                "description": res["description"],
                "sources": [source_slug],
            })

    fm["entry_count"] = sum(len(v) for v in groups.values())
    path.write_text(_render_resources_index(fm, groups))
    return path
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_write.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/write.py tests/test_write.py
git commit -m "feat(write): resources-index upsert with URL dedup and source citations"
```

### Task 23: write.py — index.md and log.md updates

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_write.py
from src.write import append_index_entries, append_log_entry


def test_append_index_adds_source_and_creator_when_new(temp_vault):
    append_index_entries(
        vault=temp_vault,
        source_slug="creator-x--video-y",
        source_title="Video Y",
        creator_slug="creator-x",
        creator_name="Creator X",
        creator_is_new=True,
    )
    text = (temp_vault / "index.md").read_text()
    assert "[[creator-x--video-y]]" in text
    assert "Video Y" in text
    assert "[[creator-x]]" in text
    assert "Creator X" in text


def test_append_index_skips_creator_when_existing(temp_vault):
    append_index_entries(
        vault=temp_vault,
        source_slug="creator-x--v1",
        source_title="V1",
        creator_slug="creator-x",
        creator_name="Creator X",
        creator_is_new=True,
    )
    append_index_entries(
        vault=temp_vault,
        source_slug="creator-x--v2",
        source_title="V2",
        creator_slug="creator-x",
        creator_name="Creator X",
        creator_is_new=False,
    )
    text = (temp_vault / "index.md").read_text()
    assert text.count("[[creator-x]]") == 1
    assert "[[creator-x--v1]]" in text
    assert "[[creator-x--v2]]" in text


def test_append_log_entry_appends_timestamped(temp_vault):
    append_log_entry(
        vault=temp_vault,
        timestamp="2026-04-21T09:00:00Z",
        message="Ingested video abc12345678 into creator-x--video-y",
    )
    text = (temp_vault / "log.md").read_text()
    assert "2026-04-21T09:00:00Z" in text
    assert "Ingested video abc12345678" in text
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/write.py
def _atomic_write(path: Path, content: str) -> None:
    import os, tempfile
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


def append_index_entries(
    *,
    vault: Path,
    source_slug: str,
    source_title: str,
    creator_slug: str,
    creator_name: str,
    creator_is_new: bool,
) -> None:
    path = vault / "index.md"
    text = path.read_text() if path.exists() else (
        "# Index\n\n## Entities\n\n## Concepts\n\n## Sources\n\n## Analyses\n"
    )

    def append_under(section: str, line: str) -> str:
        header = f"## {section}\n"
        idx = text.index(header) + len(header)
        next_section = text.find("\n## ", idx)
        insert_at = next_section if next_section != -1 else len(text)
        return text[:insert_at].rstrip() + "\n" + line + "\n" + text[insert_at:]

    if creator_is_new:
        text = append_under("Entities", f"- [[{creator_slug}]] — {creator_name}")
    text = append_under("Sources", f"- [[{source_slug}]] — {source_title}")
    _atomic_write(path, text)


def append_log_entry(*, vault: Path, timestamp: str, message: str) -> None:
    path = vault / "log.md"
    existing = path.read_text() if path.exists() else "# Log\n"
    line = f"- {timestamp} — {message}\n"
    path.write_text(existing.rstrip() + "\n" + line)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_write.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/write.py tests/test_write.py
git commit -m "feat(write): atomic index.md updates and log.md appender"
```

---

## Phase 7 — config.py

### Task 24: config.py — load and validate config.yml

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path

import pytest

from src.config import Config, ConfigError, load_config


def test_load_config_parses_valid_yaml(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(
        "watchlist:\n"
        "  - url: https://www.youtube.com/@Foo\n"
        "    default_categories: [optimising-ai]\n"
        "seed_categories: [optimising-ai, building-websites]\n"
        "ingest:\n"
        "  max_videos_per_run: 10\n"
        "  lookback_days: 14\n"
        "  min_duration_seconds: 60\n"
    )
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.seed_categories == ["optimising-ai", "building-websites"]
    assert cfg.watchlist[0].url == "https://www.youtube.com/@Foo"
    assert cfg.watchlist[0].default_categories == ["optimising-ai"]
    assert cfg.ingest.max_videos_per_run == 10
    assert cfg.ingest.lookback_days == 14
    assert cfg.ingest.min_duration_seconds == 60


def test_load_config_allows_empty_watchlist(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(
        "watchlist: []\n"
        "seed_categories: [x]\n"
        "ingest:\n"
        "  max_videos_per_run: 1\n"
        "  lookback_days: 1\n"
        "  min_duration_seconds: 1\n"
    )
    cfg = load_config(p)
    assert cfg.watchlist == []


def test_load_config_raises_on_missing_required(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text("watchlist: []\n")
    with pytest.raises(ConfigError, match="seed_categories"):
        load_config(p)
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# src/config.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    pass


@dataclass
class WatchlistChannel:
    url: str
    default_categories: list[str] = field(default_factory=list)
    min_duration_seconds: int | None = None


@dataclass
class IngestConfig:
    max_videos_per_run: int
    lookback_days: int
    min_duration_seconds: int


@dataclass
class Config:
    watchlist: list[WatchlistChannel]
    seed_categories: list[str]
    ingest: IngestConfig


def load_config(path: Path) -> Config:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ConfigError("config.yml must be a mapping")
    for key in ("watchlist", "seed_categories", "ingest"):
        if key not in data:
            raise ConfigError(f"config.yml missing key: {key}")
    watchlist_raw = data["watchlist"] or []
    watchlist = [
        WatchlistChannel(
            url=item["url"],
            default_categories=item.get("default_categories") or [],
            min_duration_seconds=item.get("min_duration_seconds"),
        )
        for item in watchlist_raw
    ]
    ingest = IngestConfig(
        max_videos_per_run=int(data["ingest"]["max_videos_per_run"]),
        lookback_days=int(data["ingest"]["lookback_days"]),
        min_duration_seconds=int(data["ingest"]["min_duration_seconds"]),
    )
    return Config(
        watchlist=watchlist,
        seed_categories=list(data["seed_categories"]),
        ingest=ingest,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_config.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat(config): load and validate config.yml with typed dataclasses"
```

---

## Phase 8 — slack_queue.py (read)

### Task 25: slack_queue.py — read messages since last_message_ts

**Files:**
- Create: `src/slack_queue.py`
- Create: `tests/test_slack_queue.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slack_queue.py
from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from src.slack_queue import SlackQueueItem, read_pending_urls


def _msg(ts, user, text):
    return {"ts": ts, "user": user, "text": text, "type": "message"}


def test_read_pending_urls_filters_bot_and_extracts(mocker):
    client = MagicMock()
    client.conversations_history.return_value = {
        "messages": [
            _msg("1745.3", "U_HUMAN",
                 "Watch this https://www.youtube.com/watch?v=aaaaaaaaaaa"),
            _msg("1745.2", "U_BOT",
                 "Daily ingest post — https://www.youtube.com/watch?v=xxxxxxxxxxx"),
            _msg("1745.1", "U_HUMAN",
                 "Vimeo https://vimeo.com/12345"),
        ],
        "has_more": False,
    }
    client.conversations_replies.return_value = {"messages": []}

    items = read_pending_urls(
        client=client,
        channel_id="C1",
        last_message_ts=None,
        bot_user_id="U_BOT",
    )
    urls = [i.url for i in items]
    assert any("aaaaaaaaaaa" in u for u in urls)
    assert not any("xxxxxxxxxxx" in u for u in urls)
    assert not any("vimeo" in u for u in urls)


def test_read_pending_urls_respects_last_ts(mocker):
    client = MagicMock()
    client.conversations_history.return_value = {"messages": [], "has_more": False}
    read_pending_urls(client=client, channel_id="C1",
                     last_message_ts="1745.0", bot_user_id="U_BOT")
    client.conversations_history.assert_called_once()
    kwargs = client.conversations_history.call_args.kwargs
    assert kwargs["channel"] == "C1"
    assert kwargs["oldest"] == "1745.0"


def test_read_pending_urls_returns_empty_on_slack_error(mocker):
    client = MagicMock()
    client.conversations_history.side_effect = SlackApiError(
        "slack err", response={"error": "rate_limited"}
    )
    result = read_pending_urls(
        client=client, channel_id="C1",
        last_message_ts=None, bot_user_id="U_BOT",
    )
    assert result == []


def test_read_pending_urls_descends_into_threads(mocker):
    client = MagicMock()
    parent_with_thread = {**_msg("1745.3", "U_HUMAN", "thread starter no url"),
                          "thread_ts": "1745.3", "reply_count": 1}
    client.conversations_history.return_value = {
        "messages": [parent_with_thread],
        "has_more": False,
    }
    client.conversations_replies.return_value = {
        "messages": [
            parent_with_thread,
            _msg("1745.31", "U_HUMAN",
                 "https://youtu.be/bbbbbbbbbbb"),
        ],
    }
    items = read_pending_urls(
        client=client, channel_id="C1",
        last_message_ts=None, bot_user_id="U_BOT",
    )
    assert any("bbbbbbbbbbb" in i.url for i in items)
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# src/slack_queue.py
from __future__ import annotations

import logging
from dataclasses import dataclass

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.fetch import extract_youtube_urls_from_text

logger = logging.getLogger(__name__)


@dataclass
class SlackQueueItem:
    url: str
    message_ts: str
    channel_id: str


def read_pending_urls(
    *,
    client: WebClient,
    channel_id: str,
    last_message_ts: str | None,
    bot_user_id: str | None,
) -> list[SlackQueueItem]:
    try:
        history = client.conversations_history(
            channel=channel_id,
            oldest=last_message_ts or "0",
            inclusive=False,
            limit=200,
        )
    except SlackApiError as exc:
        logger.warning("slack conversations_history failed: %s", exc)
        return []

    items: list[SlackQueueItem] = []
    for msg in history.get("messages", []):
        if msg.get("user") == bot_user_id:
            continue
        _collect_urls(msg, channel_id, items)
        if msg.get("thread_ts") and int(msg.get("reply_count", 0)) > 0:
            try:
                replies = client.conversations_replies(
                    channel=channel_id, ts=msg["thread_ts"]
                )
                for reply in replies.get("messages", []):
                    if reply.get("ts") == msg["thread_ts"]:
                        continue
                    if reply.get("user") == bot_user_id:
                        continue
                    _collect_urls(reply, channel_id, items)
            except SlackApiError as exc:
                logger.warning("slack conversations_replies failed: %s", exc)
    return items


def _collect_urls(msg: dict, channel_id: str, out: list[SlackQueueItem]) -> None:
    for url in extract_youtube_urls_from_text(msg.get("text", "") or ""):
        out.append(SlackQueueItem(url=url, message_ts=msg["ts"], channel_id=channel_id))
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_slack_queue.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slack_queue.py tests/test_slack_queue.py
git commit -m "feat(slack_queue): read channel + threads, filter bot, extract URLs"
```

### Task 26: slack_queue.py — mark-as-processed via reaction

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_slack_queue.py
from src.slack_queue import mark_processed


def test_mark_processed_adds_reaction():
    client = MagicMock()
    mark_processed(client=client, channel_id="C1", message_ts="1745.3")
    client.reactions_add.assert_called_once_with(
        channel="C1", timestamp="1745.3", name="vhs"
    )


def test_mark_processed_swallows_already_reacted(mocker):
    client = MagicMock()
    client.reactions_add.side_effect = SlackApiError(
        "x", response={"error": "already_reacted"}
    )
    mark_processed(client=client, channel_id="C1", message_ts="1745.3")
    # should not raise


def test_mark_processed_reraises_on_other_errors():
    client = MagicMock()
    client.reactions_add.side_effect = SlackApiError(
        "x", response={"error": "channel_not_found"}
    )
    with pytest.raises(SlackApiError):
        mark_processed(client=client, channel_id="C1", message_ts="1745.3")
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `mark_processed` undefined.

- [ ] **Step 3: Implementation**

```python
# append to src/slack_queue.py
def mark_processed(*, client: WebClient, channel_id: str, message_ts: str) -> None:
    try:
        client.reactions_add(channel=channel_id, timestamp=message_ts, name="vhs")
    except SlackApiError as exc:
        if exc.response.get("error") == "already_reacted":
            return
        raise
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_slack_queue.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slack_queue.py tests/test_slack_queue.py
git commit -m "feat(slack_queue): mark_processed reaction (tolerant of already-reacted)"
```

### Task 27: slack_queue.py — resolve bot user id

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_slack_queue.py
from src.slack_queue import resolve_bot_user_id


def test_resolve_bot_user_id_caches_state(mocker):
    client = MagicMock()
    client.auth_test.return_value = {"user_id": "U_BOT_123"}
    state = {"slack_queue": {"last_message_ts": None, "bot_user_id": None}}
    bot_id = resolve_bot_user_id(client, state)
    assert bot_id == "U_BOT_123"
    assert state["slack_queue"]["bot_user_id"] == "U_BOT_123"

    # second call does not re-query
    client.auth_test.reset_mock()
    bot_id_2 = resolve_bot_user_id(client, state)
    assert bot_id_2 == "U_BOT_123"
    client.auth_test.assert_not_called()
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/slack_queue.py
def resolve_bot_user_id(client: WebClient, state: dict) -> str:
    cached = state["slack_queue"].get("bot_user_id")
    if cached:
        return cached
    resp = client.auth_test()
    state["slack_queue"]["bot_user_id"] = resp["user_id"]
    return resp["user_id"]
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_slack_queue.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slack_queue.py tests/test_slack_queue.py
git commit -m "feat(slack_queue): resolve_bot_user_id cached in state"
```

---

## Phase 9 — notify.py (Slack summary write)

### Task 28: notify.py — compose top-level summary

**Files:**
- Create: `src/notify.py`
- Create: `tests/test_notify.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notify.py
from src.notify import RunSummary, VideoResult, compose_top_level


def test_compose_top_level_with_ingests_and_failures():
    summary = RunSummary(
        run_date="2026-04-21 09:00",
        ingested=[
            VideoResult(title="How Prompt Caching Works", creator="Anthropic",
                        categories=["optimising-ai", "tool-combinations"],
                        source_page="wiki/sources/creator-anthropic--how-prompt-caching-works.md",
                        key_takeaways=["t1", "t2", "t3"], resources_count=5,
                        proposed_new_category_slugs=[]),
        ],
        skipped=[{"title": "Short", "reason": "under 60s"}],
        failed=[{"title": "Dead", "video_id": "xyz", "reason": "no captions",
                 "attempt": 2, "moved_dead": False}],
        storage_bytes=142 * 1024 * 1024, storage_video_count=47,
        storage_added_today=3,
        proposed_categories_pending=["agent-orchestration"],
        autopromoted_categories=[],
        dead_today=[],
    )
    text = compose_top_level(summary)
    assert "📼 AI Learnings — daily ingest" in text
    assert "Ingested 1 new" in text
    assert "skipped 1" in text
    assert "failed 1" in text
    assert "How Prompt Caching Works" in text
    assert "optimising-ai" in text
    assert "under 60s" in text
    assert "raw/youtube: 142 MB" in text
    assert "47 videos" in text
    assert "+3 today" in text
    assert "agent-orchestration" in text


def test_compose_top_level_heartbeat_on_zero_ingest():
    summary = RunSummary(
        run_date="2026-04-21 09:00",
        ingested=[], skipped=[], failed=[],
        storage_bytes=0, storage_video_count=0,
        storage_added_today=0,
        proposed_categories_pending=[],
        autopromoted_categories=[],
        dead_today=[],
    )
    text = compose_top_level(summary)
    assert "📼" in text
    assert "0 new" in text
    assert "idle" in text.lower() or "nothing new" in text.lower()
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# src/notify.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


@dataclass
class VideoResult:
    title: str
    creator: str
    categories: list[str]
    source_page: str
    key_takeaways: list[str]
    resources_count: int
    proposed_new_category_slugs: list[str] = field(default_factory=list)


@dataclass
class RunSummary:
    run_date: str
    ingested: list[VideoResult]
    skipped: list[dict]  # {title, reason}
    failed: list[dict]   # {title, video_id, reason, attempt, moved_dead}
    storage_bytes: int
    storage_video_count: int
    storage_added_today: int
    proposed_categories_pending: list[str]
    autopromoted_categories: list[str]
    dead_today: list[dict]  # {video_id, reason}


def _mb(value: int) -> str:
    return f"{value / (1024 * 1024):.0f} MB"


def compose_top_level(summary: RunSummary) -> str:
    lines = [f"📼 AI Learnings — daily ingest · {summary.run_date}"]
    lines.append(
        f"Ingested {len(summary.ingested)} new · "
        f"skipped {len(summary.skipped)} · "
        f"failed {len(summary.failed)}"
    )
    if not summary.ingested and not summary.skipped and not summary.failed:
        lines.append("")
        lines.append("_Watchlist idle — nothing new today._")
    if summary.ingested:
        lines.append("")
        lines.append("NEW")
        for v in summary.ingested:
            cats = ", ".join(v.categories) or "—"
            extra = ""
            if v.proposed_new_category_slugs:
                extra = (
                    " ⚠️ proposed new category: "
                    + ", ".join(v.proposed_new_category_slugs)
                )
            lines.append(f"• \"{v.title}\" — {v.creator} — {cats}{extra}")
    if summary.skipped:
        lines.append("")
        lines.append("SKIPPED")
        for s in summary.skipped:
            lines.append(f"• \"{s['title']}\" — {s['reason']}")
    lines.append("")
    lines.append("STORAGE")
    lines.append(
        f"raw/youtube: {_mb(summary.storage_bytes)} "
        f"({summary.storage_video_count} videos · +{summary.storage_added_today} today)"
    )
    if summary.proposed_categories_pending or summary.autopromoted_categories:
        lines.append("")
        lines.append("REVIEW QUEUE")
        if summary.proposed_categories_pending:
            lines.append(
                f"• {len(summary.proposed_categories_pending)} proposed "
                f"categories awaiting rename/merge: "
                + ", ".join(summary.proposed_categories_pending)
            )
        for slug in summary.autopromoted_categories:
            lines.append(
                f"• ℹ️ `{slug}` auto-promoted to seed list after 3 uses — "
                "edit config.yml to rename/merge if desired"
            )
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_notify.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/notify.py tests/test_notify.py
git commit -m "feat(notify): compose_top_level summary with storage and review queue"
```

### Task 29: notify.py — compose threaded replies

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_notify.py
from src.notify import compose_video_reply, compose_failure_reply


def test_compose_video_reply_contains_all_fields():
    video = VideoResult(
        title="Prompt Caching",
        creator="Anthropic",
        categories=["optimising-ai"],
        source_page="wiki/sources/creator-anthropic--prompt-caching.md",
        key_takeaways=["One", "Two", "Three"],
        resources_count=5,
    )
    text = compose_video_reply(video)
    assert "Prompt Caching" in text
    assert "Anthropic" in text
    assert "wiki/sources/creator-anthropic--prompt-caching.md" in text
    assert "3 takeaways" in text
    assert "5 resources" in text
    assert "optimising-ai" in text
    assert "One" in text and "Two" in text and "Three" in text


def test_compose_failure_reply_marks_dead_flag():
    text = compose_failure_reply({
        "title": "Dead Video",
        "video_id": "xyz",
        "reason": "no captions",
        "attempt": 3,
        "moved_dead": True,
    })
    assert "❌" in text
    assert "Dead Video" in text
    assert "xyz" in text
    assert "no captions" in text
    assert "moved to dead" in text


def test_compose_failure_reply_shows_retry_count():
    text = compose_failure_reply({
        "title": "Video",
        "video_id": "abc",
        "reason": "llm_error",
        "attempt": 1,
        "moved_dead": False,
    })
    assert "retry 1 of 3" in text
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/notify.py
def compose_video_reply(video: VideoResult) -> str:
    cats = ", ".join(video.categories) or "—"
    lines = [
        f"\"{video.title}\" — {video.creator}",
        f"📂 {video.source_page}",
        f"📝 {len(video.key_takeaways)} takeaways · "
        f"🔗 {video.resources_count} resources · 🏷 {cats}",
    ]
    for t in video.key_takeaways:
        lines.append(f"Takeaway: {t}")
    return "\n".join(lines)


def compose_failure_reply(failure: dict) -> str:
    next_line = (
        "moved to dead" if failure["moved_dead"]
        else f"retry {failure['attempt']} of 3"
    )
    return (
        f"❌ \"{failure['title']}\" — {failure['video_id']}\n"
        f"Reason: {failure['reason']}\n"
        f"Next: {next_line}"
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_notify.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/notify.py tests/test_notify.py
git commit -m "feat(notify): per-video and per-failure threaded reply composers"
```

### Task 30: notify.py — post summary and threads

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_notify.py
from unittest.mock import MagicMock

from src.notify import post_run_summary


def test_post_run_summary_posts_top_level_then_threads():
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1745.5"}
    summary = RunSummary(
        run_date="2026-04-21 09:00",
        ingested=[VideoResult(title="A", creator="c", categories=["x"],
                              source_page="p", key_takeaways=["t"], resources_count=1)],
        skipped=[], failed=[{"title": "F", "video_id": "v", "reason": "r",
                             "attempt": 1, "moved_dead": False}],
        storage_bytes=0, storage_video_count=0, storage_added_today=0,
        proposed_categories_pending=[], autopromoted_categories=[], dead_today=[],
    )
    ok, delivery_log = post_run_summary(
        client=client, channel_id="C1", summary=summary,
    )
    assert ok is True
    # three posts: top-level, video reply, failure reply
    assert client.chat_postMessage.call_count == 3
    top_call = client.chat_postMessage.call_args_list[0]
    assert top_call.kwargs["channel"] == "C1"
    assert "📼" in top_call.kwargs["text"]
    video_call = client.chat_postMessage.call_args_list[1]
    assert video_call.kwargs["thread_ts"] == "1745.5"
    failure_call = client.chat_postMessage.call_args_list[2]
    assert failure_call.kwargs["thread_ts"] == "1745.5"


def test_post_run_summary_returns_false_on_slack_error():
    client = MagicMock()
    client.chat_postMessage.side_effect = SlackApiError(
        "err", response={"error": "channel_not_found"}
    )
    summary = RunSummary(run_date="2026-04-21", ingested=[], skipped=[], failed=[],
                         storage_bytes=0, storage_video_count=0, storage_added_today=0,
                         proposed_categories_pending=[], autopromoted_categories=[],
                         dead_today=[])
    ok, log = post_run_summary(client=client, channel_id="C1", summary=summary)
    assert ok is False
    assert "error" in log
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/notify.py
def post_run_summary(
    *,
    client: WebClient,
    channel_id: str,
    summary: RunSummary,
) -> tuple[bool, dict]:
    try:
        top = client.chat_postMessage(
            channel=channel_id, text=compose_top_level(summary)
        )
        parent_ts = top["ts"]
        for v in summary.ingested:
            client.chat_postMessage(
                channel=channel_id, thread_ts=parent_ts,
                text=compose_video_reply(v),
            )
        for f in summary.failed:
            client.chat_postMessage(
                channel=channel_id, thread_ts=parent_ts,
                text=compose_failure_reply(f),
            )
        return True, {"top_ts": parent_ts}
    except SlackApiError as exc:
        logger.warning("slack post failed: %s", exc)
        return False, {"error": str(exc)}
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_notify.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/notify.py tests/test_notify.py
git commit -m "feat(notify): post top-level + threaded replies with error handling"
```

### Task 31: notify.py — catch-up for undelivered summaries

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_notify.py
import json
from pathlib import Path

from src.notify import deliver_undelivered_summaries


def test_deliver_undelivered_drains_state_on_success(tmp_path):
    log_path = tmp_path / "missed.json"
    log_path.write_text(json.dumps({
        "run_date": "2026-04-20 09:00",
        "ingested": [], "skipped": [], "failed": [],
        "storage_bytes": 0, "storage_video_count": 0, "storage_added_today": 0,
        "proposed_categories_pending": [], "autopromoted_categories": [],
        "dead_today": [],
    }))
    state = {"undelivered_summaries": [
        {"run_date": "2026-04-20 09:00", "log_path": str(log_path)}
    ]}
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1745.5"}

    deliver_undelivered_summaries(client=client, channel_id="C1", state=state)
    assert state["undelivered_summaries"] == []
    first_text = client.chat_postMessage.call_args_list[0].kwargs["text"]
    assert "delayed from" in first_text


def test_deliver_undelivered_retains_on_failure(tmp_path):
    log_path = tmp_path / "missed.json"
    log_path.write_text(json.dumps({
        "run_date": "2026-04-20 09:00",
        "ingested": [], "skipped": [], "failed": [],
        "storage_bytes": 0, "storage_video_count": 0, "storage_added_today": 0,
        "proposed_categories_pending": [], "autopromoted_categories": [],
        "dead_today": [],
    }))
    state = {"undelivered_summaries": [
        {"run_date": "2026-04-20 09:00", "log_path": str(log_path)}
    ]}
    client = MagicMock()
    client.chat_postMessage.side_effect = SlackApiError(
        "x", response={"error": "channel_not_found"}
    )
    deliver_undelivered_summaries(client=client, channel_id="C1", state=state)
    assert len(state["undelivered_summaries"]) == 1
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/notify.py
import json
from pathlib import Path


def _summary_from_log(log: dict) -> RunSummary:
    return RunSummary(
        run_date=log["run_date"],
        ingested=[VideoResult(**v) for v in log.get("ingested", [])],
        skipped=log.get("skipped", []),
        failed=log.get("failed", []),
        storage_bytes=log.get("storage_bytes", 0),
        storage_video_count=log.get("storage_video_count", 0),
        storage_added_today=log.get("storage_added_today", 0),
        proposed_categories_pending=log.get("proposed_categories_pending", []),
        autopromoted_categories=log.get("autopromoted_categories", []),
        dead_today=log.get("dead_today", []),
    )


def deliver_undelivered_summaries(
    *,
    client: WebClient,
    channel_id: str,
    state: dict,
) -> None:
    pending = list(state.get("undelivered_summaries", []))
    remaining: list[dict] = []
    for entry in pending:
        try:
            data = json.loads(Path(entry["log_path"]).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning("cannot read undelivered log %s: %s", entry, exc)
            continue
        summary = _summary_from_log(data)
        prefixed = RunSummary(
            run_date=f"⚠ delayed from {summary.run_date}",
            ingested=summary.ingested, skipped=summary.skipped, failed=summary.failed,
            storage_bytes=summary.storage_bytes,
            storage_video_count=summary.storage_video_count,
            storage_added_today=summary.storage_added_today,
            proposed_categories_pending=summary.proposed_categories_pending,
            autopromoted_categories=summary.autopromoted_categories,
            dead_today=summary.dead_today,
        )
        ok, _ = post_run_summary(client=client, channel_id=channel_id, summary=prefixed)
        if not ok:
            remaining.append(entry)
    state["undelivered_summaries"] = remaining
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_notify.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/notify.py tests/test_notify.py
git commit -m "feat(notify): deliver_undelivered_summaries drains state on success"
```

---

## Phase 10 — main.py orchestration

### Task 32: main.py — queue unification and dedup

**Files:**
- Create: `src/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
from src.main import UrlCandidate, build_unified_queue
from src.slack_queue import SlackQueueItem


def test_build_unified_queue_preserves_order_and_dedups():
    candidates = build_unified_queue(
        queue_txt_urls=["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
        slack_items=[
            SlackQueueItem(url="https://www.youtube.com/watch?v=bbbbbbbbbbb",
                           message_ts="1745.3", channel_id="C1"),
            # dup of queue.txt via shortened form
            SlackQueueItem(url="https://youtu.be/aaaaaaaaaaa",
                           message_ts="1745.4", channel_id="C1"),
        ],
        watchlist_urls=["https://www.youtube.com/watch?v=ccccccccccc"],
        already_ingested={"ccccccccccc"},
    )
    ids = [c.video_id for c in candidates]
    assert ids == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert candidates[0].source == "queue.txt"
    assert candidates[1].source == "slack"


def test_build_unified_queue_skips_dead_and_ingested():
    candidates = build_unified_queue(
        queue_txt_urls=["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
        slack_items=[],
        watchlist_urls=[],
        already_ingested={"aaaaaaaaaaa"},
    )
    assert candidates == []
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# src/main.py
from __future__ import annotations

from dataclasses import dataclass

from src.fetch import extract_video_id
from src.slack_queue import SlackQueueItem


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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_main.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(main): unified queue with dedup and source provenance"
```

### Task 33: main.py — queue.txt drain (atomic truncate on success)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_main.py
from pathlib import Path

from src.main import drain_queue_txt


def test_drain_queue_txt_returns_lines_and_truncates(tmp_path):
    q = tmp_path / "queue.txt"
    q.write_text(
        "https://www.youtube.com/watch?v=aaaaaaaaaaa\n"
        "https://youtu.be/bbbbbbbbbbb\n"
        "\n"
        "# comment line ignored\n"
    )
    urls = drain_queue_txt(q)
    assert "https://www.youtube.com/watch?v=aaaaaaaaaaa" in urls
    assert "https://youtu.be/bbbbbbbbbbb" in urls
    assert q.read_text() == ""


def test_drain_queue_txt_missing_file_returns_empty(tmp_path):
    q = tmp_path / "queue.txt"
    assert drain_queue_txt(q) == []
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/main.py
from pathlib import Path


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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_main.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(main): drain_queue_txt reads-and-truncates"
```

### Task 34: main.py — storage footprint calculation

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_main.py
from src.main import raw_storage_footprint


def test_raw_storage_footprint(tmp_path):
    raw_dir = tmp_path / "raw" / "youtube"
    raw_dir.mkdir(parents=True)
    (raw_dir / "a.transcript.txt").write_text("a" * 1000)
    (raw_dir / "b.transcript.txt").write_text("b" * 2000)
    bytes_, count = raw_storage_footprint(raw_dir)
    assert count == 2
    assert bytes_ == 3000


def test_raw_storage_footprint_missing_dir(tmp_path):
    bytes_, count = raw_storage_footprint(tmp_path / "nonexistent")
    assert bytes_ == 0
    assert count == 0
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/main.py
def raw_storage_footprint(raw_dir: Path) -> tuple[int, int]:
    if not raw_dir.exists():
        return 0, 0
    files = list(raw_dir.glob("*.transcript.txt"))
    return sum(f.stat().st_size for f in files), len(files)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_main.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(main): raw_storage_footprint counts transcripts and bytes"
```

### Task 35: main.py — process_one_video (fetch + extract + write + state)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_main.py
import json
from pathlib import Path
from unittest.mock import MagicMock

from src.fetch import FetchResult


def _fetch_fixture(fixtures_dir: Path, raw_dir: Path) -> FetchResult:
    meta = json.loads((fixtures_dir / "sample-video.json").read_text())
    transcript = (fixtures_dir / "sample-transcript.txt").read_text()
    raw_path = raw_dir / f"{meta['id']}.transcript.txt"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(transcript)
    return FetchResult(
        video_id=meta["id"], title=meta["title"], description=meta["description"],
        channel=meta["channel"], channel_url=meta["channel_url"],
        channel_id=meta["channel_id"], duration_seconds=meta["duration"],
        published_at="2026-04-15", webpage_url=meta["webpage_url"],
        transcript=transcript, raw_transcript_path=raw_path,
    )


def test_process_one_video_writes_all_artifacts(mocker, temp_vault, fixtures_dir):
    from src.main import process_one_video
    fetch_result = _fetch_fixture(fixtures_dir, temp_vault / "raw" / "youtube")
    extraction = {
        "session_summary": "About prompt caching.",
        "instructions_and_howto": "1. Do this.\n2. Do that.",
        "key_takeaways": ["Cache writes cost more than reads"],
        "resources": [{"url": "https://docs.anthropic.com/caching",
                       "title": "Caching docs", "description": "official",
                       "group": "Documentation"}],
        "categories": ["optimising-ai"],
        "proposed_new_categories": [],
        "tags": ["prompt-caching"],
        "domain": "claude-code",
        "creator_bio_additions": "",
        "connections": [],
    }
    mocker.patch("src.main.fetch_video", return_value=fetch_result)
    mocker.patch("src.main.call_extract", return_value=extraction)
    state = {"ingested_video_ids": {}, "channels": {}, "failed_videos": {},
             "dead_videos": {}, "proposed_categories": {},
             "slack_queue": {"last_message_ts": None, "bot_user_id": None},
             "undelivered_summaries": []}

    result = process_one_video(
        url=fetch_result.webpage_url,
        client=MagicMock(),
        vault=temp_vault,
        state=state,
        seed_categories=["optimising-ai"],
        channel_hint_categories=[],
        today="2026-04-21",
        now_iso="2026-04-21T09:00:00Z",
        model="claude-sonnet-4-7",
    )

    assert result.video_id == fetch_result.video_id
    source_path = temp_vault / "wiki" / "sources" / result.source_page
    assert source_path.exists()
    creator_path = temp_vault / "wiki" / "entities" / f"{result.creator_slug}.md"
    assert creator_path.exists()
    resources_path = temp_vault / "wiki" / "sources" / "resources-index.md"
    assert resources_path.exists()
    assert fetch_result.video_id in state["ingested_video_ids"]
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL.

- [ ] **Step 3: Implementation**

```python
# append to src/main.py
import logging
from dataclasses import dataclass

from anthropic import Anthropic

from src.extract import ExtractionError, call_extract, render_extract_prompt
from src.fetch import FetchError, fetch_video
from src.state import mark_ingested, record_failure, record_proposed_category
from src.write import (
    append_index_entries, append_log_entry, kebab_slug,
    upsert_creator_page, upsert_resources_index, write_source_page,
)

logger = logging.getLogger(__name__)


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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_main.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(main): process_one_video wires fetch + extract + write + state"
```

### Task 36: main.py — run_once entry point with Slack integration

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_main.py
from src.main import run_once


def test_run_once_heartbeat_on_empty(mocker, temp_vault, tmp_path):
    from slack_sdk import WebClient
    mocker.patch("src.main.self_update_ytdlp")
    slack_client = mocker.patch("src.main.WebClient").return_value
    slack_client.auth_test.return_value = {"user_id": "U_BOT"}
    slack_client.chat_postMessage.return_value = {"ts": "1745.5"}
    slack_client.conversations_history.return_value = {"messages": [], "has_more": False}
    mocker.patch("src.main.Anthropic")

    state_path = tmp_path / "state.json"
    queue_path = tmp_path / "queue.txt"
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        "watchlist: []\n"
        "seed_categories: [optimising-ai]\n"
        "ingest:\n"
        "  max_videos_per_run: 10\n"
        "  lookback_days: 14\n"
        "  min_duration_seconds: 60\n"
    )

    run_once(
        config_path=config_path, state_path=state_path, queue_path=queue_path,
        vault=temp_vault, slack_channel_id="C1", anthropic_api_key="x",
        slack_bot_token="y", today="2026-04-21", now_iso="2026-04-21T09:00:00Z",
    )

    # top-level heartbeat posted
    assert slack_client.chat_postMessage.called
    top_text = slack_client.chat_postMessage.call_args_list[0].kwargs["text"]
    assert "📼" in top_text
    assert "0 new" in top_text
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL — `run_once` undefined.

- [ ] **Step 3: Implementation**

```python
# append to src/main.py
from datetime import datetime, timezone

from anthropic import Anthropic
from slack_sdk import WebClient

from src.config import load_config
from src.fetch import list_new_videos_for_channel, self_update_ytdlp
from src.notify import (
    RunSummary, VideoResult,
    deliver_undelivered_summaries, post_run_summary,
)
from src.slack_queue import (
    SlackQueueItem, mark_processed,
    read_pending_urls, resolve_bot_user_id,
)
from src.state import load_state, save_state


def run_once(
    *,
    config_path: Path,
    state_path: Path,
    queue_path: Path,
    vault: Path,
    slack_channel_id: str,
    anthropic_api_key: str,
    slack_bot_token: str,
    today: str | None = None,
    now_iso: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    today = today or now.strftime("%Y-%m-%d")
    now_iso = now_iso or now.strftime("%Y-%m-%dT%H:%M:%SZ")

    cfg = load_config(config_path)
    state = load_state(state_path)
    slack_client = WebClient(token=slack_bot_token)
    anthropic_client = Anthropic(api_key=anthropic_api_key)

    try:
        self_update_ytdlp()
    except RuntimeError as exc:
        logger.error("yt-dlp self-update failed: %s", exc)

    bot_user_id = resolve_bot_user_id(slack_client, state)

    deliver_undelivered_summaries(
        client=slack_client, channel_id=slack_channel_id, state=state
    )

    slack_items = read_pending_urls(
        client=slack_client,
        channel_id=slack_channel_id,
        last_message_ts=state["slack_queue"]["last_message_ts"],
        bot_user_id=bot_user_id,
    )

    queue_urls = drain_queue_txt(queue_path)

    watchlist_urls: list[str] = []
    hint_by_video_id: dict[str, list[str]] = {}
    for channel in cfg.watchlist:
        channel_state = state["channels"].setdefault(channel.url, {
            "last_checked_at": None, "last_seen_video_id": None,
        })
        try:
            new_videos = list_new_videos_for_channel(
                channel.url,
                last_seen_video_id=channel_state.get("last_seen_video_id"),
                lookback_days=cfg.ingest.lookback_days,
                now=today,
            )
        except Exception as exc:
            logger.warning("watchlist poll failed for %s: %s", channel.url, exc)
            continue
        for v in new_videos:
            url = v.get("url") or f"https://www.youtube.com/watch?v={v['id']}"
            watchlist_urls.append(url)
            hint_by_video_id[v["id"]] = channel.default_categories
        if new_videos:
            channel_state["last_seen_video_id"] = new_videos[0].get("id")
        channel_state["last_checked_at"] = now_iso

    already_ingested = set(state["ingested_video_ids"].keys()) | set(state["dead_videos"].keys())
    queue = build_unified_queue(
        queue_txt_urls=queue_urls,
        slack_items=slack_items,
        watchlist_urls=watchlist_urls,
        already_ingested=already_ingested,
    )[: cfg.ingest.max_videos_per_run]

    ingested: list[VideoResult] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    dead_today: list[dict] = []

    for cand in queue:
        try:
            result = process_one_video(
                url=cand.url,
                client=anthropic_client,
                vault=vault,
                state=state,
                seed_categories=cfg.seed_categories + _autopromoted(state),
                channel_hint_categories=hint_by_video_id.get(cand.video_id, []),
                today=today,
                now_iso=now_iso,
            )
            if cand.slack_item is not None:
                try:
                    mark_processed(
                        client=slack_client,
                        channel_id=cand.slack_item.channel_id,
                        message_ts=cand.slack_item.message_ts,
                    )
                except Exception as exc:
                    logger.warning("slack reaction failed: %s", exc)
            ingested.append(VideoResult(
                title=result.title, creator=result.creator,
                categories=result.categories,
                source_page=f"wiki/sources/{result.source_page}",
                key_takeaways=result.key_takeaways[:3],
                resources_count=result.resources_count,
                proposed_new_category_slugs=result.proposed_new_category_slugs,
            ))
        except FetchError as exc:
            record_failure(state, video_id=cand.video_id,
                           reason=str(exc), now=now_iso)
            moved = cand.video_id in state["dead_videos"]
            attempt = state["failed_videos"].get(cand.video_id, {}).get("attempts", 3)
            failed.append({
                "title": f"<{cand.video_id}>", "video_id": cand.video_id,
                "reason": str(exc), "attempt": attempt, "moved_dead": moved,
            })
            if moved:
                dead_today.append({"video_id": cand.video_id, "reason": str(exc)})
        except ExtractionError as exc:
            record_failure(state, video_id=cand.video_id,
                           reason=f"llm: {exc}", now=now_iso)
            failed.append({
                "title": f"<{cand.video_id}>", "video_id": cand.video_id,
                "reason": f"llm: {exc}",
                "attempt": state["failed_videos"].get(cand.video_id, {}).get("attempts", 1),
                "moved_dead": cand.video_id in state["dead_videos"],
            })
        if cand.slack_item is not None:
            ts = cand.slack_item.message_ts
            prev = state["slack_queue"].get("last_message_ts") or "0"
            if float(ts) > float(prev):
                state["slack_queue"]["last_message_ts"] = ts

    storage_bytes, storage_count = raw_storage_footprint(vault / "raw" / "youtube")
    pending_categories = [
        slug for slug, entry in state["proposed_categories"].items()
        if entry["status"] == "pending"
    ]
    autopromoted = [
        slug for slug, entry in state["proposed_categories"].items()
        if entry["status"] == "auto-promoted"
    ]

    summary = RunSummary(
        run_date=now.strftime("%Y-%m-%d %H:%M"),
        ingested=ingested, skipped=skipped, failed=failed,
        storage_bytes=storage_bytes, storage_video_count=storage_count,
        storage_added_today=len(ingested),
        proposed_categories_pending=pending_categories,
        autopromoted_categories=autopromoted,
        dead_today=dead_today,
    )
    ok, _ = post_run_summary(
        client=slack_client, channel_id=slack_channel_id, summary=summary,
    )
    if not ok:
        log_path = vault.parent / "logs" / f"{today}.json"
        # Run summary log is kept next to the project logs/ — write path is env-derived.
        _log_summary_for_retry(summary, log_path, state)

    save_state(state_path, state)


def _autopromoted(state: dict) -> list[str]:
    return [
        slug for slug, entry in state["proposed_categories"].items()
        if entry["status"] == "auto-promoted"
    ]


def _log_summary_for_retry(summary: RunSummary, log_path: Path, state: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_date": summary.run_date,
        "ingested": [v.__dict__ for v in summary.ingested],
        "skipped": summary.skipped,
        "failed": summary.failed,
        "storage_bytes": summary.storage_bytes,
        "storage_video_count": summary.storage_video_count,
        "storage_added_today": summary.storage_added_today,
        "proposed_categories_pending": summary.proposed_categories_pending,
        "autopromoted_categories": summary.autopromoted_categories,
        "dead_today": summary.dead_today,
    }
    log_path.write_text(json.dumps(payload))
    state["undelivered_summaries"].append({
        "run_date": summary.run_date, "log_path": str(log_path),
    })


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()
    project_root = Path(__file__).resolve().parent.parent
    vault = Path(os.environ["VAULT_PATH"])
    run_once(
        config_path=project_root / "config.yml",
        state_path=project_root / "state.json",
        queue_path=project_root / "queue.txt",
        vault=vault,
        slack_channel_id=os.environ["SLACK_CHANNEL_ID"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_main.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(main): run_once orchestrator wires all modules + Slack heartbeat"
```

---

## Phase 11 — launchd, vault patch, README, smoke test

### Task 37: launchd plist for 09:00 daily

**Files:**
- Create: `com.steven.ytingest.plist`

- [ ] **Step 1: Write the plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.steven.ytingest</string>

  <key>ProgramArguments</key>
  <array>
    <string>/Users/steven/Vibe Projects/youtube-transcript-ailearning/.venv/bin/python</string>
    <string>-m</string>
    <string>src.main</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/steven/Vibe Projects/youtube-transcript-ailearning</string>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>9</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>StandardOutPath</key>
  <string>/Users/steven/Vibe Projects/youtube-transcript-ailearning/logs/launchd.stdout.log</string>

  <key>StandardErrorPath</key>
  <string>/Users/steven/Vibe Projects/youtube-transcript-ailearning/logs/launchd.stderr.log</string>

  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
```

- [ ] **Step 2: Validate the plist parses**

Run: `plutil -lint "/Users/steven/Vibe Projects/youtube-transcript-ailearning/com.steven.ytingest.plist"`
Expected: `OK` status.

- [ ] **Step 3: Commit**

```bash
git add com.steven.ytingest.plist
git commit -m "feat(launchd): daily 09:00 plist for main.py"
```

### Task 38: Patch vault CLAUDE.md with new schema variants

**Files:**
- Modify: `/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/CLAUDE.md`

This is a cross-project edit. No tests — the vault's CLAUDE.md is a doc, not code.

- [ ] **Step 1: Read the current file to locate the `### Entity Page` and `### Source Summary` sections**

Run: `cat "/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/CLAUDE.md" | head -110`

- [ ] **Step 2: Add a YouTube-video variant under `### Source Summary (wiki/sources/)`**

Append, immediately after the existing Source Summary schema block, a second schema block titled **Video source (YouTube)** documenting the extended frontmatter fields and sections used by this ingestion pipeline. Keep the original schema unchanged so `source_type: article | transcript | notes | pdf | release-notes` pages are still valid.

Use this patch text (append directly after the closing triple backtick of the base schema and before the section-description line starting `Sections:`):

````markdown
**Video source (YouTube) extensions** — for pages created by the
`youtube-transcript-ailearning` pipeline, the schema adds these
frontmatter fields and sections:

```yaml
source_type: video
source_platform: youtube
video_id: <11-char-id>
video_url: https://www.youtube.com/watch?v=<id>
creator: "[[creator-<slug>]]"
published_at: YYYY-MM-DD
duration_seconds: N
categories: [list of category slugs]
```

Video sources use these sections (in order):
`## Session Summary`, `## Instructions & How-To`, `## Resources Mentioned`,
`## Key Takeaways`, `## Connections`.
````

- [ ] **Step 3: Add `creator` under `### Entity Page`**

Under the Entity Page schema section, extend the `entity_type` enumeration from
`entity_type: model | sdk | tool | provider | feature`
to
`entity_type: model | sdk | tool | provider | feature | creator`

Add a paragraph after the schema block:

```markdown
**Creator entity** — a YouTube channel / podcast host. Created on first sighting and
appended (not overwritten) on subsequent sightings. Uses extra frontmatter:
`creator_platform`, `channel_url`, `channel_id`. Sections: `## About`, `## Themes`,
`## Sources`. Bio additions are date-stamped (`_Added YYYY-MM-DD:_ ...`) under
`## About`.
```

- [ ] **Step 4: Manually eyeball the diff**

Run:
```bash
cd "/Users/steven/Vibe Projects/wiki-knowledge-interface"
git diff "vaults/AI Learnings/CLAUDE.md"
```
Expected: only additions, no deletions outside the `entity_type` line.

- [ ] **Step 5: Commit in the vault repo (if it is a git repo)**

```bash
cd "/Users/steven/Vibe Projects/wiki-knowledge-interface"
if [ -d .git ]; then
  git add "vaults/AI Learnings/CLAUDE.md"
  git commit -m "docs(vault): add video source and creator entity variants"
fi
```
If the wiki-knowledge-interface is not a git repo, skip the commit — the file change is already saved.

### Task 39: README.md with setup instructions

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write**

````markdown
# YouTube Transcript → AI Learnings

Ingests YouTube videos from a watchlist, Slack channel drops, and a local queue file;
extracts structured learning content via Claude; writes source + creator + resources
pages to the AI Learnings wiki vault; posts a daily summary to Slack.

Spec: `docs/superpowers/specs/2026-04-21-youtube-transcript-ingestion-design.md`
Plan: `docs/superpowers/plans/2026-04-21-youtube-transcript-ingestion.md`

## One-time setup

1. **Python + deps**
   ```bash
   python3.12 -m venv .venv
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
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with setup, manual push, launchd, review workflow"
```

### Task 40: End-to-end smoke test

This task verifies the full pipeline against a real video, real Claude, real Slack.
It is a one-off verification, not an automated test.

- [ ] **Step 1: Seed a single watchlist entry**

Edit `config.yml`:
```yaml
watchlist:
  - url: https://www.youtube.com/@AnthropicAI
    default_categories: [optimising-ai]
```

- [ ] **Step 2: Run manually**

```bash
source .venv/bin/activate
python -m src.main
```
Expected: completes without uncaught exception; takes 30s–2min depending on
channel size.

- [ ] **Step 3: Verify vault artifacts**

Run:
```bash
ls "/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/wiki/sources/" | head
ls "/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/wiki/entities/" | head
cat "/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/index.md"
tail -n 20 "/Users/steven/Vibe Projects/wiki-knowledge-interface/vaults/AI Learnings/log.md"
```
Expected:
- one or more `creator-anthropic-ai--*.md` source pages
- `creator-anthropic-ai.md` entity page
- `resources-index.md` updated
- `index.md` has new entries under `## Entities` and `## Sources`
- `log.md` has ingestion lines dated today

- [ ] **Step 4: Verify Slack summary**

Open the configured Slack channel. Expected: one top-level message from the bot
with `📼 AI Learnings — daily ingest`, threaded replies for each ingested video
and each failure. Storage line shows `raw/youtube: N MB (M videos · +X today)`.

- [ ] **Step 5: Verify state.json**

Run: `cat state.json | python -m json.tool | head -40`
Expected: `ingested_video_ids` populated; `channels` has a `last_seen_video_id`
for the tested channel; `slack_queue.bot_user_id` filled in.

- [ ] **Step 6: Verify launchd catches the next window**

Run: `launchctl list | grep ytingest`
Expected: shows the job loaded with PID `-` (not currently running) and exit
status `0` from the last manual trigger.

- [ ] **Step 7: Commit the seeded config (only if the watchlist matches your real preferences)**

```bash
git add config.yml
git commit -m "chore: seed watchlist"
```

---

## Self-review notes (plan author)

1. **Spec coverage:** every section in the spec is implemented.
   - §4 Architecture → Tasks 1 (scaffold) + all module tasks
   - §5.1 config.yml → Task 24 (load) + Task 1 (starter file)
   - §5.2 state.json shape → Tasks 2–6
   - §5.3 queue.txt → Task 33
   - §5.4 queue unification → Task 32
   - §6.1 extraction inputs + cache → Tasks 15 + 18
   - §6.2 JSON schema → Task 16
   - §6.3 source page → Task 20
   - §6.4 creator page → Task 21
   - §6.5 resources index → Task 22
   - §6.6 index.md + log.md → Task 23
   - §7.1–7.4 Slack → Tasks 25–27 (read) + 28–31 (write)
   - §8 failure modes → Task 5 (state-side) + Task 36 (run-level)
   - §9 category hygiene → Task 6 (state) + Task 28/36 (surfacing)
   - §10 execution env → Tasks 1 (.env, pyproject) + 37 (launchd) + 39 (README)
   - §12 vault patch → Task 38
2. **Placeholder scan:** no TBD / TODO / "handle edge cases" references. All
   test bodies contain real assertions, all code blocks are executable as-is.
3. **Type consistency:** `ProcessedVideo` / `VideoResult` / `RunSummary` /
   `FetchResult` / `SlackQueueItem` names consistent across test + impl.
   `kebab_slug` used consistently. `extract_video_id` returns `str | None`
   everywhere.
4. **No orphaned symbols:** every helper referenced in a task is defined in
   that task or an earlier one. `_yaml_frontmatter` defined in Task 20, used
   in Tasks 21 + 22. `_atomic_write` defined in Task 23.


