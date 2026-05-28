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
class DigestConfig:
    window_days: int = 7
    vault_app_base_url: str = "http://localhost:3000"
    vault_name: str = "AI Learnings"


@dataclass
class Config:
    watchlist: list[WatchlistChannel]
    seed_categories: list[str]
    ingest: IngestConfig
    digest: DigestConfig = field(default_factory=DigestConfig)


def _int_field(data: dict, *keys: str) -> int:
    obj: object = data
    for k in keys:
        obj = obj[k]
    try:
        return int(obj)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"config.yml field {'.'.join(keys)!r} must be an integer, got {obj!r}"
        ) from exc


def load_config(path: Path) -> Config:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ConfigError("config.yml must be a mapping")
    for key in ("watchlist", "seed_categories", "ingest"):
        if key not in data:
            raise ConfigError(f"config.yml missing key: {key}")

    watchlist_raw = data["watchlist"] or []
    if not isinstance(watchlist_raw, list):
        raise ConfigError("config.yml 'watchlist' must be a list")
    watchlist = [
        WatchlistChannel(
            url=item["url"],
            default_categories=item.get("default_categories") or [],
            min_duration_seconds=item.get("min_duration_seconds"),
        )
        for item in watchlist_raw
    ]

    if not isinstance(data["seed_categories"], list):
        raise ConfigError("config.yml 'seed_categories' must be a list")
    seed_categories = list(data["seed_categories"])
    duplicates = sorted({c for c in seed_categories if seed_categories.count(c) > 1})
    if duplicates:
        raise ConfigError(
            f"config.yml 'seed_categories' contains duplicates: {duplicates}"
        )

    ingest_raw = data["ingest"]
    if not isinstance(ingest_raw, dict):
        raise ConfigError("config.yml 'ingest' must be a mapping")
    ingest = IngestConfig(
        max_videos_per_run=_int_field(data, "ingest", "max_videos_per_run"),
        lookback_days=_int_field(data, "ingest", "lookback_days"),
        min_duration_seconds=_int_field(data, "ingest", "min_duration_seconds"),
    )

    digest_raw = data.get("digest") or {}
    if not isinstance(digest_raw, dict):
        raise ConfigError("config.yml 'digest' must be a mapping")
    try:
        digest = DigestConfig(
            window_days=int(digest_raw.get("window_days", 7)),
            vault_app_base_url=str(digest_raw.get("vault_app_base_url", "http://localhost:3000")),
            vault_name=str(digest_raw.get("vault_name", "AI Learnings")),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"config.yml 'digest.window_days' must be an integer: {exc}") from exc
    return Config(
        watchlist=watchlist,
        seed_categories=seed_categories,
        ingest=ingest,
        digest=digest,
    )
