# RankingAgent

Automated "Top 5" ranking-video pipeline for the **DailyWreck** YouTube channel:
discovers viral clips (fails, Karen moments, worst tackles, ...) via Reddit,
downloads them, ranks/selects the top 5, edits them into one video with
rank/reaction overlays and a watermark, and uploads to YouTube — one video a day.

## Setup

1. Python 3.11+, then:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   pip install -r requirements.txt
   ```
2. Install [ffmpeg](https://ffmpeg.org/download.html) and make sure it's on your `PATH`.
3. Copy `.env.example` to `.env` and fill in:
   - A Reddit API app (type "script") from https://www.reddit.com/prefs/apps
   - A YouTube Data API v3 OAuth client secrets JSON from Google Cloud Console
     (needed later, for the upload step)
4. Themes (subreddits, titles, thresholds) live in `config/themes.yaml`.

## Usage

```
python -m rankingagent.cli discover --theme fails
python -m rankingagent.cli select --theme fails
```

## Status

M0-M2 done: scaffold, Reddit discovery/download, ranking/selection with dedupe.
Next: M3 editing (blocked on a logo asset + brand color hex), M4 YouTube upload,
M5 history/dedupe CLI, M6 daily headless-agent orchestration via Windows Task
Scheduler. See the project plan for the full roadmap.
