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


# ---------------------------------------------------------------------------
# Task 20: write_source_page
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Task 21: upsert_creator_page
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Task 22: upsert_resources_index
# ---------------------------------------------------------------------------
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
    assert text.count("https://docs.anthropic.com") == 1
    assert "[[creator-x--second]]" in text
    assert "## Tools" in text
    assert "yt-dlp" in text
    assert "entry_count: 2" in text


# ---------------------------------------------------------------------------
# Task 23: append_index_entries, append_log_entry
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Review-fix coverage
# ---------------------------------------------------------------------------


def test_resources_index_survives_em_dash_in_content(temp_vault):
    upsert_resources_index(
        vault=temp_vault,
        resources=[
            {"url": "https://example.com", "title": "Title — with em-dash",
             "description": "desc also — with em-dash", "group": "Tools"},
        ],
        source_slug="creator-x--v1",
        today="2026-04-21",
    )
    upsert_resources_index(
        vault=temp_vault,
        resources=[
            {"url": "https://example.com", "title": "Title — with em-dash",
             "description": "desc also — with em-dash", "group": "Tools"},
        ],
        source_slug="creator-x--v2",
        today="2026-04-22",
    )
    text = (temp_vault / "wiki" / "sources" / "resources-index.md").read_text()
    assert text.count("https://example.com") == 1
    assert "[[creator-x--v1]]" in text
    assert "[[creator-x--v2]]" in text
    assert "Title — with em-dash" in text
    assert "entry_count: 1" in text


def test_resources_index_coerces_unknown_group_to_uncategorised(temp_vault):
    upsert_resources_index(
        vault=temp_vault,
        resources=[
            {"url": "https://example.com", "title": "Weird",
             "description": "d", "group": "SomeUnknownGroup"},
        ],
        source_slug="creator-x--v1",
        today="2026-04-21",
    )
    text = (temp_vault / "wiki" / "sources" / "resources-index.md").read_text()
    assert "## Uncategorised" in text
    assert "SomeUnknownGroup" not in text
    assert "entry_count: 1" in text


def test_upsert_creator_page_clears_placeholder_on_first_bio_addition(temp_vault):
    first = _creator_inputs(vault=temp_vault)
    upsert_creator_page(**first)
    placeholder = "_First sighting — bio to be appended"
    assert placeholder in (
        temp_vault / "wiki" / "entities" / "creator-anthropic.md"
    ).read_text()

    second = _creator_inputs(
        vault=temp_vault,
        video_title="Second",
        video_slug="second",
        creator_bio_additions="Joined the DevRel team in April 2026.",
        today="2026-04-22",
    )
    _, path = upsert_creator_page(**second)
    text = path.read_text()
    assert placeholder not in text
    assert "Joined the DevRel team in April 2026." in text
    assert "2026-04-22" in text
