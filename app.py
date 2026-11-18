"""ViralClip AI: GitHub/Streamlit Community Cloud app; no paid APIs or Docker."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import threading
import uuid

import streamlit as st
from viralclip.core import download_video, pipeline

st.set_page_config(page_title="ViralClip AI", page_icon="🎬", layout="wide")
DATA = Path(tempfile.gettempdir()) / "viralclip_streamlit_jobs"
DATA.mkdir(parents=True, exist_ok=True)
@st.cache_resource
def server_lock():
    return threading.Lock()

st.title("🎬 ViralClip AI")
st.caption("Free local AI • CPU-only • GitHub + Streamlit Community Cloud • No paid APIs")
st.info("Best for spoken videos (podcasts, interviews, tutorials). Scores estimate highlight potential, not actual virality. Only process videos you are authorized to reuse.")

with st.sidebar:
    st.header("Clip settings")
    count = st.slider("Number of clips", min_value=5, max_value=7, value=5)
    min_s = st.slider("Minimum duration (seconds)", min_value=15, max_value=45, value=20, step=5)
    max_s = st.slider("Maximum duration (seconds)", min_value=30, max_value=75, value=45, step=5)
    mode_label = st.radio("Subtitles / download versions", ["Both versions", "With subtitles only", "Without subtitles only"], index=0,
                          help="Both versions creates two MP4 files per clip. On Streamlit free hosting this can take substantially longer.")
    mode = {"Both versions":"both", "With subtitles only":"on", "Without subtitles only":"off"}[mode_label]
    model = st.selectbox("CPU speech model", ["tiny", "base"], index=0,
                         help="Tiny is recommended on Streamlit Community Cloud. Base may be slower and use more memory.")
    language_label = st.selectbox("Audio language", ["Auto-detect", "English", "Urdu", "Hindi", "Spanish", "Arabic"], index=0)
    language = {"Auto-detect": None, "English": "en", "Urdu": "ur", "Hindi": "hi", "Spanish": "es", "Arabic": "ar"}[language_label]
    resolution = st.select_slider("Output resolution", options=[360, 540, 720], value=540,
                                  format_func=lambda x: f"{x} × {int(x*16/9)}")
    st.caption("YouTube and Vimeo recordings have no fixed duration limit. Longer videos take more time and temporary disk space.")

source_type = st.radio("Source", ["Video URL", "Upload video"], horizontal=True)
url = st.text_input("Public YouTube/Vimeo URL (HTTPS)", placeholder="https://www.youtube.com/watch?v=...", disabled=source_type != "Video URL")
uploaded = st.file_uploader("Or upload your own MP4/MOV/MKV/WEBM (≤1000 MB)", type=["mp4", "mov", "mkv", "webm"],
                            disabled=source_type != "Upload video")

if "job_dir" not in st.session_state:
    st.session_state.job_dir = None
if "manifest" not in st.session_state:
    st.session_state.manifest = None

if st.button("✨ Generate 5–7 clips", type="primary", disabled=max_s < min_s):
    if source_type == "Video URL" and not url.strip():
        st.error("Paste a valid public video URL first")
    elif source_type == "Upload video" and uploaded is None:
        st.error("Upload a video first")
    elif not server_lock().acquire(blocking=False):
        st.error("The free server is already working on another job; try again after it finishes")
    else:
        job_dir = DATA / uuid.uuid4().hex
        try:
            # Remove only this session's previous job. Other users' folders are not touched.
            prev = st.session_state.job_dir
            st.session_state.job_dir = None
            st.session_state.manifest = None
            if prev:
                shutil.rmtree(prev, ignore_errors=True)
            job_dir.mkdir(parents=True, exist_ok=False)
            status = st.empty()
            bar = st.progress(0)
            def update(message, fraction):
                status.write(message)
                bar.progress(min(100, max(0, int(fraction * 100))))
            if source_type == "Video URL":
                update("Downloading source (availability depends on the video platform)", .02)
                source = download_video(url.strip(), job_dir)
            else:
                uploaded.seek(0)
                suffix = Path(uploaded.name).suffix.lower()
                if suffix not in {".mp4", ".mov", ".mkv", ".webm"}:
                    raise ValueError("Unsupported video format")
                source = job_dir / f"source{suffix}"
                with source.open("wb") as out:
                    while chunk := uploaded.read(1024*1024):
                        out.write(chunk)
            result = pipeline(source.resolve(), job_dir.resolve(), count, min_s, max_s,
                              model, resolution, update, language=language, subtitle_mode=mode)
            st.session_state.job_dir = str(job_dir)
            st.session_state.manifest = result["manifest"]
            # Release storage used by the source and temporary caption files after rendering.
            source.unlink(missing_ok=True)
            for p in job_dir.glob("*.ass"):
                p.unlink(missing_ok=True)
            st.success(f"Created {len(result['manifest']['clips'])} clips. Download your results below.")
        except Exception as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            st.error(f"Generation failed: {exc}")
        finally:
            server_lock().release()

manifest = st.session_state.manifest
folder = Path(st.session_state.job_dir) if st.session_state.job_dir else None
if manifest and folder and folder.is_dir():
    st.divider()
    st.subheader(f"✅ {len(manifest['clips'])} generated highlights")
    st.caption(f"Detected language: {manifest['language']} · Output: vertical 9:16 · Files are temporary")
    for archive, filename in manifest["archives"].items():
        ap = folder / filename
        if ap.is_file():
            labels = {"all":"Download all clips (ZIP)", "with_subtitles":"Download subtitled clips (ZIP)", "without_subtitles":"Download clean clips (ZIP)"}
            with ap.open("rb") as f:
                st.download_button(f"⬇️ {labels[archive]}", data=f, file_name=filename,
                                   mime="application/zip", key=f"zip_{folder.name}_{archive}")
    for i, clip in enumerate(manifest["clips"], start=1):
        with st.expander(f"Clip {i} · {clip['title']} · score {clip['score']}/100", expanded=i == 1):
            st.caption(f"Source: {clip['start']:.1f}s – {clip['end']:.1f}s · {clip['reason']}")
            files = clip["files"]
            choice = st.radio("Preview version", list(files.keys()),
                              format_func=lambda k: "With subtitles" if k == "with_subtitles" else "Without subtitles",
                              horizontal=True, key=f"preview_{folder.name}_{i}")
            preview_file = folder / files[choice]
            if preview_file.exists():
                st.video(str(preview_file))
            cols = st.columns(len(files))
            for col, (key, filename) in zip(cols, files.items()):
                p = folder / filename
                if p.exists():
                    with col, p.open("rb") as f:
                        st.download_button("⬇️ With subtitles" if key == "with_subtitles" else "⬇️ Without subtitles",
                                           data=f, file_name=filename, mime="video/mp4",
                                           key=f"clip_{folder.name}_{i}_{key}")
            st.caption(clip["transcript"][:650])
    if st.button("🗑️ Delete my generated clips from this server"):
        shutil.rmtree(folder, ignore_errors=True)
        st.session_state.job_dir = None
        st.session_state.manifest = None
        st.rerun()

st.divider()
st.caption("Streamlit Community Cloud is a shared, resource-limited host. Do not use this as an unrestricted public processing service. Jobs may be lost on restart; download clips promptly.")
