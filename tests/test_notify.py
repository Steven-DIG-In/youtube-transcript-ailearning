from src.notify import RunSummary, VideoResult, compose_top_level


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
