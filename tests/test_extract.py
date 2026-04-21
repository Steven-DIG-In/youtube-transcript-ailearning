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


# ---------------------------------------------------------------------------
# Task 16: parse_extraction_response
# ---------------------------------------------------------------------------
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
