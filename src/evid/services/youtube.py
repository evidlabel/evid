"""A YouTube video URL becomes its caption track, not the watch page.

The official captions API will not download someone else's transcript. The
``youtube-transcript-api`` library reads the public caption track the player
already uses. No API key.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_NOT_TRANSCRIBED = "This video is not transcribed."
_NOT_FETCHED = "The transcript could not be fetched."
_AGE_RESTRICTED = "This video is age-restricted."
_UNAVAILABLE = "This video is not available."
_ONE_VIDEO = "One video URL is required."

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = frozenset(
    {
        "youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "youtu.be",
    }
)


def youtube_video_id(url: str) -> str | None:
    """The video id, or None when *url* is not a YouTube URL.

    A YouTube page that is not one video (a playlist, a channel) raises
    ValueError. The caller then does not render the page.
    """
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or host not in _HOSTS:
        return None
    video = _id_from(host, parsed.path, parse_qs(parsed.query))
    if video:
        return video
    raise ValueError(_ONE_VIDEO)


def _id_from(host: str, path: str, query: dict) -> str:
    parts = [p for p in path.split("/") if p]
    if host == "youtu.be":
        candidate = parts[0] if parts else ""
    elif parts[:1] == ["watch"]:
        candidate = (query.get("v") or [""])[0]
    elif parts[:1] in (["shorts"], ["live"], ["embed"], ["v"]):
        candidate = parts[1] if len(parts) > 1 else ""
    else:
        candidate = ""
    if _VIDEO_ID.fullmatch(candidate):
        return candidate
    return ""


def cues_to_text(cues: list[str]) -> str:
    """Spoken text only. Cues join into sentences, then paragraphs."""
    parts = [" ".join(c.split()) for c in cues]
    raw = " ".join(p for p in parts if p)
    return re.sub(r"([.!?])\s+", r"\1\n\n", raw).strip()


def fetch_transcript(video_id: str) -> str:
    """The caption track as plain text.

    A manual caption is preferred to an automatic one. Nothing is translated.
    ValueError carries the message the GUI and the CLI show.
    """
    from youtube_transcript_api import (
        AgeRestricted,
        CouldNotRetrieveTranscript,
        IpBlocked,
        NoTranscriptFound,
        PoTokenRequired,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
        VideoUnplayable,
        YouTubeTranscriptApi,
    )

    try:
        tracks = list(YouTubeTranscriptApi().list(video_id))
    except (TranscriptsDisabled, NoTranscriptFound) as exc:
        raise ValueError(_NOT_TRANSCRIBED) from exc
    except (IpBlocked, RequestBlocked, PoTokenRequired) as exc:
        raise ValueError(_NOT_FETCHED) from exc
    except AgeRestricted as exc:
        raise ValueError(_AGE_RESTRICTED) from exc
    except (VideoUnavailable, VideoUnplayable) as exc:
        raise ValueError(_UNAVAILABLE) from exc
    except CouldNotRetrieveTranscript as exc:
        raise ValueError(_NOT_FETCHED) from exc
    if not tracks:
        raise ValueError(_NOT_TRANSCRIBED)
    try:
        fetched = tracks[0].fetch()
    except (TranscriptsDisabled, NoTranscriptFound) as exc:
        raise ValueError(_NOT_TRANSCRIBED) from exc
    except (IpBlocked, RequestBlocked, PoTokenRequired) as exc:
        raise ValueError(_NOT_FETCHED) from exc
    except CouldNotRetrieveTranscript as exc:
        raise ValueError(_NOT_FETCHED) from exc
    text = cues_to_text([snippet.text for snippet in fetched])
    if not text:
        raise ValueError(_NOT_TRANSCRIBED)
    return text


def youtube_oembed(video_id: str) -> tuple[str, str]:
    """``(title, channel)`` from YouTube oEmbed. Empty when it does not answer."""
    import requests

    watch = f"https://www.youtube.com/watch?v={video_id}"
    try:
        response = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": watch, "format": "json"},
            timeout=15,
            headers={"User-Agent": "evid"},
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    return str(data.get("title") or ""), str(data.get("author_name") or "")
