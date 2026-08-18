from __future__ import annotations

import hashlib
import logging
import ssl
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from rankingagent.discovery.base import Clip
from rankingagent.download.downloader import fetch_metadata

logger = logging.getLogger(__name__)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RankingAgent/0.1"


class RssDiscoverySource:
    """Discovery via a subreddit's public RSS feed (`/top/.rss`) — no Reddit
    API app/approval needed, unlike discovery.reddit.RedditDiscoverySource
    (see the reddit-api-blocker memory entry: the API application was
    denied). The RSS endpoint is unauthenticated but aggressively rate
    limited (~1 request per 20-30s before 429s start), so requests here are
    deliberately paced — this is slow by design, not a bug.

    Per-candidate score/comment-count metadata comes from a yt-dlp fetch
    (works anonymously), the same mechanism discovery.manual already uses.
    """

    platform = "reddit"

    def __init__(
        self,
        no_check_certificate: bool = False,
        request_delay_seconds: float = 25.0,
        max_candidates_per_subreddit: int = 30,
    ):
        self.no_check_certificate = no_check_certificate
        self.request_delay_seconds = request_delay_seconds
        self.max_candidates_per_subreddit = max_candidates_per_subreddit
        self._ssl_context = None
        if no_check_certificate:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._ssl_context = ctx

    def _fetch_feed(self, subreddit: str, time_filter: str) -> bytes | None:
        url = f"https://www.reddit.com/r/{subreddit}/top/.rss?t={time_filter}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        for attempt in range(4):
            try:
                return urllib.request.urlopen(req, timeout=15, context=self._ssl_context).read()
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    wait = self.request_delay_seconds * (attempt + 1)
                    logger.info("Rate limited fetching r/%s feed, waiting %.0fs", subreddit, wait)
                    time.sleep(wait)
                    continue
                logger.warning("Failed to fetch r/%s RSS feed: %s", subreddit, e)
                return None
            except Exception:
                logger.exception("Failed to fetch r/%s RSS feed", subreddit)
                return None
        return None

    def _parse_entries(self, body: bytes) -> list[tuple[str, str, str]]:
        """Returns list of (title, permalink, author)."""
        root = ET.fromstring(body)
        results = []
        for entry in root.findall("atom:entry", ATOM_NS):
            title_el = entry.find("atom:title", ATOM_NS)
            link_el = entry.find("atom:link", ATOM_NS)
            author_el = entry.find("atom:author/atom:name", ATOM_NS)
            if title_el is None or link_el is None:
                continue
            permalink = link_el.attrib.get("href", "")
            author = (author_el.text or "unknown").lstrip("/u/") if author_el is not None else "unknown"
            results.append((title_el.text or "", permalink, author))
        return results

    def discover(
        self, theme_name: str, subreddits: list[str], min_score: int, limit: int, time_filter: str = "week"
    ) -> list[Clip]:
        clips: list[Clip] = []

        for i, subreddit in enumerate(subreddits):
            if i > 0:
                time.sleep(self.request_delay_seconds)

            body = self._fetch_feed(subreddit, time_filter=time_filter)
            if body is None:
                continue

            entries = self._parse_entries(body)[: self.max_candidates_per_subreddit]
            logger.info("r/%s: %d candidate posts from RSS", subreddit, len(entries))

            for entry_idx, (title, permalink, author) in enumerate(entries, start=1):
                time.sleep(self.request_delay_seconds)
                # Every other branch below (non-video, below min_score) skips
                # silently — without a log line here, a run can go minutes
                # with zero output during the pacing sleeps, which external
                # process monitors can mistake for a hung/stalled process.
                logger.info("r/%s: fetching metadata for candidate %d/%d", subreddit, entry_idx, len(entries))
                info = fetch_metadata(permalink, no_check_certificate=self.no_check_certificate)
                if info is None:
                    # Not a video post (or fetch failed) — skip.
                    continue

                score = float(info.get("like_count") or 0)
                if score < min_score:
                    continue

                clips.append(
                    Clip(
                        id="reddit_rss_" + hashlib.sha1(permalink.encode("utf-8")).hexdigest()[:12],
                        theme=theme_name,
                        platform=self.platform,
                        source_url=info.get("webpage_url", permalink),
                        creator=info.get("uploader") or author,
                        caption=info.get("title") or title,
                        score=score,
                        num_comments=int(info.get("comment_count") or 0),
                        duration_seconds=float(info["duration"]) if info.get("duration") else None,
                    )
                )

        clips.sort(key=lambda c: c.score, reverse=True)
        return clips[:limit]
