from pathlib import Path

from src.state import DEFAULT_STATE, load_state, save_state


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
    initial = {"ingested_video_ids": {"v1": {}}, "channels": {}, "failed_videos": {},
               "dead_videos": {}, "proposed_categories": {},
               "slack_queue": {"last_message_ts": None, "bot_user_id": None},
               "undelivered_summaries": []}
    save_state(temp_state_path, initial)
    leftover_tmp = [p for p in tmp_path.iterdir() if p.name.startswith("state.json.tmp")]
    assert leftover_tmp == []
    assert load_state(temp_state_path) == initial
