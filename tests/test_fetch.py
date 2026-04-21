import json
from pathlib import Path

import pytest

from src.fetch import extract_video_id, extract_youtube_urls_from_text, self_update_ytdlp


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc123", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
])
def test_extract_video_id(url, expected):
    assert extract_video_id(url) == expected


def test_extract_video_id_rejects_non_youtube():
    assert extract_video_id("https://vimeo.com/12345") is None
    assert extract_video_id("not a url") is None


def test_extract_urls_from_text_single():
    text = "Check this out: https://www.youtube.com/watch?v=dQw4w9WgXcQ — great video."
    assert extract_youtube_urls_from_text(text) == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


def test_extract_urls_from_text_multiple_forms():
    text = (
        "1) https://youtu.be/aaaaaaaaaaa\n"
        "2) also https://www.youtube.com/watch?v=bbbbbbbbbbb&t=42\n"
        "3) vimeo https://vimeo.com/ignoreme"
    )
    urls = extract_youtube_urls_from_text(text)
    assert len(urls) == 2
    assert any("aaaaaaaaaaa" in u for u in urls)
    assert any("bbbbbbbbbbb" in u for u in urls)


def test_extract_urls_from_text_empty():
    assert extract_youtube_urls_from_text("no links here") == []


def test_self_update_runs_pip_install(mocker):
    mock_run = mocker.patch("src.fetch.subprocess.run")
    mock_run.return_value.returncode = 0
    self_update_ytdlp()
    mock_run.assert_called_once()
    args = mock_run.call_args.args[0]
    assert "pip" in args
    assert "install" in args
    assert "-U" in args
    assert "yt-dlp" in args


def test_self_update_raises_on_failure(mocker):
    mock_run = mocker.patch("src.fetch.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "network error"
    with pytest.raises(RuntimeError, match="yt-dlp self-update failed"):
        self_update_ytdlp()


def test_self_update_raises_on_timeout(mocker):
    import subprocess as _subprocess
    mock_run = mocker.patch("src.fetch.subprocess.run")
    mock_run.side_effect = _subprocess.TimeoutExpired(cmd="pip", timeout=120)
    with pytest.raises(RuntimeError, match="timed out"):
        self_update_ytdlp()


# ---------------------------------------------------------------------------
# Task 11: fetch_video wrapper
# ---------------------------------------------------------------------------

from src.fetch import FetchResult, fetch_video, FetchError


def test_fetch_video_returns_shaped_result_on_success(mocker, fixtures_dir, tmp_path):
    metadata = json.loads((fixtures_dir / "sample-video.json").read_text())
    transcript = (fixtures_dir / "sample-transcript.txt").read_text()

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return {**metadata, "_transcript_text": transcript}

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FakeYDL)
    mocker.patch("src.fetch._load_transcript_for_video",
                 return_value=transcript)

    result = fetch_video("https://www.youtube.com/watch?v=" + metadata["id"],
                        raw_dir=tmp_path / "raw" / "youtube")
    assert isinstance(result, FetchResult)
    assert result.video_id == metadata["id"]
    assert result.title == metadata["title"]
    assert result.duration_seconds == metadata["duration"]
    # published_at converts YYYYMMDD → YYYY-MM-DD
    yyyymmdd = metadata["upload_date"]
    assert result.published_at == f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    assert result.transcript == transcript
    assert result.raw_transcript_path.exists()
    assert result.raw_transcript_path.read_text() == transcript


def test_fetch_video_raises_when_no_captions(mocker, fixtures_dir, tmp_path):
    metadata = json.loads((fixtures_dir / "sample-video.json").read_text())

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return metadata

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FakeYDL)
    mocker.patch("src.fetch._load_transcript_for_video", return_value=None)

    with pytest.raises(FetchError, match="no captions"):
        fetch_video(metadata["webpage_url"], raw_dir=tmp_path / "raw" / "youtube")


def test_fetch_video_wraps_ytdlp_exception_as_fetch_error(mocker, tmp_path):
    class FailingYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            raise RuntimeError("video unavailable: private")

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FailingYDL)
    with pytest.raises(FetchError, match="yt-dlp extract_info failed"):
        fetch_video(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            raw_dir=tmp_path / "raw" / "youtube",
        )


def test_fetch_video_wraps_missing_field_as_fetch_error(mocker, tmp_path):
    class PartialYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return {"id": "dQw4w9WgXcQ", "title": "ok", "_transcript_text": "hello"}

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", PartialYDL)
    with pytest.raises(FetchError, match="missing expected field"):
        fetch_video(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            raw_dir=tmp_path / "raw" / "youtube",
        )


# ---------------------------------------------------------------------------
# Task 12: list_new_videos_for_channel
# ---------------------------------------------------------------------------

from src.fetch import list_new_videos_for_channel


def test_list_new_videos_stops_at_last_seen(mocker):
    feed = {
        "entries": [
            {"id": "v3", "upload_date": "20260421"},
            {"id": "v2", "upload_date": "20260418"},
            {"id": "v1", "upload_date": "20260410"},
        ]
    }

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return feed

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FakeYDL)
    new = list_new_videos_for_channel(
        "https://www.youtube.com/@Foo",
        last_seen_video_id="v2",
        lookback_days=30,
        now="2026-04-21",
    )
    assert [v["id"] for v in new] == ["v3"]


def test_list_new_videos_respects_lookback_when_no_last_seen(mocker):
    feed = {
        "entries": [
            {"id": "v3", "upload_date": "20260421"},
            {"id": "v2", "upload_date": "20260415"},
            {"id": "v1", "upload_date": "20260301"},
        ]
    }

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return feed

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FakeYDL)
    new = list_new_videos_for_channel(
        "https://www.youtube.com/@Foo",
        last_seen_video_id=None,
        lookback_days=14,
        now="2026-04-21",
    )
    assert [v["id"] for v in new] == ["v3", "v2"]


def test_list_new_videos_wraps_ytdlp_exception_as_fetch_error(mocker):
    class FailingYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            raise RuntimeError("channel not found")

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FailingYDL)
    with pytest.raises(FetchError, match="channel feed failed"):
        list_new_videos_for_channel(
            "https://www.youtube.com/@nonexistent",
            last_seen_video_id=None,
            lookback_days=14,
            now="2026-04-21",
        )
