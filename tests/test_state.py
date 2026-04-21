from pathlib import Path

from src.state import DEFAULT_STATE, load_state, save_state, is_ingested, mark_ingested, record_failure, DEAD_THRESHOLD, record_proposed_category, CATEGORY_AUTOPROMOTE_THRESHOLD


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


def test_is_ingested_false_when_absent():
    state = {"ingested_video_ids": {}}
    assert is_ingested(state, "abc12345678") is False


def test_mark_ingested_then_is_ingested_true():
    state = {"ingested_video_ids": {}}
    mark_ingested(
        state,
        video_id="abc12345678",
        source_page="wiki/sources/creator-foo--video-bar.md",
        creator_slug="creator-foo",
        ingested_at="2026-04-21T09:00:00Z",
    )
    assert is_ingested(state, "abc12345678") is True
    assert state["ingested_video_ids"]["abc12345678"]["source_page"].endswith("video-bar.md")
    assert state["ingested_video_ids"]["abc12345678"]["creator_slug"] == "creator-foo"


def test_record_failure_increments_attempts():
    state = {"failed_videos": {}, "dead_videos": {}}
    record_failure(state, video_id="v1", reason="no captions", now="2026-04-21T09:00:00Z")
    record_failure(state, video_id="v1", reason="no captions", now="2026-04-22T09:00:00Z")
    assert state["failed_videos"]["v1"]["attempts"] == 2
    assert state["failed_videos"]["v1"]["reason"] == "no captions"
    assert state["failed_videos"]["v1"]["last_tried"] == "2026-04-22T09:00:00Z"
    assert "v1" not in state["dead_videos"]


def test_record_failure_moves_to_dead_after_threshold():
    state = {"failed_videos": {}, "dead_videos": {}}
    for i in range(DEAD_THRESHOLD):
        record_failure(state, video_id="v1", reason="no captions", now=f"2026-04-2{i+1}T09:00:00Z")
    assert "v1" not in state["failed_videos"]
    assert "v1" in state["dead_videos"]
    assert state["dead_videos"]["v1"]["reason"] == "no captions"


def test_proposed_category_first_sighting_is_pending():
    state = {"proposed_categories": {}}
    record_proposed_category(
        state,
        slug="agent-orchestration",
        video_id="v1",
        now="2026-04-21T09:00:00Z",
    )
    entry = state["proposed_categories"]["agent-orchestration"]
    assert entry["sightings"] == 1
    assert entry["status"] == "pending"
    assert entry["videos"] == ["v1"]
    assert entry["first_seen"] == "2026-04-21T09:00:00Z"


def test_proposed_category_autopromotes_at_threshold():
    state = {"proposed_categories": {}}
    for i in range(CATEGORY_AUTOPROMOTE_THRESHOLD):
        record_proposed_category(
            state,
            slug="agent-orchestration",
            video_id=f"v{i}",
            now=f"2026-04-2{i+1}T09:00:00Z",
        )
    assert state["proposed_categories"]["agent-orchestration"]["status"] == "auto-promoted"
    assert state["proposed_categories"]["agent-orchestration"]["sightings"] == CATEGORY_AUTOPROMOTE_THRESHOLD


def test_proposed_category_dedup_videos():
    state = {"proposed_categories": {}}
    record_proposed_category(state, slug="x", video_id="v1", now="2026-04-21T09:00:00Z")
    record_proposed_category(state, slug="x", video_id="v1", now="2026-04-22T09:00:00Z")
    assert state["proposed_categories"]["x"]["videos"] == ["v1"]
    assert state["proposed_categories"]["x"]["sightings"] == 1
