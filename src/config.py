from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    pass


@dataclass
class WatchlistChannel:
    url: str
    default_categories: list[str] = field(default_factory=list)
    min_duration_seconds: int | None = None


@dataclass
class IngestConfig:
    max_videos_per_run: int
    lookback_days: int
    min_duration_seconds: int


@dataclass
class Config:
    watchlist: list[WatchlistChannel]
    seed_categories: list[str]
    ingest: IngestConfig


def load_config(path: Path) -> Config:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ConfigError("config.yml must be a mapping")
    for key in ("watchlist", "seed_categories", "ingest"):
        if key not in data:
            raise ConfigError(f"config.yml missing key: {key}")
    watchlist_raw = data["watchlist"] or []
    watchlist = [
        WatchlistChannel(
            url=item["url"],
            default_categories=item.get("default_categories") or [],
            min_duration_seconds=item.get("min_duration_seconds"),
        )
        for item in watchlist_raw
    ]
    ingest = IngestConfig(
        max_videos_per_run=int(data["ingest"]["max_videos_per_run"]),
        lookback_days=int(data["ingest"]["lookback_days"]),
        min_duration_seconds=int(data["ingest"]["min_duration_seconds"]),
    )
    return Config(
        watchlist=watchlist,
        seed_categories=list(data["seed_categories"]),
        ingest=ingest,
    )
