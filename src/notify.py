from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


@dataclass
class VideoResult:
    title: str
    creator: str
    categories: list[str]
    source_page: str
    key_takeaways: list[str]
    resources_count: int
    proposed_new_category_slugs: list[str] = field(default_factory=list)


@dataclass
class RunSummary:
    run_date: str
    ingested: list[VideoResult]
    skipped: list[dict]
    failed: list[dict]
    storage_bytes: int
    storage_video_count: int
    storage_added_today: int
    proposed_categories_pending: list[str]
    autopromoted_categories: list[str]
    dead_today: list[dict]
    digest_pointer: str | None = None


def _mb(value: int) -> str:
    return f"{value / (1024 * 1024):.0f} MB"


def compose_top_level(summary: RunSummary) -> str:
    lines = [f"📼 AI Learnings — daily ingest · {summary.run_date}"]
    lines.append(
        f"Ingested {len(summary.ingested)} new · "
        f"skipped {len(summary.skipped)} · "
        f"failed {len(summary.failed)}"
    )
    if not summary.ingested and not summary.skipped and not summary.failed:
        lines.append("")
        lines.append("_Watchlist idle — nothing new today._")
    if summary.ingested:
        lines.append("")
        lines.append("NEW")
        for v in summary.ingested:
            cats = ", ".join(v.categories) or "—"
            extra = ""
            if v.proposed_new_category_slugs:
                extra = (
                    " ⚠️ proposed new category: "
                    + ", ".join(v.proposed_new_category_slugs)
                )
            lines.append(f"• \"{v.title}\" — {v.creator} — {cats}{extra}")
    if summary.skipped:
        lines.append("")
        lines.append("SKIPPED")
        for s in summary.skipped:
            lines.append(f"• \"{s['title']}\" — {s['reason']}")
    lines.append("")
    lines.append("STORAGE")
    lines.append(
        f"raw/youtube: {_mb(summary.storage_bytes)} "
        f"({summary.storage_video_count} videos · +{summary.storage_added_today} today)"
    )
    if summary.proposed_categories_pending or summary.autopromoted_categories:
        lines.append("")
        lines.append("REVIEW QUEUE")
        if summary.proposed_categories_pending:
            lines.append(
                f"• {len(summary.proposed_categories_pending)} proposed "
                f"categories awaiting rename/merge: "
                + ", ".join(summary.proposed_categories_pending)
            )
        for slug in summary.autopromoted_categories:
            lines.append(
                f"• ℹ️ `{slug}` auto-promoted to seed list after 3 uses — "
                "edit config.yml to rename/merge if desired"
            )
    if summary.digest_pointer:
        lines.append("")
        lines.append(summary.digest_pointer)
    return "\n".join(lines)


def compose_video_reply(video: VideoResult) -> str:
    cats = ", ".join(video.categories) or "—"
    lines = [
        f"\"{video.title}\" — {video.creator}",
        f"📂 {video.source_page}",
        f"📝 {len(video.key_takeaways)} takeaways · "
        f"🔗 {video.resources_count} resources · 🏷 {cats}",
    ]
    for t in video.key_takeaways:
        lines.append(f"Takeaway: {t}")
    return "\n".join(lines)


def compose_failure_reply(failure: dict) -> str:
    next_line = (
        "moved to dead" if failure["moved_dead"]
        else f"retry {failure['attempt']} of 3"
    )
    return (
        f"❌ \"{failure['title']}\" — {failure['video_id']}\n"
        f"Reason: {failure['reason']}\n"
        f"Next: {next_line}"
    )


def post_run_summary(
    *,
    client: WebClient,
    channel_id: str,
    summary: RunSummary,
) -> tuple[bool, dict]:
    parent_ts: str | None = None
    try:
        top = client.chat_postMessage(
            channel=channel_id, text=compose_top_level(summary)
        )
        parent_ts = top["ts"]
    except SlackApiError as exc:
        logger.warning("slack top-level post failed: %s", exc)
        return False, {"error": str(exc)}

    # Top-level succeeded; threaded replies are best-effort. A failure here
    # should not trigger a catch-up retry of the whole summary (which would
    # duplicate the top-level message), so we surface partial success to the
    # caller via the result tuple.
    thread_errors: list[str] = []
    for v in summary.ingested:
        try:
            client.chat_postMessage(
                channel=channel_id, thread_ts=parent_ts,
                text=compose_video_reply(v),
            )
        except SlackApiError as exc:
            logger.warning("slack thread reply failed for %s: %s", v.title, exc)
            thread_errors.append(str(exc))
    for f in summary.failed:
        try:
            client.chat_postMessage(
                channel=channel_id, thread_ts=parent_ts,
                text=compose_failure_reply(f),
            )
        except SlackApiError as exc:
            logger.warning("slack failure reply failed for %s: %s", f.get("video_id"), exc)
            thread_errors.append(str(exc))

    result: dict = {"top_ts": parent_ts}
    if thread_errors:
        result["thread_errors"] = thread_errors
    return True, result


def _safe_video_result(v: dict) -> VideoResult | None:
    try:
        return VideoResult(**v)
    except TypeError as exc:
        logger.warning("skipping undelivered video with incompatible schema: %s", exc)
        return None


def _summary_from_log(log: dict) -> RunSummary:
    ingested = [
        vr for vr in (_safe_video_result(v) for v in log.get("ingested", []))
        if vr is not None
    ]
    return RunSummary(
        run_date=log["run_date"],
        ingested=ingested,
        skipped=log.get("skipped", []),
        failed=log.get("failed", []),
        storage_bytes=log.get("storage_bytes", 0),
        storage_video_count=log.get("storage_video_count", 0),
        storage_added_today=log.get("storage_added_today", 0),
        proposed_categories_pending=log.get("proposed_categories_pending", []),
        autopromoted_categories=log.get("autopromoted_categories", []),
        dead_today=log.get("dead_today", []),
        digest_pointer=log.get("digest_pointer"),
    )


def deliver_undelivered_summaries(
    *,
    client: WebClient,
    channel_id: str,
    state: dict,
) -> None:
    pending = list(state.get("undelivered_summaries", []))
    remaining: list[dict] = []
    for entry in pending:
        try:
            data = json.loads(Path(entry["log_path"]).read_text())
        except FileNotFoundError as exc:
            logger.warning("undelivered log %s missing, retaining for retry: %s", entry, exc)
            remaining.append(entry)
            continue
        except json.JSONDecodeError as exc:
            logger.warning("undelivered log %s corrupt, dropping: %s", entry, exc)
            continue
        summary = _summary_from_log(data)
        prefixed = RunSummary(
            run_date=f"⚠ delayed from {summary.run_date}",
            ingested=summary.ingested, skipped=summary.skipped, failed=summary.failed,
            storage_bytes=summary.storage_bytes,
            storage_video_count=summary.storage_video_count,
            storage_added_today=summary.storage_added_today,
            proposed_categories_pending=summary.proposed_categories_pending,
            autopromoted_categories=summary.autopromoted_categories,
            dead_today=summary.dead_today,
        )
        ok, _ = post_run_summary(client=client, channel_id=channel_id, summary=prefixed)
        if not ok:
            remaining.append(entry)
    state["undelivered_summaries"] = remaining
