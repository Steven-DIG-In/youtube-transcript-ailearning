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
