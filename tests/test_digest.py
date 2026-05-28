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
