from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from rankingagent.config import DOWNLOADS_DIR, RENDERS_DIR, load_settings, load_themes
from rankingagent.db.store import (
    get_clips_by_status,
    get_selected_clips,
    get_video_history,
    init_db,
    mark_clip_audio,
    mark_clip_downloaded,
    mark_clip_duration,
    mark_clip_status,
    record_video,
    set_clip_reaction,
    upsert_clip,
    get_connection,
)
from rankingagent.discovery.manual import ManualDiscoverySource
from rankingagent.discovery.reddit import RedditDiscoverySource
from rankingagent.discovery.rss import RssDiscoverySource
from rankingagent.download.downloader import download_clip
from rankingagent.editing.assembler import render_video
from rankingagent.editing.clip_processor import extract_preview_frames, get_duration, has_audio_stream
from rankingagent.editing.highlight import find_highlight_window
from rankingagent.ranking.scorer import MAX_RAW_CLIP_SECONDS, select_and_rank
from rankingagent.upload.youtube import upload_video

logger = logging.getLogger(__name__)


def _download_pending(theme_name: str, no_check_certificate: bool) -> None:
    with get_connection() as conn:
        to_download = get_clips_by_status(conn, theme_name, "discovered")

    theme_dir = DOWNLOADS_DIR / theme_name
    downloaded = 0
    skipped_too_long = 0
    for row in to_download:
        # Metadata-known duration (from yt-dlp at discovery time) lets us
        # skip the download entirely for clips that would be excluded at
        # `select` anyway — no point pulling a 5-minute dashcam video just to
        # throw it away (see MAX_RAW_CLIP_SECONDS / 2026-08-18 feedback).
        if row["duration_seconds"] is not None and row["duration_seconds"] > MAX_RAW_CLIP_SECONDS:
            with get_connection() as conn:
                mark_clip_status(conn, row["id"], "too_long")
            skipped_too_long += 1
            continue

        local_path = download_clip(
            row["source_url"], row["id"], theme_dir, no_check_certificate=no_check_certificate
        )
        with get_connection() as conn:
            if local_path is not None:
                mark_clip_downloaded(conn, row["id"], str(local_path))
                try:
                    mark_clip_audio(conn, row["id"], has_audio_stream(local_path))
                except Exception:
                    logger.exception("Audio-stream probe failed for clip %s, assuming it has audio", row["id"])
                try:
                    mark_clip_duration(conn, row["id"], get_duration(local_path))
                except Exception:
                    logger.exception("Duration probe failed for clip %s", row["id"])
                downloaded += 1
            else:
                conn.execute(
                    "UPDATE clips SET status = 'download_failed', updated_at = datetime('now') WHERE id = ?",
                    (row["id"],),
                )

    logger.info(
        "Downloaded %d/%d clips for theme '%s' (%d skipped as too long, >%.0fs)",
        downloaded, len(to_download), theme_name, skipped_too_long, MAX_RAW_CLIP_SECONDS,
    )


def discover_and_download(theme_name: str) -> None:
    init_db()
    themes = load_themes()
    if theme_name not in themes:
        raise ValueError(f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}")
    theme = themes[theme_name]

    settings = load_settings()
    source = RedditDiscoverySource(settings)

    logger.info("Discovering clips for theme '%s' from %s", theme.name, theme.subreddits)
    clips = source.discover(
        theme_name=theme.name,
        subreddits=theme.subreddits,
        min_score=theme.min_score,
        limit=max(theme.clip_count * 4, 20),
    )
    logger.info("Discovered %d candidate clips", len(clips))

    with get_connection() as conn:
        for clip in clips:
            upsert_clip(conn, clip.as_db_row())

    _download_pending(theme.name, settings.ytdlp_no_check_certificate)


def discover_from_urls(theme_name: str, urls: list[str]) -> None:
    """Fallback discovery while Reddit API access is pending approval: the
    user supplies a curated list of post URLs instead of an automated
    subreddit search. See discovery.manual.ManualDiscoverySource."""
    init_db()
    themes = load_themes()
    if theme_name not in themes:
        raise ValueError(f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}")
    theme = themes[theme_name]

    settings = load_settings()
    source = ManualDiscoverySource(no_check_certificate=settings.ytdlp_no_check_certificate)

    logger.info("Fetching metadata for %d manually supplied URLs (theme '%s')", len(urls), theme.name)
    clips = source.discover_from_urls(theme.name, urls)
    logger.info("Resolved %d/%d clips", len(clips), len(urls))

    with get_connection() as conn:
        for clip in clips:
            upsert_clip(conn, clip.as_db_row())

    _download_pending(theme.name, settings.ytdlp_no_check_certificate)


