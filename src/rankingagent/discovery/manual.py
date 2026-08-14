from __future__ import annotations

import hashlib
import logging

from rankingagent.discovery.base import Clip
from rankingagent.download.downloader import fetch_metadata

logger = logging.getLogger(__name__)


class ManualDiscoverySource:
    """Fallback discovery for while Reddit API access is pending approval
    (see the reddit-api-blocker memory entry): the user browses Reddit
    themselves and supplies a list of post URLs. Metadata (title, uploader,
    score, comment count) is pulled via yt-dlp, which works anonymously and
    doesn't need PRAW/API credentials at all."""

    platform = "reddit"

    def __init__(self, no_check_certificate: bool = False):
        self.no_check_certificate = no_check_certificate

    def discover_from_urls(self, theme_name: str, urls: list[str]) -> list[Clip]:
        clips: list[Clip] = []
        for url in urls:
            url = url.strip()
            if not url:
                continue

            info = fetch_metadata(url, no_check_certificate=self.no_check_certificate)
            if info is None:
                logger.warning("Skipping %s — metadata fetch failed", url)
                continue

            clip_id = "reddit_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
            clips.append(
                Clip(
                    id=clip_id,
                    theme=theme_name,
                    platform=self.platform,
                    source_url=info.get("webpage_url", url),
                    creator=info.get("uploader") or "unknown",
                    caption=info.get("title") or "",
                    score=float(info.get("like_count") or 0),
                    num_comments=int(info.get("comment_count") or 0),
                )
            )
        return clips
