import pytest

from src.fetch import extract_video_id, extract_youtube_urls_from_text, self_update_ytdlp


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc123", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
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