def discover_via_rss(theme_name: str) -> None:
    """Fully automated discovery via subreddit RSS feeds — no Reddit API
    approval needed (see reddit-api-blocker memory: the API application was
    denied). Deliberately slow (paced requests to avoid Reddit's anonymous
    rate limit). IMPORTANT: RSS "top" posts are not pre-filtered for tone —
    review with `candidates`/`reject` before running `select`, since a
    subreddit's current top posts can skew political/tragic/graphic rather
    than the comedic tone this project wants (observed directly with
    r/PublicFreakout on 2026-08-14)."""
    init_db()
    themes = load_themes()
    if theme_name not in themes:
        raise ValueError(f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}")
    theme = themes[theme_name]

    settings = load_settings()
    source = RssDiscoverySource(no_check_certificate=settings.ytdlp_no_check_certificate)

    logger.info("RSS-discovering clips for theme '%s' from %s (this is slow by design)", theme.name, theme.subreddits)
    clips = source.discover(
        theme_name=theme.name,
        subreddits=theme.subreddits,
        min_score=theme.min_score,
        limit=max(theme.clip_count * 4, 20),
        time_filter=theme.time_filter,
    )
    logger.info("Discovered %d candidate clips", len(clips))

    with get_connection() as conn:
        for clip in clips:
            upsert_clip(conn, clip.as_db_row())

    _download_pending(theme.name, settings.ytdlp_no_check_certificate)


def list_candidates(theme_name: str) -> list[dict]:
    """Downloaded-but-not-yet-selected clips, for content review before
    `select` — check each caption/creator for tone/appropriateness and
    `reject` anything that doesn't fit before proceeding."""
    init_db()
    themes = load_themes()
    if theme_name not in themes:
        raise ValueError(f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}")
    theme = themes[theme_name]

    with get_connection() as conn:
        rows = get_clips_by_status(conn, theme.name, "downloaded")

    return [dict(row) for row in rows]


def reject_clips(theme_name: str, clip_ids: list[str]) -> None:
    """Mark clips as rejected so `select` skips them — used after reviewing
    `list_candidates` output for tone/appropriateness."""
    init_db()
    with get_connection() as conn:
        for clip_id in clip_ids:
            mark_clip_status(conn, clip_id, "rejected")
    logger.info("Rejected %d clips for theme '%s'", len(clip_ids), theme_name)


def select_top_clips(theme_name: str) -> list[dict]:
    init_db()
    themes = load_themes()
    if theme_name not in themes:
        raise ValueError(f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}")
    theme = themes[theme_name]

    with get_connection() as conn:
        ranked = select_and_rank(conn, theme.name, count=theme.clip_count)

    logger.info("Selected %d clips for theme '%s'", len(ranked), theme.name)
    return ranked


def preview_clip_frames(theme_name: str, count: int = 6) -> dict[str, list[dict]]:
    """For each currently-selected clip, sample `count` evenly-spaced frames
    across its full raw duration and return their paths/timestamps, so a
    reviewer can see where the fail/punchline actually happens before
    `render` trims each clip to its highlight window — the moment isn't
    always at the very start of the raw clip. Run this after `select`
    and before `render`; pass the chosen start times to `render` via
    --clip-starts."""
    init_db()
    themes = load_themes()
    if theme_name not in themes:
        raise ValueError(f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}")
    theme = themes[theme_name]

    with get_connection() as conn:
        rows = get_selected_clips(conn, theme.name)
        if not rows:
            raise ValueError(
                f"No selected clips for theme '{theme_name}' — run `select` first."
            )

    preview_root = DOWNLOADS_DIR / theme.name / "_preview"
    result: dict[str, list[dict]] = {}
    for row in rows:
        clip_dir = preview_root / row["id"]
        result[row["id"]] = extract_preview_frames(Path(row["local_path"]), clip_dir, count=count)

    return result


def _auto_detect_clip_windows(
    ranked_clips: list[dict], clip_starts: dict[str, float], gemini_api_key: str
) -> tuple[dict[str, float], dict[str, float]]:
    """Ask Gemini for the (start, duration) highlight window of every clip
    that doesn't already have an explicit start in `clip_starts` — see
    editing.highlight.find_highlight_window. An explicit clip_starts entry
    always wins (lets a caller override a specific clip's start; that clip
    keeps the default fixed duration since we have no detected window for
    it). Clips where Gemini's call fails fall back to start=0 at the default
    duration rather than blocking the render."""
    starts = dict(clip_starts)
    durations: dict[str, float] = {}
    if not gemini_api_key:
        logger.warning("GEMINI_API_KEY not set — skipping auto highlight detection, all unset clips start at 0")
        return starts, durations

    for clip in ranked_clips:
        if clip["id"] in starts:
            continue
        try:
            window = find_highlight_window(Path(clip["local_path"]), gemini_api_key)
        except Exception:
            logger.exception("Gemini highlight detection failed for clip %s", clip["id"])
            window = None

        start, duration = window if window is not None else (0.0, None)
        starts[clip["id"]] = start
        if duration is not None:
            durations[clip["id"]] = duration
        logger.info(
            "Auto-detected window for clip %s: start=%.1fs duration=%s",
            clip["id"], start, f"{duration:.1f}s" if duration is not None else "default",
        )

    return starts, durations


