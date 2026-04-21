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
