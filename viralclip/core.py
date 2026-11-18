from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from bisect import bisect_left, bisect_right
from typing import Callable
from urllib.parse import urlsplit

HOOK_WORDS = {"secret", "mistake", "truth", "never", "always", "why", "how", "best", "worst", "actually", "surprising", "problem", "solution", "important", "first", "instead", "learned", "imagine", "remember", "unexpected", "warning", "crazy", "realize", "biggest", "simple", "trick", "tip", "changed", "because", "here's", "heres"}
FILLER = {"um", "uh", "erm", "you know", "like"}

@dataclass
class Word:
    start: float
    end: float
    text: str

@dataclass
class Candidate:
    start: float
    end: float
    score: float
    title: str
    reason: str
    transcript: str


def run(cmd: list[str], timeout: int = 3600) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Executable not installed: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("External processing command timed out") from exc
    if p.returncode:
        raise RuntimeError(f"Command failed: {cmd[0]}: {p.stderr[-1400:]}")
    return p.stdout


def probe(path: Path) -> dict:
    result = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)], timeout=30))
    video = next((s for s in result.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise ValueError("This file does not contain a video stream")
    return {"duration": float(result["format"]["duration"]), "width": int(video["width"]), "height": int(video["height"]), "audio": any(s.get("codec_type") == "audio" for s in result.get("streams", []))}


def check_url(url: str) -> None:
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port:
        raise ValueError("Enter a public HTTPS video URL")
    hostname = parts.hostname.lower().rstrip(".")
    allowed = ("youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com", "www.youtu.be", "vimeo.com", "www.vimeo.com")
    if hostname not in allowed:
        raise ValueError("For security, URL input currently supports YouTube and Vimeo only. Upload your other videos as MP4.")


def download_video(url: str, directory: Path, max_duration_s: int, max_bytes: int) -> Path:
    import yt_dlp
    check_url(url)
    directory.mkdir(parents=True, exist_ok=True)
    opts = {"format": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b", "merge_output_format": "mp4", "outtmpl": str(directory / "source.%(ext)s"), "noplaylist": True, "quiet": True, "no_warnings": True, "socket_timeout": 20, "retries": 2, "max_filesize": max_bytes, "match_filter": yt_dlp.utils.match_filter_func(f"duration <= {max_duration_s}"), "restrictfilenames": True, "ignoreerrors": False}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or info.get("_type") == "playlist":
                raise ValueError("Please provide a single video URL")
            duration = info.get("duration")
            if duration and duration > max_duration_s:
                raise ValueError(f"Video exceeds the {max_duration_s // 60}-minute limit")
            filesize = info.get("filesize") or info.get("filesize_approx")
            if filesize and filesize > max_bytes:
                raise ValueError("Source video exceeds the configured file size limit")
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(f"Could not download this video. It may be restricted or unavailable: {exc}") from exc
    files = [p for p in directory.glob("source.*") if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
    if not files:
        raise RuntimeError("Download finished without a playable video file")
    source = max(files, key=lambda p: p.stat().st_size)
    if source.stat().st_size > max_bytes:
        source.unlink(missing_ok=True)
        raise ValueError("Source file exceeds the configured size limit")
    return source


def transcribe(source: Path, model_name: str = "base", language: str | None = None) -> tuple[list[Word], str]:
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=2)
    segments, info = model.transcribe(str(source), beam_size=1, language=language, vad_filter=True, word_timestamps=True, condition_on_previous_text=False)
    words: list[Word] = []
    for segment in segments:
        for w in segment.words or []:
            if w.word.strip() and w.end > w.start:
                words.append(Word(round(w.start, 3), round(w.end, 3), w.word.strip()))
    if not words:
        raise ValueError("No recognizable speech found. This version requires spoken content for highlight scoring")
    return words, info.language


def score_text(words: list[Word], start: float, end: float) -> tuple[float, str]:
    spoken = " ".join(w.text for w in words)
    tokens = re.findall(r"[\w']+", spoken.lower())
    if not tokens:
        return 0.0, "No speech"
    first = " ".join(w.text for w in words[:min(18, len(words))]).lower()
    first_tokens = set(re.findall(r"[\w']+", first))
    hook = min(1.0, len(first_tokens & HOOK_WORDS) / 2.0 + (0.25 if "?" in first else 0))
    content = min(1.0, len(set(t for t in tokens if len(t) > 4)) / 45.0)
    density = len(tokens) / max(1.0, end - start) * 60
    pacing = max(0.0, 1 - abs(density - 145) / 145)
    emotion = min(1.0, (spoken.count("!") + spoken.count("?") + sum(tokens.count(t) for t in ("wow", "amazing", "shocking", "incredible"))) / 3)
    completeness = 1.0 if words[-1].text.endswith((".", "!", "?")) else 0.45
    filler_rate = sum(t in FILLER for t in tokens) / len(tokens)
    length_fit = max(0.0, 1 - abs((end-start)-42)/100)
    raw = 25*hook + 25*content + 20*emotion + 15*completeness + 10*pacing + 5*length_fit
    raw = max(0, min(100, raw - 100*filler_rate))
    reason = ", ".join(label for label, val in (("strong opening",hook),("informative",content),("expressive",emotion),("clear ending",completeness),("good pace",pacing)) if val >= .70) or "Spoken highlight"
    return round(raw, 1), reason


def make_candidates(words: list[Word], count: int, min_s: int, max_s: int, duration: float) -> list[Candidate]:
    # Candidate windows start at natural word boundaries; ends prefer punctuation.
    candidates: list[Candidate] = []
    if not words:
        return candidates
    step = max(1, len(words) // 140)
    starts = sorted(set([0] + list(range(0, len(words), step)) + [i+1 for i,w in enumerate(words[:-1]) if w.text.endswith((".", "?", "!"))]))
    ends_ts = [w.end for w in words]
    for i in starts:
        start = words[i].start
        if duration - start < min_s:
            continue
        lo = max(i+1, bisect_left(ends_ts, start + min_s, lo=i+1))
        hi = bisect_right(ends_ts, start + max_s, lo=lo)
        valid_end_idx = range(lo, hi)
        if not valid_end_idx:
            # Short source videos can provide a shorter contextual clip.
            if duration < min_s and i == 0:
                valid_end_idx = [len(words)-1]
            else:
                continue
        ends = [j for j in valid_end_idx if words[j].text.endswith((".", "?", "!"))]
        target = start + (min_s+max_s)/2
        ends = sorted(ends or valid_end_idx, key=lambda j: abs(words[j].end-target))[:3]
        for j in ends:
            end = min(duration, words[j].end + 0.30)
            excerpt = words[i:j+1]
            score, reason = score_text(excerpt, start, end)
            title_tokens = re.findall(r"[\w'-]+", " ".join(w.text for w in excerpt[:12]))
            title = " ".join(title_tokens[:8]).strip() or "Highlight"
            candidates.append(Candidate(round(max(0,start-0.15),2), round(end,2), score, title, reason, " ".join(w.text for w in excerpt)))
    candidates.sort(key=lambda c: (-c.score, c.start))
    selected: list[Candidate] = []
    for c in candidates:
        if all(max(0, min(c.end, other.end) - max(c.start, other.start)) < 0.20 * min(c.end-c.start, other.end-other.start) for other in selected):
            selected.append(c)
        if len(selected) >= count:
            break
    return selected


def face_center(source: Path, start: float, end: float, width: int, height: int) -> float:
    """Sample frame faces, return median X center, otherwise centered crop."""
    try:
        import cv2
        cap = cv2.VideoCapture(str(source))
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        centers = []
        for sec in [start + (end-start)*f for f in (0.2,0.4,0.6,0.8)]:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0, sec)*1000)
            ok, frame = cap.read()
            if not ok:
                continue
            h,w = frame.shape[:2]
            scale = min(1,640/max(w,h))
            small = cv2.resize(frame, None, fx=scale, fy=scale)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=4, minSize=(28,28))
            if len(faces):
                x,y,fw,fh = max(faces, key=lambda b:b[2]*b[3])
                centers.append((x+fw/2)/small.shape[1])
        cap.release()
        return float(sorted(centers)[len(centers)//2]) if centers else 0.5
    except Exception:
        return 0.5


def ass_time(sec: float) -> str:
    centi = max(0, int(round(sec*100)))
    return f"{centi//360000}:{(centi//6000)%60:02}:{(centi//100)%60:02}.{centi%100:02}"


def escape_ass(txt: str) -> str:
    return txt.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def write_captions(words: list[Word], clip: Candidate, out: Path) -> None:
    # 2-4 word caption groups, yellow active word; rendered with libass.
    filtered = [w for w in words if w.start < clip.end and w.end > clip.start]
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,76,&H00FFFFFF,&H0000FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,5,1,2,64,64,390,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for k in range(0, len(filtered), 4):
        group = filtered[k:k+4]
        for i,w in enumerate(group):
            s = max(0, w.start - clip.start)
            e = min(clip.end-clip.start, w.end-clip.start)
            if e <= s:
                continue
            txt = " ".join((r"{\c&H0045FFFF&}" + escape_ass(v.text) + r"{\c&H00FFFFFF&}") if idx == i else escape_ass(v.text) for idx,v in enumerate(group))
            events.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Default,,0,0,0,,{txt}")
    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def render(source: Path, clip: Candidate, words: list[Word], output_dir: Path, index: int, info: dict, resolution: int = 540, crf: int = 26, subtitles: bool = True) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    variant = "subtitled" if subtitles else "clean"
    subs = output_dir / f"clip_{index:02}.ass"
    if subtitles:
        write_captions(words, clip, subs)
    out = output_dir / f"clip_{index:02}_{variant}.mp4"
    width,height = info["width"], info["height"]
    center = face_center(source, clip.start, clip.end, width, height)
    # Crop to 9:16 from existing footage; no letterbox, no unnecessary distortion.
    crop_w = min(width, int(height*9/16))
    crop_h = min(height, int(width*16/9))
    x = int(max(0, min(width-crop_w, width*center-crop_w/2)))
    y = int(max(0, (height-crop_h)//2))
    # Relative ASS filename (no shell escaping) because ffmpeg runs inside output folder.
    vf = f"crop={crop_w}:{crop_h}:{x}:{y},scale={resolution}:{int(resolution*16/9)},setsar=1"
    if subtitles:
        vf += f",ass={subs.name}"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(clip.start), "-i", str(source), "-t", str(clip.end-clip.start), "-vf", vf, "-map", "0:v:0"]
    if info["audio"]:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-threads", "2", str(out)]
    # Absolute paths avoid process-wide chdir races across Streamlit sessions.
    if subtitles:
        vf = vf.replace(f"ass={subs.name}", f"ass={subs.as_posix().replace(chr(58), chr(92)+chr(58))}")
        cmd[cmd.index("-vf") + 1] = vf
    run(cmd, timeout=2400)
    return out


def build_zip(files: list[Path], out: Path) -> Path:
    import zipfile
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as zf:
        for p in files:
            zf.write(p, p.name)
    return out


def pipeline(source: Path, directory: Path, count: int, min_s: int, max_s: int, model: str, resolution: int, progress: Callable[[str, float], None], language: str | None = None, subtitle_mode: str = "both") -> dict:
    if subtitle_mode not in {"both", "on", "off"}:
        raise ValueError("Invalid subtitle mode")
    progress("Checking source video", .05)
    info = probe(source)
    if info["duration"] > int(os.getenv("MAX_VIDEO_MINUTES", "20")) * 60:
        raise ValueError("Video exceeds the configured duration limit")
    if not info["audio"]:
        raise ValueError("Source has no audio; this tool selects clips from speech")
    progress("Transcribing speech on CPU", .12)
    words, detected_language = transcribe(source, model, language)
    progress("Ranking video highlights", .55)
    clips = make_candidates(words, count, min_s, max_s, info["duration"])
    if not clips:
        raise ValueError("No suitable clips found. Use a longer spoken video or reduce minimum clip duration")
    variants = [True, False] if subtitle_mode == "both" else [subtitle_mode == "on"]
    exported = []
    clip_items = []
    for n, clip in enumerate(clips, 1):
        item = asdict(clip)
        item["files"] = {}
        for sub in variants:
            progress(f"Rendering clip {n}/{len(clips)} ({'subtitles' if sub else 'no subtitles'})", .60 + .37 * ((n-1)*len(variants) + (0 if sub == variants[0] else 1))/(len(clips)*len(variants)))
            file = render(source, clip, words, directory, n, info, resolution, subtitles=sub)
            item["files"]["with_subtitles" if sub else "without_subtitles"] = file.name
            exported.append(file)
        clip_items.append(item)
    archives = {}
    if subtitle_mode == "both":
        archives["with_subtitles"] = build_zip([directory / c["files"]["with_subtitles"] for c in clip_items], directory / "clips_with_subtitles.zip").name
        archives["without_subtitles"] = build_zip([directory / c["files"]["without_subtitles"] for c in clip_items], directory / "clips_without_subtitles.zip").name
    archives["all"] = build_zip(exported, directory / "all_clips.zip").name
    manifest = {"language": detected_language, "duration": info["duration"], "subtitle_mode": subtitle_mode, "clips": clip_items, "archives": archives}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    progress("Finished", 1.0)
    return {"manifest": manifest, "files": exported}
