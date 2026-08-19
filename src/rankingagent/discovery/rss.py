from __future__ import annotations

import hashlib
import logging
import ssl
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from rankingagent.discovery.base import Clip
from rankingagent.download.downloader import fetch_metadata

logger = logging.getLogger(__name__)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RankingAgent/0.1"


def _normalize_url(url: str) -> str:
    """Strip query string and trailing slash so a permalink from a fresh RSS
    entry can be compared against a stored `source_url` (yt-dlp's resolved
    `webpage_url`) even when they differ in exactly those cosmetic ways."""
    return url.split("?", 1)[0].rstrip("/")


def _post_id_from_permalink(permalink: str) -> str | None:
    """Extract Reddit's `t3_<id>` fullname from a `/comments/<id>/...`
    permalink, for use as the search.rss pagination cursor (`after=`)."""
    parts = [p for p in permalink.split("/") if p]
    if "comments" not in parts:
        return None
    idx = parts.index("comments")
    if idx + 1 >= len(parts):
        return None
    return "t3_" + parts[idx + 1]


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
        max_candidates_per_search: int = 100,
    ):
        self.no_check_certificate = no_check_certificate
        self.request_delay_seconds = request_delay_seconds
        self.max_candidates_per_subreddit = max_candidates_per_subreddit
        # Safety cap, not a normal target (raised 15->100, 2026-08-19) —
        # discover_search now keeps paginating a query until it hits its
        # share of the overall clip target, so this only exists to stop a
        # single query from looping forever if it never runs dry and never
        # yields enough valid clips either.
        self.max_candidates_per_search = max_candidates_per_search
        self._ssl_context = None
        if no_check_certificate:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._ssl_context = ctx

    def _fetch(self, url: str, label: str) -> bytes | None:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        for attempt in range(4):
            try:
                return urllib.request.urlopen(req, timeout=15, context=self._ssl_context).read()
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    wait = self.request_delay_seconds * (attempt + 1)
                    logger.info("Rate limited fetching %s feed, waiting %.0fs", label, wait)
                    time.sleep(wait)
                    continue
                logger.warning("Failed to fetch %s RSS feed: %s", label, e)
                return None
            except Exception:
                logger.exception("Failed to fetch %s RSS feed", label)
                return None
        return None

    def _fetch_feed(self, subreddit: str, time_filter: str) -> bytes | None:
        url = f"https://www.reddit.com/r/{subreddit}/top/.rss?t={time_filter}"
        return self._fetch(url, f"r/{subreddit}")

    def _fetch_search(self, query: str, time_filter: str, exact_phrase: bool = True, after: str | None = None) -> bytes | None:
        # site-wide search (not scoped to any subreddit) — lets a theme be
        # sourced by keyword/concept instead of a fixed subreddit list.
        # type=link excludes subreddit/user hits (search otherwise mixes
        # them in); wrapping the query in quotes makes it a phrase match —
        # without it, unquoted multi-word queries drift into loosely
        # related/irrelevant posts (confirmed 2026-08-18: unquoted "instant
        # karma caught on camera" surfaced an unrelated cat-collar PSA post).
        # sort=relevance, NOT sort=top (bug fixed 2026-08-19): a live check
        # of "worst tackle" with sort=top&t=all returned almost entirely
        # highest-scored *discussion*/megathread posts across Reddit history
        # ("TJ CLEMMINGS IS TERRIBLE MEGATHREAD", reaction articles) — a
        # phrase match ranked by score, not by how well it matches the
        # query, surfaces whatever's most-upvoted among the matches, which
        # for a phrase like this is dominated by text threads, not the
        # actual video clips. sort=relevance (already noted as the correct
        # choice in a 2026-08-18 investigation but never wired in) ranks by
        # match quality instead and returns genuine on-topic video posts.
        # `exact_phrase=False` (per-theme opt-out) drops the quoting for a
        # scarce theme where the literal phrase is too narrow — trades
        # precision for recall; downstream yt-dlp/min_score filtering still
        # rejects whatever doesn't pan out, so the only cost of the extra
        # breadth is more paced requests, not wrong results.
        from urllib.parse import quote

        q = ('"' + query + '"') if exact_phrase else query
        url = f"https://www.reddit.com/search.rss?q={quote(q)}&sort=relevance&t={time_filter}&type=link"
        # `after=t3_<post_id>` pages past Reddit's ~25-result-per-request cap
        # on this endpoint (confirmed live 2026-08-19 — page 2 returned 25
        # entirely new entries, no overlap with page 1). Not exposed by the
        # RSS spec itself; Reddit's RSS backend happens to honor the same
        # `after` cursor its JSON API uses.
        if after:
            url += f"&after={after}"
        return self._fetch(url, f'search "{query}"' + (f" (after {after})" if after else ""))

    def _parse_entries(self, body: bytes) -> list[tuple[str, str, str, datetime | None]]:
        """Returns list of (title, permalink, author, published)."""
        root = ET.fromstring(body)
        results = []
        for entry in root.findall("atom:entry", ATOM_NS):
            title_el = entry.find("atom:title", ATOM_NS)
            link_el = entry.find("atom:link", ATOM_NS)
            author_el = entry.find("atom:author/atom:name", ATOM_NS)
            published_el = entry.find("atom:published", ATOM_NS)
            if title_el is None or link_el is None:
                continue
            permalink = link_el.attrib.get("href", "")
            author = (author_el.text or "unknown").lstrip("/u/") if author_el is not None else "unknown"
            published = None
            if published_el is not None and published_el.text:
                try:
                    published = datetime.fromisoformat(published_el.text)
                except ValueError:
                    published = None
            results.append((title_el.text or "", permalink, author, published))
        return results

    def _entries_to_clips(
        self,
        theme_name: str,
        label: str,
        entries: list[tuple[str, str, str, datetime | None]],
        min_score: int,
        known_urls: set[str] | None = None,
    ) -> list[Clip]:
        clips: list[Clip] = []
        for entry_idx, (title, permalink, author, _published) in enumerate(entries, start=1):
            if known_urls and _normalize_url(permalink) in known_urls:
                # Already discovered/used in a past run (any theme, any
                # video) — skip before spending a paced metadata request on
                # it. Doesn't need a sleep since nothing was fetched.
                logger.info("%s: candidate %d/%d already used previously, skipping", label, entry_idx, len(entries))
                continue

            time.sleep(self.request_delay_seconds)
            # Every other branch below (non-video, below min_score) skips
            # silently — without a log line here, a run can go minutes
            # with zero output during the pacing sleeps, which external
            # process monitors can mistake for a hung/stalled process.
            logger.info("%s: fetching metadata for candidate %d/%d", label, entry_idx, len(entries))
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
        return clips

    def discover(
        self,
        theme_name: str,
        subreddits: list[str],
        min_score: int,
        limit: int,
        time_filter: str = "week",
        known_urls: set[str] | None = None,
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
            clips.extend(self._entries_to_clips(theme_name, f"r/{subreddit}", entries, min_score, known_urls))

        clips.sort(key=lambda c: c.score, reverse=True)
        return clips[:limit]

    def discover_search(
        self,
        theme_name: str,
        queries: list[str],
        min_score: int,
        limit: int,
        time_filter: str = "week",
        max_age_days: int | None = None,
        known_urls: set[str] | None = None,
        exact_phrase: bool = True,
        search_pages: int = 1,
    ) -> list[Clip]:
        """Site-wide discovery via Reddit's public search RSS — not scoped to
        any subreddit, so a theme can be sourced by keyword/concept instead
        of a fixed subreddit list. `max_age_days`, when set, drops entries
        older than that — a client-side filter because Reddit's search `t=`
        param only offers coarse buckets (week/month/year/all), no arbitrary
        window like "6 months" (2026-08-18 user request).

        Keeps paginating each query (via the `after=t3_<id>` cursor —
        confirmed working live 2026-08-19, a real query's page 2 returned 25
        entirely new posts) until the running total of *valid* clips across
        all queries reaches `limit`, rather than stopping after a fixed page
        count regardless of yield (2026-08-19 user request: "gewoon
        doorgaan tot ie 5 goede heeft" — a low per-candidate hit rate, e.g.
        most search results being non-video posts, used to silently cap
        yield well below what a theme needed). Two safety caps prevent an
        unbounded loop on a query that never runs dry: `search_pages`
        (pages per query) and `max_candidates_per_search` (total candidates
        checked per query) — both generous defaults, not normal targets.
        """
        clips: list[Clip] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days) if max_age_days else None

        for qi, query in enumerate(queries):
            if len(clips) >= limit:
                logger.info(
                    "Already have %d/%d target clips — skipping remaining queries %s",
                    len(clips), limit, queries[qi:],
                )
                break
            if qi > 0:
                time.sleep(self.request_delay_seconds)

            label = f'search "{query}"'
            after: str | None = None
            checked_this_query = 0
            for page in range(search_pages):
                if page > 0:
                    time.sleep(self.request_delay_seconds)
                body = self._fetch_search(query, time_filter=time_filter, exact_phrase=exact_phrase, after=after)
                if body is None:
                    break
                raw_entries = self._parse_entries(body)
                if not raw_entries:
                    logger.info('%s: page %d empty — no more results', label, page + 1)
                    break
                after = _post_id_from_permalink(raw_entries[-1][1])

                page_entries = raw_entries
                if cutoff is not None:
                    page_entries = [e for e in page_entries if e[3] is not None and e[3] >= cutoff]
                remaining = min(len(page_entries), self.max_candidates_per_search - checked_this_query)
                page_entries = page_entries[:remaining]
                checked_this_query += len(page_entries)

                logger.info('%s: page %d, %d candidate posts to check', label, page + 1, len(page_entries))
                new_clips = self._entries_to_clips(
                    theme_name, f"{label} p{page + 1}", page_entries, min_score, known_urls
                )
                clips.extend(new_clips)

                if len(clips) >= limit:
                    logger.info('%s: reached target (%d/%d clips) — moving on', label, len(clips), limit)
                    break
                if checked_this_query >= self.max_candidates_per_search:
                    logger.info(
                        '%s: hit the %d-candidate safety cap for this query, moving on',
                        label, self.max_candidates_per_search,
                    )
                    break
                if after is None:
                    break

        clips.sort(key=lambda c: c.score, reverse=True)
        return clips[:limit]
