from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
DOWNLOADS_DIR = DATA_DIR / "downloads"
RENDERS_DIR = DATA_DIR / "renders"
DB_PATH = DATA_DIR / "clips.db"

load_dotenv(ROOT_DIR / ".env")


@dataclass
class Theme:
    name: str
    on_screen_label: str
    subreddits: list[str]
    min_score: int
    clip_count: int
    title_template: str
    description_template: str
    # Reddit RSS "top" time window (hour/day/week/month/year/all). Themes
    # about a recurring but low-frequency event (e.g. a genuinely bad tackle)
    # need a wider window than "week" to find good matches at all — a
    # week-only scan can come back nearly empty some weeks even though
    # plenty of iconic clips exist across a longer span (2026-08-18).
    time_filter: str = "week"
    # If set, `discover-rss` sources this theme via Reddit's site-wide
    # search.rss (keyword/concept, not scoped to a subreddit) instead of the
    # fixed `subreddits` list — for themes whose narrative crosses many
    # subreddits (e.g. "karma" content lives in dozens of subs, not just
    # r/instantkarma) where pinning to a few subreddits under-fills the pool.
    search_queries: list[str] | None = None
    # Client-side age cutoff (days) applied on top of `time_filter` for
    # search-based discovery — Reddit's search `t=` param only offers coarse
    # buckets (week/month/year/all), no arbitrary window like "6 months".
    search_max_age_days: int | None = None
    # Per-theme override for ranking.scorer.MAX_RAW_CLIP_SECONDS (raw source
    # clip duration cap for eligibility) and editing.highlight.MAX_CLIP_
    # DURATION (final trimmed highlight-window cap). None means "use that
    # module's default". Some themes' raw footage structurally runs longer
    # before the actual moment than others — e.g. a doorbell-cam delivery
    # clip needs the driver to walk up, act, and leave, which a quick fail
    # clip doesn't (2026-08-19 user request for `worst_mailman`).
    max_raw_clip_seconds: float | None = None
    max_highlight_seconds: float | None = None
    # False disables the forced music bed under the opening (first-revealed)
    # segment regardless of has_audio_stream (see editing.assembler.
    # render_video) — the default (True) fixed a real "first clip sounds
    # silent" complaint for comedic content, but for a theme whose ambient
    # audio carries real narrative weight (e.g. a rescue's shouting/splashing)
    # a cheerful music bed underneath reads as tonally wrong instead
    # (2026-08-19 user feedback on `hero_moments`).
    force_opening_music: bool = True
    # Per-theme override for RssDiscoverySource's max_candidates_per_search
    # (default 100, a safety cap not a normal target) — total candidates
    # checked per query before giving up on it regardless of yield.
    max_search_candidates: int | None = None
    # How many ~25-result search.rss pages to walk per query via the
    # `after=` cursor, as a safety cap. Raised 1->6 (2026-08-19 user
    # request: "gewoon doorgaan tot ie 5 goede heeft" — a low per-candidate
    # hit rate used to silently cap yield at whatever the first page held,
    # regardless of how many more results existed). discover_search stops
    # pulling more pages as soon as the running clip total hits its target,
    # so this and max_search_candidates only matter as an upper bound for a
    # query that never runs dry and never yields enough either.
    search_pages: int = 6
    # False drops the exact-phrase quoting around each search query,
    # trading precision for recall — for a theme where even soccer-specific
    # phrasing still under-fills the candidate pool (2026-08-19).
    search_exact_phrase: bool = True


@dataclass
class Settings:
    reddit_client_id: str = field(default_factory=lambda: os.environ.get("REDDIT_CLIENT_ID", ""))
    reddit_client_secret: str = field(default_factory=lambda: os.environ.get("REDDIT_CLIENT_SECRET", ""))
    reddit_user_agent: str = field(
        default_factory=lambda: os.environ.get("REDDIT_USER_AGENT", "RankingAgent/0.1")
    )
    youtube_client_secrets_path: str = field(
        default_factory=lambda: os.environ.get("YOUTUBE_CLIENT_SECRETS_PATH", "")
    )
    youtube_privacy_status: str = field(
        default_factory=lambda: os.environ.get("YOUTUBE_PRIVACY_STATUS", "unlisted")
    )
    # Workaround for dev machines behind an SSL-inspecting corporate proxy,
    # where Python's cert verification fails even though the underlying
    # request is fine. Leave false on the real deployment (home) laptop.
    ytdlp_no_check_certificate: bool = field(
        default_factory=lambda: os.environ.get("YTDLP_NO_CHECK_CERTIFICATE", "false").lower() == "true"
    )
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))


def load_settings() -> Settings:
    return Settings()


def load_themes() -> dict[str, Theme]:
    themes_path = CONFIG_DIR / "themes.yaml"
    with open(themes_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    themes: dict[str, Theme] = {}
    for entry in raw["themes"]:
        theme = Theme(
            name=entry["name"],
            on_screen_label=entry.get("on_screen_label", entry["name"].replace("_", " ").title()),
            subreddits=entry["subreddits"],
            min_score=entry.get("min_score", 500),
            clip_count=entry.get("clip_count", 5),
            title_template=entry["title_template"],
            description_template=entry["description_template"],
            time_filter=entry.get("time_filter", "week"),
            search_queries=entry.get("search_queries"),
            search_max_age_days=entry.get("search_max_age_days"),
            max_raw_clip_seconds=entry.get("max_raw_clip_seconds"),
            max_highlight_seconds=entry.get("max_highlight_seconds"),
            force_opening_music=entry.get("force_opening_music", True),
            max_search_candidates=entry.get("max_search_candidates"),
            search_pages=entry.get("search_pages", 6),
            search_exact_phrase=entry.get("search_exact_phrase", True),
        )
        themes[theme.name] = theme
    return themes


def ensure_data_dirs() -> None:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
