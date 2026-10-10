"""A YouTube URL resolves to its caption track. No live YouTube call."""

from pathlib import Path
from unittest.mock import patch

import pytest

from evid.services.doc_ingester import resolve_source
from evid.services.youtube import cues_to_text, fetch_transcript, youtube_video_id

_WATCH = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
_SHORT = "https://youtu.be/jNQXAC9IVRw"


def test_video_urls_and_a_playlist():
    assert youtube_video_id(_WATCH) == "jNQXAC9IVRw"
    assert youtube_video_id(_WATCH + "&list=PL123") == "jNQXAC9IVRw"
    assert youtube_video_id(_SHORT) == "jNQXAC9IVRw"
    assert (
        youtube_video_id("https://www.youtube.com/shorts/jNQXAC9IVRw") == "jNQXAC9IVRw"
    )
    assert youtube_video_id("https://www.youtube.com/live/jNQXAC9IVRw") == "jNQXAC9IVRw"
    assert youtube_video_id("https://example.com/watch?v=jNQXAC9IVRw") is None
    with pytest.raises(ValueError, match="One video URL is required"):
        youtube_video_id("https://www.youtube.com/playlist?list=PL123")
    with pytest.raises(ValueError, match="One video URL is required"):
        youtube_video_id("https://www.youtube.com/@jawed")


def test_cues_become_paragraphs():
    assert cues_to_text(["Hello elephants.", "They have trunks."]) == (
        "Hello elephants.\n\nThey have trunks."
    )
    assert cues_to_text(["  ", ""]) == ""


class _Snippet:
    def __init__(self, text: str) -> None:
        self.text = text


class _Track:
    def __init__(self, text: str) -> None:
        self.text = text
        self.fetched = False

    def fetch(self):
        self.fetched = True
        return [_Snippet(self.text)]


def test_manual_track_is_the_text_and_the_next_is_left():
    first, second = _Track("Hello elephants."), _Track("Andere Sprache.")

    class _Api:
        def list(self, video_id):
            assert video_id == "jNQXAC9IVRw"
            return [first, second]

    with patch("youtube_transcript_api.YouTubeTranscriptApi", _Api):
        assert fetch_transcript("jNQXAC9IVRw") == "Hello elephants."
    assert first.fetched and not second.fetched


def _raises(exc):
    class _Api:
        def list(self, video_id):
            raise exc

    return patch("youtube_transcript_api.YouTubeTranscriptApi", _Api)


def test_missing_and_blocked_captions_are_different_messages():
    from youtube_transcript_api import (
        AgeRestricted,
        IpBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    with (
        _raises(TranscriptsDisabled("jNQXAC9IVRw")),
        pytest.raises(ValueError, match="^This video is not transcribed\\.$"),
    ):
        fetch_transcript("jNQXAC9IVRw")
    with (
        _raises(IpBlocked("jNQXAC9IVRw")),
        pytest.raises(ValueError, match="^The transcript could not be fetched\\.$"),
    ):
        fetch_transcript("jNQXAC9IVRw")
    with (
        _raises(AgeRestricted("jNQXAC9IVRw")),
        pytest.raises(ValueError, match="^This video is age-restricted\\.$"),
    ):
        fetch_transcript("jNQXAC9IVRw")
    with (
        _raises(VideoUnavailable("jNQXAC9IVRw")),
        pytest.raises(ValueError, match="^This video is not available\\.$"),
    ):
        fetch_transcript("jNQXAC9IVRw")


def test_transcript_becomes_the_document_and_a_miss_does_not_render():
    captured = {}

    def fake_pdf(url, output_dir, html=None, stem=None):
        captured["html"] = html
        captured["stem"] = stem
        captured["url"] = url
        path = Path(output_dir) / f"{stem}.pdf"
        path.write_bytes(b"%PDF-1.4\n")
        return path, "Me at the zoo"

    with (
        patch(
            "evid.services.youtube.fetch_transcript",
            return_value="Hello elephants.\n\nThey have trunks.",
        ),
        patch(
            "evid.services.youtube.youtube_oembed",
            return_value=("Me at the zoo", "jawed"),
        ),
        patch("evid.core.typst_generation.web_to_pdf", side_effect=fake_pdf),
        patch("requests.get", side_effect=AssertionError("the watch page was fetched")),
    ):
        resolved = resolve_source(_SHORT)
    try:
        assert resolved.source_url == _SHORT
        assert resolved.title == "Me at the zoo"
        assert resolved.authors == "jawed"
        assert resolved.original_name == "jNQXAC9IVRw.pdf"
        assert captured["stem"] == "jNQXAC9IVRw"
        assert "Hello elephants." in captured["html"]
        assert "Me at the zoo" in captured["html"]
    finally:
        resolved.temp_dir.cleanup()

    with (
        patch(
            "evid.services.youtube.fetch_transcript",
            side_effect=ValueError("This video is not transcribed."),
        ),
        patch(
            "evid.core.typst_generation.web_to_pdf",
            side_effect=AssertionError("the page was rendered"),
        ),
        patch("requests.get", side_effect=AssertionError("the watch page was fetched")),
        pytest.raises(ValueError, match="^This video is not transcribed\\.$"),
    ):
        resolve_source(_WATCH)
