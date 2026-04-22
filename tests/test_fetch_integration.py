"""Recorded-fixture integration test for the fetch pipeline.

Per cross-AI feedback `mock-heavy-tests-need-integration-fixture.md`:
the unit suite mocks `_load_transcript_for_video` and returns inline transcript
text wholesale. That shape is not what real yt-dlp returns — real tracks carry
only a `url` that must be HTTP-fetched. The three bugs surfaced in the
2026-04-21 smoke run (cb8f993) fell through that blind spot.

This test exercises the real `_load_transcript_for_video`,
`_fetch_subtitle_url`, and `_vtt_to_plain_text` code paths end-to-end by
mocking only at the boundaries: `yt_dlp.YoutubeDL.extract_info` (the library
surface) and `urllib.request.urlopen` (the HTTP layer).
"""

from __future__ import annotations

import io
import json

from src.fetch import FetchResult, fetch_video


def test_fetch_video_end_to_end_with_url_only_subtitle(
    mocker, fixtures_dir, tmp_path
):
    info_dict = json.loads(
        (fixtures_dir / "ytdlp-info-subtitle-url.json").read_text()
    )
    vtt_bytes = (fixtures_dir / "sample-subtitle.vtt").read_bytes()

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return info_dict

    mocker.patch("src.fetch.yt_dlp.YoutubeDL", FakeYDL)

    class FakeHTTPResponse(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_urlopen(url, timeout=None):
        assert url == info_dict["automatic_captions"]["en"][0]["url"]
        return FakeHTTPResponse(vtt_bytes)

    mocker.patch("src.fetch.urlopen", side_effect=fake_urlopen)

    result = fetch_video(
        info_dict["webpage_url"], raw_dir=tmp_path / "raw" / "youtube"
    )

    assert isinstance(result, FetchResult)
    assert result.video_id == info_dict["id"]
    assert result.title == info_dict["title"]
    assert result.channel == info_dict["channel"]
    assert result.duration_seconds == info_dict["duration"]
    assert result.published_at == "2025-04-04"

    assert "Hello and welcome to the talk." in result.transcript
    assert "Today we discuss agents." in result.transcript
    assert "We'll cover three ideas." in result.transcript
    assert "WEBVTT" not in result.transcript
    assert "-->" not in result.transcript
    assert "00:00:" not in result.transcript

    lines = [line for line in result.transcript.split("\n") if line.strip()]
    assert len(lines) == len(set(lines)), (
        f"VTT dedup failed — transcript has duplicated lines: {lines}"
    )

    assert result.raw_transcript_path.exists()
    assert result.raw_transcript_path.read_text() == result.transcript
