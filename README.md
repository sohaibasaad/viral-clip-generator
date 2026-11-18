# ViralClip AI — Streamlit Community Cloud edition

A Python application that accepts a permitted YouTube/Vimeo URL or an uploaded spoken video, selects up to 5–7 non-overlapping highlights, crops to portrait (9:16), generates word-highlight captions, and provides **MP4 and ZIP downloads with subtitles, without subtitles, or both**. No paid AI API or Docker is required.

## 1. Publish to GitHub

1. Create an empty GitHub repository (example `viralclip-streamlit`).
2. Upload **the contents of this folder into the repository root**, including `.streamlit/config.toml` (GitHub's normal drag-and-drop uploader can skip hidden directories, so use Git or check it carefully).
3. Ensure `app.py`, `requirements.txt`, and `packages.txt` are directly in the repository root.

Using Git on your computer:

```bash
git init
git add .
git commit -m "Initial Streamlit AI reel generator"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/viralclip-streamlit.git
git push -u origin main
```

## 2. Deploy to Streamlit

1. Open https://share.streamlit.io/ and sign in with GitHub.
2. Create a new app and select your repository and `main` branch.
3. Set **Main file path** to `app.py`.
4. Under Advanced settings, choose Python **3.11 or 3.12** (3.12 recommended).
5. Deploy. Streamlit installs Python dependencies from `requirements.txt` and FFmpeg + a font via `packages.txt` automatically.
6. The first generation downloads a tiny/base Whisper model from its public model repository; this is **not a paid API**. Outbound access to model files is needed.

## 3. Subtitle modes

- **Both versions** (default): renders each selected clip twice; downloads for both individual variants, separate ZIPs, and combined ZIP.
- **With subtitles only**: outputs one burned-in-caption MP4 for each clip.
- **Without subtitles only**: outputs clean MP4s, without caption overlays.

Subtitle choice is made **before** generation, since captions are physically burned into the video during rendering. There is no way to remove burned-in subtitles from an already-rendered video; the clean version is rendered from the original source.

## 4. Important Streamlit free hosting limits

- Streamlit Community Cloud has relatively low available CPU and memory; exact resource allocation varies and may change. Transcription and encoding can take a long time or exhaust available resources.
- Defaults: 5 clips, 20–45 seconds each, 540×960, CPU `tiny` model, no fixed URL duration or byte cap. Browser uploads allow 150 MB per file. Speech recognition processes five minutes of audio at a time.
- Choose **Without subtitles only** or **With subtitles only**, and 360×640, for lower rendering demand.
- YouTube/Vimeo downloading with yt-dlp is **best effort** and can fail due to platform blocking, authentication, policy changes, or anti-bot checks. Uploading videos you control is more reliable.
- This is a **transcript-based heuristic highlighter**. It does not guarantee viral outcomes, does not reliably handle non-speech music/montages, and may return fewer than 5 clips if there are too few distinct spoken moments.
- The current face crop uses sampled face positions to select one **fixed crop per clip**; it does **not** continuously follow moving faces.
- Files live temporarily on the Streamlit server and can disappear on restart. Download promptly. There is no durable storage, multi-tenant isolation, or queue. A simple server lock prevents concurrent jobs within one running process.
- Do not make the app public to untrusted users without adding authentication, quotas, automatic stale-job cleanup, and sandboxing.
- Download and reuse only footage you own or are authorized to edit and republish.

## 5. Run locally (no Docker)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
# Install ffmpeg separately on your OS (packages.txt works automatically only on Streamlit Cloud)
streamlit run app.py
```

## 6. Files

```
app.py                    # Streamlit UI / subtitle toggles / previews / downloads
viralclip/core.py         # retrieval, CPU Whisper, highlight ranking, captions, FFmpeg
requirements.txt          # Python dependencies
packages.txt              # system packages for Streamlit Cloud
.streamlit/config.toml    # limits and server settings
tests/test_core.py        # unit tests
```

Tests: `python -m unittest discover -s tests -v`

## 7. Common problems

- **Out of memory or app restarted**: select the tiny model, 360px output, one subtitle mode, smaller source video. Free hosting is not suitable for consistently processing hour-long videos.
- **Download error**: try uploading the MP4 directly. Platform-supported URL downloads are not guaranteed.
- **No clips found**: use longer speech-heavy content and lower the minimum duration.
- **No captions on clean version**: expected. Use the subtitled download.
- **FFmpeg missing or subtitle filter unavailable**: confirm `packages.txt` is in the repository root and redeploy; FFmpeg must include `ass`/libass support.
