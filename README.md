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
   - `YOUTUBE_CLIENT_SECRETS_PATH` — a YouTube Data API v3 OAuth client
     secrets JSON from Google Cloud Console, created under the Google account
     that owns the DailyWreck channel (see `upload/youtube.py` docstring and
     the `youtube-upload-lessons` memory entry for the scope/gotchas this
     project already learned the hard way).
   - `GEMINI_API_KEY` — used for auto highlight-detection during `render`
     (free tier, but only 20 requests/day — see `video-pipeline-gotchas`).
   - Reddit API credentials (`REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`) are
     **not required** — Reddit closed self-service app registration behind a
     manual "Responsible Builder Policy" approval process (see the
     `reddit-api-blocker` memory entry), so `discover` (PRAW) doesn't work.
     Use `discover-rss` or `discover-manual` instead, which need no Reddit
     API access at all.
4. Themes (subreddits, on-screen label, thresholds) live in `config/themes.yaml`.
5. Brand assets live in `assets/brand/` (`watermark.png` used in every video,
   `banner.png` for the YouTube channel page).

## Usage

Each pipeline stage is its own CLI subcommand, so a human (or the daily agent
run, see below) can inspect/decide between steps:

```
python -m rankingagent.cli discover-rss --theme fails
python -m rankingagent.cli candidates --theme fails   # review for tone; RSS "top" isn't pre-filtered
python -m rankingagent.cli reject --theme fails --clip-ids <id1>,<id2>
python -m rankingagent.cli select --theme fails
python -m rankingagent.cli render --theme fails --reactions '{"<clip_id>": "Ouch"}'
python -m rankingagent.cli upload --theme fails --video <path> --title "..." --description "..."
python -m rankingagent.cli history --theme fails
```

## Dagelijkse automatisering

The full daily production (theme pick -> discover -> select -> write
reactions/title/description -> render -> upload) is driven by a **headless
Claude Code run**, not a plain Python cron job — the judgment-heavy steps
(what's trending, which title is best) need an LLM, while the mechanical
steps are the CLI commands above. See `daily_run/PROMPT.md` for the exact
instructions that run gets.

Setup on the home laptop:

1. Scope what the unattended run is allowed to do via a project
   `.claude/settings.json` permission allowlist (Bash for the `rankingagent`
   CLI, WebSearch for the trend-check) rather than relying only on
   `--dangerously-skip-permissions`.
2. `daily_run/run_daily.ps1` wraps the headless `claude -p` invocation and
   logs output to `data/logs/`.
3. Register it in Windows Task Scheduler: Create Task → Trigger: Daily at a
   fixed time → Action: `powershell.exe -File
   "<repo path>\daily_run\run_daily.ps1"`.
4. The very first upload needs a one-time interactive Google OAuth consent
   (a browser window opens) — run `upload` manually once before relying on
   the scheduled task.

## Status

M0-M6 built and verified end-to-end with **real Reddit content**: discovery,
download, ranking/selection with dedupe, ffmpeg/Pillow video assembly
matching the DailyWreck brand, YouTube upload, history/dedupe CLI, and the
daily headless-agent orchestration prompt + Task Scheduler wiring.

Reddit's official API (PRAW, `discover`) is still blocked pending their
manual "Responsible Builder Policy" approval — but that's no longer a
blocker for the pipeline: `discover-rss` (subreddit `/top/.rss` feeds) and
`discover-manual` (curated URL list), both via `yt-dlp`, need no API
approval and are the discovery paths actually in use. See
`reddit-api-blocker` memory for the full story.

First real video published 2026-08-17: episode #1,
`youtube.com/watch?v=oUDFu0OL4QE` (public). TikTok/Instagram as additional
clip sources remain deferred/optional (see the project plan).