def render_video_for_theme(
    theme_name: str,
    reactions: dict[str, str],
    title_text: str | None = None,
    clip_starts: dict[str, float] | None = None,
    auto_highlight: bool = True,
) -> Path:
    init_db()
    themes = load_themes()
    if theme_name not in themes:
        raise ValueError(f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}")
    theme = themes[theme_name]
    title_text = title_text or theme.on_screen_label

    with get_connection() as conn:
        rows = get_selected_clips(conn, theme.name)
        if not rows:
            raise ValueError(
                f"No selected clips for theme '{theme_name}' — run `select` first."
            )
        ranked_clips = [dict(row) for row in rows]

        for clip_id, reaction in reactions.items():
            set_clip_reaction(conn, clip_id, reaction)

    clip_starts = clip_starts or {}
    clip_durations: dict[str, float] = {}
    if auto_highlight:
        settings = load_settings()
        clip_starts, clip_durations = _auto_detect_clip_windows(ranked_clips, clip_starts, settings.gemini_api_key)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    work_dir = RENDERS_DIR / theme.name / f"work_{timestamp}"
    output_path = RENDERS_DIR / theme.name / f"{timestamp}.mp4"

    render_video(
        title_text, ranked_clips, reactions, work_dir, output_path,
        clip_starts=clip_starts, clip_durations=clip_durations,
    )
    logger.info("Rendered video for theme '%s' at %s", theme.name, output_path)

    _cleanup_after_render(theme.name, work_dir)

    return output_path


def _cleanup_after_render(theme_name: str, work_dir: Path) -> None:
    """Once the final mp4 is assembled, no loose/raw clip files should be
    left behind — not just the 5 that were used, but every raw clip
    downloaded for this theme (candidates that were discovered/rejected but
    never selected). Wipes the whole theme download dir and the intermediate
    work dir (normalized clips, per-segment overlays, segment mp4s); only
    the final render survives. Any clip rows still referencing those deleted
    files are marked 'rejected' so a future `select` can't pick a clip whose
    local file no longer exists."""
    theme_dir = DOWNLOADS_DIR / theme_name
    if theme_dir.exists():
        shutil.rmtree(theme_dir)

    if work_dir.exists():
        shutil.rmtree(work_dir)

    with get_connection() as conn:
        leftover = get_clips_by_status(conn, theme_name, "downloaded")
        for row in leftover:
            mark_clip_status(conn, row["id"], "rejected")

    logger.info("Cleaned up all raw clips for theme '%s' and work dir %s", theme_name, work_dir)


def upload_rendered_video(
    theme_name: str,
    video_path: Path,
    title: str,
    description: str,
    tags: list[str] | None = None,
    privacy_status: str | None = None,
    publish_at: str | None = None,
) -> str:
    init_db()
    themes = load_themes()
    if theme_name not in themes:
        raise ValueError(f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}")
    theme = themes[theme_name]

    video_id = upload_video(
        video_path,
        title=title,
        description=description,
        tags=tags or [],
        privacy_status=privacy_status,
        publish_at=publish_at,
    )

    with get_connection() as conn:
        rows = get_selected_clips(conn, theme.name)
        clip_ids = [row["id"] for row in rows]
        record_video(conn, theme.name, title, video_id, str(video_path), clip_ids)
        for clip_id in clip_ids:
            mark_clip_status(conn, clip_id, "published")

    logger.info("Published video for theme '%s': https://youtube.com/watch?v=%s", theme.name, video_id)
    return video_id


def get_theme_history(theme_name: str) -> list[dict]:
    """Previously published videos for a theme (title, youtube id, clip ids,
    publish date) — used by the daily agent run to avoid repeating a topic
    and to see which clips are already spent."""
    init_db()
    themes = load_themes()
    if theme_name not in themes:
        raise ValueError(f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}")
    theme = themes[theme_name]

    with get_connection() as conn:
        rows = get_video_history(conn, theme.name)

    return [dict(row) for row in rows]
