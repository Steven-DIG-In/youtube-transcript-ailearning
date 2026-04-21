import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from src.notify import (
    RunSummary,
    VideoResult,
    compose_failure_reply,
    compose_top_level,
    compose_video_reply,
    deliver_undelivered_summaries,
    post_run_summary,
)


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
