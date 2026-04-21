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
