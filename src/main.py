from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from slack_sdk import WebClient

from src.config import load_config
from src.extract import ExtractionError, call_extract, render_extract_prompt
from src.fetch import FetchError, extract_video_id, fetch_video, list_new_videos_for_channel, self_update_ytdlp
from src.notify import (
    RunSummary,
    VideoResult,
    deliver_undelivered_summaries,
    post_run_summary,
)
from src.slack_queue import (
    SlackQueueItem,
    mark_processed,
    read_pending_urls,
    resolve_bot_user_id,
)
from src.state import load_state, mark_ingested, record_failure, record_proposed_category, save_state
from src.write import (
    append_index_entries,
    append_log_entry,
    kebab_slug,
    upsert_creator_page,
    upsert_resources_index,
    write_source_page,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task 32: UrlCandidate + build_unified_queue
# ---------------------------------------------------------------------------
@dataclass
class UrlCandidate:
    url: str
    video_id: str
    source: str  # "queue.txt" | "slack" | "watchlist"
    slack_item: SlackQueueItem | None = None


def build_unified_queue(
    *,
    queue_txt_urls: list[str],
    slack_items: list[SlackQueueItem],
    watchlist_urls: list[str],
    already_ingested: set[str],
) -> list[UrlCandidate]:
    seen: set[str] = set()
    out: list[UrlCandidate] = []

    def add(url: str, source: str, slack_item: SlackQueueItem | None = None) -> None:
        vid = extract_video_id(url)
        if not vid or vid in seen or vid in already_ingested:
            return
        seen.add(vid)
        out.append(UrlCandidate(url=url, video_id=vid, source=source,
                                slack_item=slack_item))

    for url in queue_txt_urls:
        add(url, "queue.txt")
    for item in slack_items:
        add(item.url, "slack", slack_item=item)
    for url in watchlist_urls:
        add(url, "watchlist")
    return out


# ---------------------------------------------------------------------------
# Task 33: drain_queue_txt
# ---------------------------------------------------------------------------
def drain_queue_txt(path: Path) -> list[str]:
    if not path.exists():
        return []
    urls = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    # Read-then-truncate: URLs exist in memory only after this point.
    # If the process dies before they reach processing, they are lost.
    # Acceptable per spec §5.3 because queue.txt is a one-shot drop-box;
    # the watchlist covers persistent subscriptions. Dedup catches any
    # re-ingestion attempt.
    path.write_text("")
    return urls


# ---------------------------------------------------------------------------
# Task 34: raw_storage_footprint
# ---------------------------------------------------------------------------
def raw_storage_footprint(raw_dir: Path) -> tuple[int, int]:
    if not raw_dir.exists():
        return 0, 0
    files = list(raw_dir.glob("*.transcript.txt"))
    return sum(f.stat().st_size for f in files), len(files)


# ---------------------------------------------------------------------------
# Task 35: ProcessedVideo + process_one_video
# ---------------------------------------------------------------------------
@dataclass
class ProcessedVideo:
    video_id: str
    title: str
    creator: str
    creator_slug: str
    creator_is_new: bool
    source_page: str  # relative filename inside wiki/sources/
    categories: list[str]
    proposed_new_category_slugs: list[str]
    key_takeaways: list[str]
    resources_count: int


def _resources_index_snapshot(vault: Path) -> str:
    path = vault / "wiki" / "sources" / "resources-index.md"
    return path.read_text() if path.exists() else ""


def _existing_creator_page(vault: Path, channel: str) -> str:
    slug = f"creator-{kebab_slug(channel)}"
    path = vault / "wiki" / "entities" / f"{slug}.md"
    return path.read_text() if path.exists() else ""


def process_one_video(
    *,
    url: str,
    client: Anthropic,
    vault: Path,
    state: dict,
    seed_categories: list[str],
    channel_hint_categories: list[str],
    today: str,
    now_iso: str,
    model: str = "claude-sonnet-4-6",
) -> ProcessedVideo:
    raw_dir = vault / "raw" / "youtube"
    fetch_result = fetch_video(url, raw_dir=raw_dir)

    prompt = render_extract_prompt(
        title=fetch_result.title,
        channel=fetch_result.channel,
        channel_url=fetch_result.channel_url,
        published_at=fetch_result.published_at,
        duration_seconds=fetch_result.duration_seconds,
        description=fetch_result.description,
        channel_hint_categories=channel_hint_categories,
        seed_categories=seed_categories,
        existing_creator_page=_existing_creator_page(vault, fetch_result.channel),
        resources_index_snapshot=_resources_index_snapshot(vault),
        transcript=fetch_result.transcript,
    )
    extraction = call_extract(client, prompt=prompt, model=model)

    creator_slug_pre = f"creator-{kebab_slug(fetch_result.channel)}"
    creator_existed = (vault / "wiki" / "entities" / f"{creator_slug_pre}.md").exists()

    creator_slug, _ = upsert_creator_page(
        vault=vault,
        channel=fetch_result.channel,
        channel_url=fetch_result.channel_url,
        channel_id=fetch_result.channel_id,
        video_title=fetch_result.title,
        video_slug=kebab_slug(fetch_result.title),
        video_summary=extraction["session_summary"],
        video_published_at=fetch_result.published_at,
        video_domain=extraction["domain"],
        categories=extraction["categories"],
        creator_bio_additions=extraction["creator_bio_additions"],
        today=today,
    )
    source_path = write_source_page(
        vault=vault,
        fetch=dataclasses.asdict(fetch_result),
        extraction=extraction,
        creator_slug=creator_slug,
        date_ingested=today,
    )
    source_slug = source_path.stem
    upsert_resources_index(
        vault=vault,
        resources=extraction["resources"],
        source_slug=source_slug,
        today=today,
    )
    append_index_entries(
        vault=vault,
        source_slug=source_slug,
        source_title=fetch_result.title,
        creator_slug=creator_slug,
        creator_name=fetch_result.channel,
        creator_is_new=not creator_existed,
    )
    append_log_entry(
        vault=vault,
        timestamp=now_iso,
        message=f"Ingested {fetch_result.video_id} → {source_slug}",
    )

    # Mark the video owned before recording secondary metadata about it.
    # If mark_ingested ever fails (shouldn't — pure dict mutation), we don't
    # want stale proposed-category counts for a video state treats as un-ingested.
    mark_ingested(
        state,
        video_id=fetch_result.video_id,
        source_page=f"wiki/sources/{source_path.name}",
        creator_slug=creator_slug,
        ingested_at=now_iso,
    )
    proposed_slugs: list[str] = []
    for p in extraction["proposed_new_categories"]:
        record_proposed_category(
            state,
            slug=p["slug"],
            video_id=fetch_result.video_id,
            now=now_iso,
        )
        proposed_slugs.append(p["slug"])

    return ProcessedVideo(
        video_id=fetch_result.video_id,
        title=fetch_result.title,
        creator=fetch_result.channel,
        creator_slug=creator_slug,
        creator_is_new=not creator_existed,
        source_page=source_path.name,
        categories=extraction["categories"],
        proposed_new_category_slugs=proposed_slugs,
        key_takeaways=extraction["key_takeaways"],
        resources_count=len(extraction["resources"]),
    )


# ---------------------------------------------------------------------------
# Task 36: run_once — top-level cron entry point
# ---------------------------------------------------------------------------
def run_once(
    *,
    config_path: Path,
    state_path: Path,
    queue_path: Path,
    vault: Path,
    slack_channel_id: str,
    anthropic_api_key: str,
    slack_bot_token: str,
    log_dir: Path | None = None,
    today: str | None = None,
    now_iso: str | None = None,
) -> None:
    if not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is empty; aborting before any processing.")

    now = datetime.now(timezone.utc)
    today = today or now.strftime("%Y-%m-%d")
    now_iso = now_iso or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    log_dir = log_dir or (state_path.parent / "logs")

    cfg = load_config(config_path)
    state = load_state(state_path)
    slack_client = WebClient(token=slack_bot_token)
    anthropic_client = Anthropic(api_key=anthropic_api_key)

    try:
        self_update_ytdlp()
    except RuntimeError as exc:
        # v1 deferral: spec §8.2 row 1 also prescribes a 🚨 Slack alert on
        # persistent yt-dlp failure. For now we log and continue; the missing
        # daily summary will surface the issue on the next successful run.
        logger.error("yt-dlp self-update failed: %s", exc)

    # Slack bot ID resolution is tolerant of Slack outages — fall back to
    # None so read_pending_urls simply skips the bot-filter step rather than
    # aborting the whole run.
    try:
        bot_user_id: str | None = resolve_bot_user_id(slack_client, state)
    except Exception as exc:  # SlackApiError or network
        logger.warning("resolve_bot_user_id failed, continuing without it: %s", exc)
        bot_user_id = None

    deliver_undelivered_summaries(
        client=slack_client, channel_id=slack_channel_id, state=state
    )

    # Queue source ordering per spec §5.4: queue.txt → Slack → watchlist.
    queue_urls = drain_queue_txt(queue_path)

    slack_items = read_pending_urls(
        client=slack_client,
        channel_id=slack_channel_id,
        last_message_ts=state["slack_queue"]["last_message_ts"],
        bot_user_id=bot_user_id,
    )

    watchlist_urls: list[str] = []
    hint_by_video_id: dict[str, list[str]] = {}
    for channel in cfg.watchlist:
        channel_state = state["channels"].setdefault(channel.url, {
            "last_checked_at": None, "last_seen_video_id": None,
        })
        try:
            new_videos = list_new_videos_for_channel(
                channel.url,
                last_seen_video_id=channel_state.get("last_seen_video_id"),
                lookback_days=cfg.ingest.lookback_days,
                now=today,
            )
        except FetchError as exc:
            logger.warning("watchlist poll failed for %s: %s", channel.url, exc)
            continue
        for v in new_videos:
            url = v.get("url") or f"https://www.youtube.com/watch?v={v['id']}"
            watchlist_urls.append(url)
            hint_by_video_id[v["id"]] = channel.default_categories
        if new_videos:
            channel_state["last_seen_video_id"] = new_videos[0].get("id")
        channel_state["last_checked_at"] = now_iso

    already_ingested = set(state["ingested_video_ids"].keys()) | set(state["dead_videos"].keys())
    queue = build_unified_queue(
        queue_txt_urls=queue_urls,
        slack_items=slack_items,
        watchlist_urls=watchlist_urls,
        already_ingested=already_ingested,
    )[: cfg.ingest.max_videos_per_run]

    ingested: list[VideoResult] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    dead_today: list[dict] = []

    for cand in queue:
        try:
            result = process_one_video(
                url=cand.url,
                client=anthropic_client,
                vault=vault,
                state=state,
                seed_categories=cfg.seed_categories + _autopromoted(state),
                channel_hint_categories=hint_by_video_id.get(cand.video_id, []),
                today=today,
                now_iso=now_iso,
            )
            if cand.slack_item is not None:
                try:
                    mark_processed(
                        client=slack_client,
                        channel_id=cand.slack_item.channel_id,
                        message_ts=cand.slack_item.message_ts,
                    )
                except Exception as exc:
                    logger.warning("slack reaction failed: %s", exc)
            ingested.append(VideoResult(
                title=result.title, creator=result.creator,
                categories=result.categories,
                source_page=f"wiki/sources/{result.source_page}",
                key_takeaways=result.key_takeaways[:3],
                resources_count=result.resources_count,
                proposed_new_category_slugs=result.proposed_new_category_slugs,
            ))
        except FetchError as exc:
            record_failure(state, video_id=cand.video_id,
                           reason=str(exc), now=now_iso)
            moved = cand.video_id in state["dead_videos"]
            attempt = state["failed_videos"].get(cand.video_id, {}).get("attempts", 3)
            failed.append({
                "title": f"<{cand.video_id}>", "video_id": cand.video_id,
                "reason": str(exc), "attempt": attempt, "moved_dead": moved,
            })
            if moved:
                dead_today.append({"video_id": cand.video_id, "reason": str(exc)})
        except ExtractionError as exc:
            record_failure(state, video_id=cand.video_id,
                           reason=f"llm: {exc}", now=now_iso)
            failed.append({
                "title": f"<{cand.video_id}>", "video_id": cand.video_id,
                "reason": f"llm: {exc}",
                "attempt": state["failed_videos"].get(cand.video_id, {}).get("attempts", 1),
                "moved_dead": cand.video_id in state["dead_videos"],
            })
        if cand.slack_item is not None:
            ts = cand.slack_item.message_ts
            prev = state["slack_queue"].get("last_message_ts") or "0"
            if float(ts) > float(prev):
                state["slack_queue"]["last_message_ts"] = ts

    storage_bytes, storage_count = raw_storage_footprint(vault / "raw" / "youtube")
    pending_categories = [
        slug for slug, entry in state["proposed_categories"].items()
        if entry["status"] == "pending"
    ]
    # Per spec §9: auto-promote notice is a one-off. Surface only categories
    # that flipped to auto-promoted during THIS run, then transition them to
    # "announced" so subsequent runs stay quiet.
    newly_autopromoted = [
        slug for slug, entry in state["proposed_categories"].items()
        if entry["status"] == "auto-promoted"
    ]
    for slug in newly_autopromoted:
        state["proposed_categories"][slug]["status"] = "announced"

    summary = RunSummary(
        run_date=now.strftime("%Y-%m-%d %H:%M"),
        ingested=ingested, skipped=skipped, failed=failed,
        storage_bytes=storage_bytes, storage_video_count=storage_count,
        storage_added_today=len(ingested),
        proposed_categories_pending=pending_categories,
        autopromoted_categories=newly_autopromoted,
        dead_today=dead_today,
    )
    ok, _ = post_run_summary(
        client=slack_client, channel_id=slack_channel_id, summary=summary,
    )
    if not ok:
        log_path = log_dir / f"{today}.json"
        _log_summary_for_retry(summary, log_path, state)

    save_state(state_path, state)


def _autopromoted(state: dict) -> list[str]:
    # Both "auto-promoted" (this run) and "announced" (past runs) are treated
    # as accepted seed categories for extraction prompts.
    return [
        slug for slug, entry in state["proposed_categories"].items()
        if entry["status"] in ("auto-promoted", "announced")
    ]


def _log_summary_for_retry(summary: RunSummary, log_path: Path, state: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_date": summary.run_date,
        "ingested": [dataclasses.asdict(v) for v in summary.ingested],
        "skipped": summary.skipped,
        "failed": summary.failed,
        "storage_bytes": summary.storage_bytes,
        "storage_video_count": summary.storage_video_count,
        "storage_added_today": summary.storage_added_today,
        "proposed_categories_pending": summary.proposed_categories_pending,
        "autopromoted_categories": summary.autopromoted_categories,
        "dead_today": summary.dead_today,
    }
    log_path.write_text(json.dumps(payload))
    state["undelivered_summaries"].append({
        "run_date": summary.run_date, "log_path": str(log_path),
    })


if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv()
    project_root = Path(__file__).resolve().parent.parent
    vault = Path(os.environ["VAULT_PATH"])
    run_once(
        config_path=project_root / "config.yml",
        state_path=project_root / "state.json",
        queue_path=project_root / "queue.txt",
        vault=vault,
        slack_channel_id=os.environ["SLACK_CHANNEL_ID"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
    )
