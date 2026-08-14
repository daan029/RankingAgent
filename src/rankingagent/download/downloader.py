from __future__ import annotations

import logging
from pathlib import Path

import yt_dlp

logger = logging.getLogger(__name__)


def download_clip(source_url: str, clip_id: str, dest_dir: Path, no_check_certificate: bool = False) -> Path | None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(dest_dir / f"{clip_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,
        "format": "mp4/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": no_check_certificate,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(source_url, download=True)
            filepath = ydl.prepare_filename(info)
            path = Path(filepath)
            if path.suffix != ".mp4":
                path = path.with_suffix(".mp4")
            return path if path.exists() else None
    except Exception:
        logger.exception("Failed to download clip %s from %s", clip_id, source_url)
        return None


def fetch_metadata(source_url: str, no_check_certificate: bool = False) -> dict | None:
    """Pull post metadata (title, uploader, like_count, comment_count, ...)
    via yt-dlp without downloading the video — works anonymously, no Reddit
    API access needed. Used by discovery.manual for the API-approval-pending
    fallback."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "nocheckcertificate": no_check_certificate,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(source_url, download=False)
    except Exception:
        logger.exception("Failed to fetch metadata for %s", source_url)
        return None
