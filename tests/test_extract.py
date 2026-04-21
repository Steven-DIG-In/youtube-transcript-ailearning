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
