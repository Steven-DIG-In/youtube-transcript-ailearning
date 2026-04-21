from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from src.slack_queue import SlackQueueItem, read_pending_urls


def _msg(ts, user, text):
    return {"ts": ts, "user": user, "text": text, "type": "message"}


def test_read_pending_urls_filters_bot_and_extracts(mocker):
    client = MagicMock()
    client.conversations_history.return_value = {
        "messages": [
            _msg("1745.3", "U_HUMAN",
                 "Watch this https://www.youtube.com/watch?v=aaaaaaaaaaa"),
            _msg("1745.2", "U_BOT",
                 "Daily ingest post — https://www.youtube.com/watch?v=xxxxxxxxxxx"),
            _msg("1745.1", "U_HUMAN",
                 "Vimeo https://vimeo.com/12345"),
        ],
        "has_more": False,
    }
    client.conversations_replies.return_value = {"messages": []}

    items = read_pending_urls(
        client=client,
        channel_id="C1",
        last_message_ts=None,
        bot_user_id="U_BOT",
    )
    urls = [i.url for i in items]
    assert any("aaaaaaaaaaa" in u for u in urls)
    assert not any("xxxxxxxxxxx" in u for u in urls)
    assert not any("vimeo" in u for u in urls)


def test_read_pending_urls_respects_last_ts(mocker):
    client = MagicMock()
    client.conversations_history.return_value = {"messages": [], "has_more": False}
    read_pending_urls(client=client, channel_id="C1",
                     last_message_ts="1745.0", bot_user_id="U_BOT")
    client.conversations_history.assert_called_once()
    kwargs = client.conversations_history.call_args.kwargs
    assert kwargs["channel"] == "C1"
    assert kwargs["oldest"] == "1745.0"


def test_read_pending_urls_returns_empty_on_slack_error(mocker):
    client = MagicMock()
    client.conversations_history.side_effect = SlackApiError(
        "slack err", response={"error": "rate_limited"}
    )
    result = read_pending_urls(
        client=client, channel_id="C1",
        last_message_ts=None, bot_user_id="U_BOT",
    )
    assert result == []


def test_read_pending_urls_descends_into_threads(mocker):
    client = MagicMock()
    parent_with_thread = {**_msg("1745.3", "U_HUMAN", "thread starter no url"),
                          "thread_ts": "1745.3", "reply_count": 1}
    client.conversations_history.return_value = {
        "messages": [parent_with_thread],
        "has_more": False,
    }
    client.conversations_replies.return_value = {
        "messages": [
            parent_with_thread,
            _msg("1745.31", "U_HUMAN",
                 "https://youtu.be/bbbbbbbbbbb"),
        ],
    }
    items = read_pending_urls(
        client=client, channel_id="C1",
        last_message_ts=None, bot_user_id="U_BOT",
    )
    assert any("bbbbbbbbbbb" in i.url for i in items)
