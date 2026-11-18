"""YouTube segment previews use public timing metadata and the embedded player."""
import json
import math
import re
from urllib.parse import parse_qs, urlsplit

from .core import Word, check_url, make_candidates


def video_id(url):
    check_url(url)
    parts = urlsplit(url.strip())
    path = parts.path.strip("/").split("/")
    if parts.hostname in {"youtu.be", "www.youtu.be"}:
        value = path[0]
    elif parts.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if path == ["watch"]:
            value = parse_qs(parts.query).get("v", [""])[0]
        elif len(path) == 2 and path[0] in {"shorts", "embed", "live"}:
            value = path[1]
        else:
            value = ""
    else:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        raise ValueError("Paste a link to one YouTube video.")
    return value


def select_segments(info, count, minimum, maximum):
    if info.get("live_status") in {"is_live", "is_upcoming"}:
        raise ValueError("Choose a finished recording.")
    duration = math.floor(info.get("duration") or 0)
    if duration < minimum:
        raise ValueError("The available recording duration is shorter than the minimum clip length, or unavailable.")
    length = min(duration, (minimum + maximum) // 2)
    segments = []

    def add(start, title, basis):
        start = max(0, min(int(start), duration - length))
        if len(segments) < count and all(start + length <= s["start"] or start >= s["end"] for s in segments):
            segments.append(dict(start=start, end=start + length, title=title, basis=basis))

    peaks = sorted(info.get("heatmap") or [], key=lambda x: x.get("value") or 0, reverse=True)
    for peak in peaks:
        if peak.get("value") and peak.get("start_time") is not None and peak.get("end_time") is not None:
            add((peak["start_time"] + peak["end_time"] - length) / 2, "Frequently replayed moment", "YouTube replay activity")
    chapters = info.get("chapters") or []
    for chapter in chapters:
        if chapter.get("start_time") is not None:
            add(chapter["start_time"], chapter.get("title") or "Chapter opening", "YouTube chapter")
    for i in range(count):
        add(round(i * (duration - length) / max(1, count - 1)), "Timeline sample", "Evenly spaced preview")
    return segments


def caption_candidates(downloader, info, count, minimum, maximum):
    from yt_dlp.networking.exceptions import RequestError

    for tracks in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        languages = list(dict.fromkeys([info.get("language"), "en", "en-orig", *tracks]))
        track = next((t for lang in languages for t in tracks.get(lang, [])
                      if t.get("ext") == "json3" and t.get("url")), None)
        if not track:
            continue
        try:
            with downloader.urlopen(track["url"]) as response:
                events = json.load(response).get("events", [])
        except (ValueError, OSError, RequestError):
            continue
        words = []
        for event in events:
            tokens = "".join(seg.get("utf8", "") for seg in event.get("segs", [])).split()
            if not tokens or not event.get("dDurationMs"):
                continue
            start = event.get("tStartMs", 0) / 1000
            if words and start < words[-1].end:
                start = words[-1].end
            end = (event.get("tStartMs", 0) + event["dDurationMs"]) / 1000
            if end <= start:
                continue
            step = (end - start) / len(tokens)
            words.extend(Word(start + i * step, start + (i + 1) * step, token)
                         for i, token in enumerate(tokens))
        if words:
            return make_candidates(words, count, minimum, maximum, info["duration"])
    return []


def youtube_previews(identifier, count, minimum, maximum):
    import yt_dlp

    url = f"https://www.youtube.com/watch?v={identifier}"
    options = dict(quiet=True, noplaylist=True, skip_download=True, ignore_no_formats_error=True,
                   js_runtimes={"node": {}}, socket_timeout=12, extractor_retries=1)
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)
        if not info or info.get("id") != identifier:
            raise ValueError("Video details are unavailable.")
        fallback = select_segments(info, count, minimum, maximum)
        candidates = caption_candidates(downloader, info, count, minimum, maximum)
        if candidates:
            return [dict(start=int(c.start), end=min(int(info["duration"]), int(c.start) + maximum, math.ceil(c.end)),
                         title=c.title, basis="Ranked from public captions") for c in candidates]
        return fallback
