from __future__ import annotations

import logging
from dataclasses import dataclass

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.fetch import extract_youtube_urls_from_text

logger = logging.getLogger(__name__)


@dataclass
class SlackQueueItem:
    url: str
    message_ts: str
    channel_id: str


def read_pending_urls(
    *,
    client: WebClient,
    channel_id: str,
    last_message_ts: str | None,
    bot_user_id: str | None,
) -> list[SlackQueueItem]:
    try:
        history = client.conversations_history(
            channel=channel_id,
            oldest=last_message_ts or "0",
            inclusive=False,
            limit=200,
        )
    except SlackApiError as exc:
        logger.warning("slack conversations_history failed: %s", exc)
        return []

    items: list[SlackQueueItem] = []
    for msg in history.get("messages", []):
        if msg.get("user") == bot_user_id:
            continue
        _collect_urls(msg, channel_id, items)
        if msg.get("thread_ts") and int(msg.get("reply_count", 0)) > 0:
            try:
                replies = client.conversations_replies(
                    channel=channel_id, ts=msg["thread_ts"]
                )
                for reply in replies.get("messages", []):
                    # Slack returns the thread parent as the first reply;
                    # skip it so we don't double-process its URLs.
                    if reply.get("ts") == msg["thread_ts"]:
                        continue
                    if reply.get("user") == bot_user_id:
                        continue
                    _collect_urls(reply, channel_id, items)
            except SlackApiError as exc:
                logger.warning("slack conversations_replies failed: %s", exc)
    return items


def _collect_urls(msg: dict, channel_id: str, out: list[SlackQueueItem]) -> None:
    for url in extract_youtube_urls_from_text(msg.get("text", "") or ""):
        out.append(SlackQueueItem(url=url, message_ts=msg["ts"], channel_id=channel_id))


def mark_processed(*, client: WebClient, channel_id: str, message_ts: str) -> None:
    try:
        client.reactions_add(channel=channel_id, timestamp=message_ts, name="vhs")
    except SlackApiError as exc:
        if exc.response.get("error") == "already_reacted":
            return
        raise


def resolve_bot_user_id(client: WebClient, state: dict) -> str:
    cached = state["slack_queue"].get("bot_user_id")
    if cached:
        return cached
    resp = client.auth_test()
    state["slack_queue"]["bot_user_id"] = resp["user_id"]
    return resp["user_id"]
