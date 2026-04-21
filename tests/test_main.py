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
