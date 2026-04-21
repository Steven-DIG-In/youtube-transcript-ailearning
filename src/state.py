from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_STATE: dict[str, Any] = {
    "ingested_video_ids": {},
    "channels": {},
    "failed_videos": {},
    "dead_videos": {},
    "proposed_categories": {},
    "slack_queue": {"last_message_ts": None, "bot_user_id": None},
    "undelivered_summaries": [],
}


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(DEFAULT_STATE)
    return json.loads(path.read_text())
