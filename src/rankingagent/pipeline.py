from __future__ import annotations

import logging
import time
from pathlib import Path

from rankingagent.config import DOWNLOADS_DIR, RENDERS_DIR, load_settings, load_themes
from rankingagent.db.store import (
    get_clips_by_status,
    get_selected_clips,
    init_db,
    mark_clip_downloaded,
    mark_clip_status,
    record_video,
    set_clip_reaction,
    upsert_clip,
    get_connection,
)
from rankingagent.discovery.reddit import RedditDiscoverySource
from rankingagent.download.downloader import download_clip
from rankingagent.editing.assembler import render_video
from rankingagent.ranking.scorer import select_and_rank
from rankingagent.upload.youtube import upload_video

logger = logging.getLogger(__name__)


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

    with get_connection() as conn:
        to_download = get_clips_by_status(conn, theme.name, "discovered")

    theme_dir = DOWNLOADS_DIR / theme.name
    downloaded = 0
    for row in to_download:
        local_path = download_clip(row["source_url"], row["id"], theme_dir)
        with get_connection() as conn:
            if local_path is not None:
                mark_clip_downloaded(conn, row["id"], str(local_path))
                downloaded += 1
            else:
                conn.execute(
                    "UPDATE clips SET status = 'download_failed', updated_at = datetime('now') WHERE id = ?",
                    (row["id"],),
                )

    logger.info("Downloaded %d/%d clips for theme '%s'", downloaded, len(to_download), theme.name)


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


def render_video_for_theme(theme_name: str, reactions: dict[str, str]) -> Path:
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
        ranked_clips = [dict(row) for row in rows]

        for clip_id, reaction in reactions.items():
            set_clip_reaction(conn, clip_id, reaction)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    work_dir = RENDERS_DIR / theme.name / f"work_{timestamp}"
    output_path = RENDERS_DIR / theme.name / f"{timestamp}.mp4"

    render_video(theme.on_screen_label, ranked_clips, reactions, work_dir, output_path)
    logger.info("Rendered video for theme '%s' at %s", theme.name, output_path)
    return output_path


def upload_rendered_video(
    theme_name: str,
    video_path: Path,
    title: str,
    description: str,
    tags: list[str] | None = None,
    privacy_status: str | None = None,
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
    )

    with get_connection() as conn:
        rows = get_selected_clips(conn, theme.name)
        clip_ids = [row["id"] for row in rows]
        record_video(conn, theme.name, title, video_id, str(video_path), clip_ids)
        for clip_id in clip_ids:
            mark_clip_status(conn, clip_id, "published")

    logger.info("Published video for theme '%s': https://youtube.com/watch?v=%s", theme.name, video_id)
    return video_id
