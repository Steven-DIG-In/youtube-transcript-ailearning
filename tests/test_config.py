from pathlib import Path

import pytest

from src.config import Config, ConfigError, load_config


def test_load_config_parses_valid_yaml(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(
        "watchlist:\n"
        "  - url: https://www.youtube.com/@Foo\n"
        "    default_categories: [optimising-ai]\n"
        "seed_categories: [optimising-ai, building-websites]\n"
        "ingest:\n"
        "  max_videos_per_run: 10\n"
        "  lookback_days: 14\n"
        "  min_duration_seconds: 60\n"
    )
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.seed_categories == ["optimising-ai", "building-websites"]
    assert cfg.watchlist[0].url == "https://www.youtube.com/@Foo"
    assert cfg.watchlist[0].default_categories == ["optimising-ai"]
    assert cfg.ingest.max_videos_per_run == 10
    assert cfg.ingest.lookback_days == 14
    assert cfg.ingest.min_duration_seconds == 60


def test_load_config_allows_empty_watchlist(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(
        "watchlist: []\n"
        "seed_categories: [x]\n"
        "ingest:\n"
        "  max_videos_per_run: 1\n"
        "  lookback_days: 1\n"
        "  min_duration_seconds: 1\n"
    )
    cfg = load_config(p)
    assert cfg.watchlist == []


def test_load_config_raises_on_missing_required(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text("watchlist: []\n")
    with pytest.raises(ConfigError, match="seed_categories"):
        load_config(p)


def test_load_config_raises_on_non_integer_ingest_field(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(
        "watchlist: []\n"
        "seed_categories: [x]\n"
        "ingest:\n"
        "  max_videos_per_run: ten\n"
        "  lookback_days: 14\n"
        "  min_duration_seconds: 60\n"
    )
    with pytest.raises(ConfigError, match="must be an integer"):
        load_config(p)


def test_load_config_raises_on_non_list_watchlist(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(
        "watchlist: not-a-list\n"
        "seed_categories: [x]\n"
        "ingest: {max_videos_per_run: 1, lookback_days: 1, min_duration_seconds: 1}\n"
    )
    with pytest.raises(ConfigError, match="'watchlist' must be a list"):
        load_config(p)


def test_load_config_raises_on_non_list_seed_categories(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(
        "watchlist: []\n"
        "seed_categories: not-a-list\n"
        "ingest: {max_videos_per_run: 1, lookback_days: 1, min_duration_seconds: 1}\n"
    )
    with pytest.raises(ConfigError, match="'seed_categories' must be a list"):
        load_config(p)


def test_load_config_raises_on_duplicate_seed_categories(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(
        "watchlist: []\n"
        "seed_categories: [optimising-ai, building-websites, optimising-ai]\n"
        "ingest: {max_videos_per_run: 1, lookback_days: 1, min_duration_seconds: 1}\n"
    )
    with pytest.raises(ConfigError, match="duplicates"):
        load_config(p)
