from __future__ import annotations

import json
import os
import tempfile
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


def save_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".tmp.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def is_ingested(state: dict[str, Any], video_id: str) -> bool:
    return video_id in state["ingested_video_ids"]


def mark_ingested(
    state: dict[str, Any],
    *,
    video_id: str,
    source_page: str,
    creator_slug: str,
    ingested_at: str,
) -> None:
    state["ingested_video_ids"][video_id] = {
        "ingested_at": ingested_at,
        "source_page": source_page,
        "creator_slug": creator_slug,
    }
