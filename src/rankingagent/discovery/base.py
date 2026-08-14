from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Clip:
    id: str
    theme: str
    platform: str
    source_url: str
    creator: str
    caption: str
    score: float
    num_comments: int = 0
    status: str = "discovered"

    def as_db_row(self) -> dict:
        return {
            "id": self.id,
            "theme": self.theme,
            "platform": self.platform,
            "source_url": self.source_url,
            "creator": self.creator,
            "caption": self.caption,
            "score": self.score,
            "num_comments": self.num_comments,
            "status": self.status,
        }


class DiscoverySource(Protocol):
    platform: str

    def discover(self, theme_name: str, subreddits: list[str], min_score: int, limit: int) -> list[Clip]:
        ...
