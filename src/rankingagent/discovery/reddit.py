from __future__ import annotations

import logging

import praw

from rankingagent.config import Settings
from rankingagent.discovery.base import Clip

logger = logging.getLogger(__name__)

# Domains yt-dlp can reliably extract video from. Reddit's own v.redd.it
# posts are covered separately via submission.is_video.
KNOWN_VIDEO_DOMAINS = (
    "v.redd.it",
    "youtube.com",
    "youtu.be",
    "streamable.com",
    "gfycat.com",
    "redgifs.com",
    "clips.twitch.tv",
)


class RedditDiscoverySource:
    platform = "reddit"

    def __init__(self, settings: Settings, time_filter: str = "week", fetch_limit: int = 50):
        self._reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        self._reddit.read_only = True
        self.time_filter = time_filter
        self.fetch_limit = fetch_limit

    def _is_video_submission(self, submission) -> bool:
        if getattr(submission, "is_video", False):
            return True
        url = getattr(submission, "url", "") or ""
        return any(domain in url for domain in KNOWN_VIDEO_DOMAINS)

    def discover(self, theme_name: str, subreddits: list[str], min_score: int, limit: int) -> list[Clip]:
        clips: list[Clip] = []
        for subreddit_name in subreddits:
            subreddit = self._reddit.subreddit(subreddit_name)
            try:
                submissions = subreddit.top(time_filter=self.time_filter, limit=self.fetch_limit)
                for submission in submissions:
                    if submission.stickied:
                        continue
                    if submission.score < min_score:
                        continue
                    if not self._is_video_submission(submission):
                        continue

                    clips.append(
                        Clip(
                            id=f"reddit_{submission.id}",
                            theme=theme_name,
                            platform=self.platform,
                            source_url=submission.url,
                            creator=str(submission.author) if submission.author else "unknown",
                            caption=submission.title,
                            score=float(submission.score),
                            num_comments=submission.num_comments,
                        )
                    )
            except Exception:
                logger.exception("Failed to fetch submissions from r/%s", subreddit_name)

        clips.sort(key=lambda c: c.score, reverse=True)
        return clips[:limit]
