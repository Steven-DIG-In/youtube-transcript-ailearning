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


# ---------------------------------------------------------------------------
# Task 33: drain_queue_txt
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Task 34: raw_storage_footprint
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Task 35: process_one_video
# ---------------------------------------------------------------------------
import json
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


# ---------------------------------------------------------------------------
# Task 36: run_once
# ---------------------------------------------------------------------------
from src.main import run_once


def test_run_once_filters_watchlist_videos_below_min_duration(
    mocker, temp_vault, tmp_path
):
    mocker.patch("src.main.self_update_ytdlp")
    mocker.patch(
        "src.main.list_new_videos_for_channel",
        return_value=[
            {
                "id": "aaaaaaaaaaa",
                "title": "Short Clip",
                "duration": 30,
                "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
                "upload_date": "20260420",
            },
        ],
    )
    fetch_video = mocker.patch("src.main.fetch_video")
    process_one_video = mocker.patch("src.main.process_one_video")
    mocker.patch("src.main.Anthropic")
    slack_client = mocker.patch("src.main.WebClient").return_value
    slack_client.auth_test.return_value = {"user_id": "U_BOT"}
    slack_client.chat_postMessage.return_value = {"ts": "1745.5"}
    slack_client.conversations_history.return_value = {
        "messages": [], "has_more": False,
    }

    state_path = tmp_path / "state.json"
    queue_path = tmp_path / "queue.txt"
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        "watchlist:\n"
        "  - url: https://www.youtube.com/@Foo\n"
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

    fetch_video.assert_not_called()
    process_one_video.assert_not_called()
    top_text = slack_client.chat_postMessage.call_args_list[0].kwargs["text"]
    assert "SKIPPED" in top_text
    assert "Short Clip" in top_text
    assert "30" in top_text  # duration reason surfaces the actual seconds


def test_run_once_posts_slack_alert_when_ytdlp_self_update_fails(
    mocker, temp_vault, tmp_path
):
    mocker.patch(
        "src.main.self_update_ytdlp",
        side_effect=RuntimeError("pypi unreachable"),
    )
    mocker.patch("src.main.Anthropic")
    slack_client = mocker.patch("src.main.WebClient").return_value
    slack_client.auth_test.return_value = {"user_id": "U_BOT"}
    slack_client.chat_postMessage.return_value = {"ts": "1745.5"}
    slack_client.conversations_history.return_value = {
        "messages": [], "has_more": False,
    }

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

    posted_texts = [
        c.kwargs.get("text", "")
        for c in slack_client.chat_postMessage.call_args_list
    ]
    alert_texts = [t for t in posted_texts if "🚨" in t]
    assert alert_texts, f"expected a 🚨 alert post, got: {posted_texts}"
    alert = alert_texts[0]
    assert "yt-dlp" in alert.lower()
    assert "pypi unreachable" in alert


def test_run_once_heartbeat_on_empty(mocker, temp_vault, tmp_path):
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

    assert slack_client.chat_postMessage.called
    top_text = slack_client.chat_postMessage.call_args_list[0].kwargs["text"]
    assert "📼" in top_text
    assert "0 new" in top_text


def test_run_once_writes_digest_and_includes_pointer(mocker, temp_vault, tmp_path):
    """run_once should call write_digest at the end and pass digest_pointer into the Slack summary."""
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
        "seed_categories: []\n"
        "ingest:\n"
        "  max_videos_per_run: 10\n"
        "  lookback_days: 14\n"
        "  min_duration_seconds: 60\n"
        "digest:\n"
        "  window_days: 7\n"
        "  vault_app_base_url: http://localhost:3000\n"
        "  vault_name: \"AI Learnings\"\n"
    )

    run_once(
        config_path=config_path, state_path=state_path, queue_path=queue_path,
        vault=temp_vault, slack_channel_id="C1", anthropic_api_key="x",
        slack_bot_token="y", today="2026-05-28", now_iso="2026-05-28T10:30:00Z",
    )

    # digest.html should exist at the vault root.
    assert (temp_vault / "digest.html").exists()
    text = (temp_vault / "digest.html").read_text()
    assert "AI Learnings — Last 7 Days" in text

    # Slack summary should contain the digest pointer line.
    top_text = slack_client.chat_postMessage.call_args_list[0].kwargs["text"]
    assert "Weekly digest refreshed" in top_text


def test_run_once_digest_failure_does_not_break_slack_post(mocker, temp_vault, tmp_path):
    """If write_digest raises, run_once should still post the Slack summary with a ⚠ pointer line."""
    mocker.patch("src.main.self_update_ytdlp")
    slack_client = mocker.patch("src.main.WebClient").return_value
    slack_client.auth_test.return_value = {"user_id": "U_BOT"}
    slack_client.chat_postMessage.return_value = {"ts": "1745.5"}
    slack_client.conversations_history.return_value = {"messages": [], "has_more": False}
    mocker.patch("src.main.Anthropic")
    mocker.patch("src.main.write_digest", side_effect=RuntimeError("simulated digest failure"))

    state_path = tmp_path / "state.json"
    queue_path = tmp_path / "queue.txt"
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        "watchlist: []\n"
        "seed_categories: []\n"
        "ingest:\n"
        "  max_videos_per_run: 10\n"
        "  lookback_days: 14\n"
        "  min_duration_seconds: 60\n"
    )

    run_once(
        config_path=config_path, state_path=state_path, queue_path=queue_path,
        vault=temp_vault, slack_channel_id="C1", anthropic_api_key="x",
        slack_bot_token="y", today="2026-05-28", now_iso="2026-05-28T10:30:00Z",
    )

    # Slack summary still posted.
    assert slack_client.chat_postMessage.called
    top_text = slack_client.chat_postMessage.call_args_list[0].kwargs["text"]
    assert "⚠ Digest generation failed" in top_text
    # State file still saved.
    assert state_path.exists()
