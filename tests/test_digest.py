from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.digest import IngestRef, SourcePage, select_recent_ingests, parse_source_page, detect_steps, tools_for_sources, top_tools
from src.write import write_source_page, upsert_resources_index


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
