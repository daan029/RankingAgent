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
        )
        themes[theme.name] = theme
    return themes


def ensure_data_dirs() -> None:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
