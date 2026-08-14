from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from rankingagent.config import DB_PATH

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


@contextmanager
def get_connection(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_clip(conn: sqlite3.Connection, clip: dict) -> None:
    conn.execute(
        """
        INSERT INTO clips (id, theme, platform, source_url, creator, caption, score, num_comments, status)
        VALUES (:id, :theme, :platform, :source_url, :creator, :caption, :score, :num_comments, :status)
        ON CONFLICT(source_url) DO UPDATE SET
            score = excluded.score,
            num_comments = excluded.num_comments,
            updated_at = datetime('now')
        """,
        clip,
    )


def mark_clip_downloaded(conn: sqlite3.Connection, clip_id: str, local_path: str) -> None:
    conn.execute(
        "UPDATE clips SET local_path = ?, status = 'downloaded', updated_at = datetime('now') WHERE id = ?",
        (local_path, clip_id),
    )


def mark_clip_status(conn: sqlite3.Connection, clip_id: str, status: str) -> None:
    conn.execute(
        "UPDATE clips SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, clip_id),
    )


def get_clips_by_status(conn: sqlite3.Connection, theme: str, status: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clips WHERE theme = ? AND status = ? ORDER BY score DESC",
        (theme, status),
    ).fetchall()


def set_clip_rank(conn: sqlite3.Connection, clip_id: str, rank: int, reveal_index: int) -> None:
    conn.execute(
        "UPDATE clips SET rank = ?, reveal_index = ?, updated_at = datetime('now') WHERE id = ?",
        (rank, reveal_index, clip_id),
    )


def get_selected_clips(conn: sqlite3.Connection, theme: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clips WHERE theme = ? AND status = 'selected' ORDER BY reveal_index ASC",
        (theme,),
    ).fetchall()


def set_clip_reaction(conn: sqlite3.Connection, clip_id: str, reaction: str) -> None:
    conn.execute(
        "UPDATE clips SET reaction = ?, updated_at = datetime('now') WHERE id = ?",
        (reaction, clip_id),
    )


def is_known_source_url(conn: sqlite3.Connection, source_url: str) -> bool:
    row = conn.execute("SELECT 1 FROM clips WHERE source_url = ?", (source_url,)).fetchone()
    return row is not None


def record_video(
    conn: sqlite3.Connection,
    theme: str,
    title: str,
    youtube_video_id: str,
    local_path: str,
    clip_ids: list[str],
) -> None:
    conn.execute(
        """
        INSERT INTO videos (theme, title, youtube_video_id, local_path, clip_ids, published_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        """,
        (theme, title, youtube_video_id, local_path, json.dumps(clip_ids)),
    )


def get_video_history(conn: sqlite3.Connection, theme: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM videos WHERE theme = ? ORDER BY created_at DESC",
        (theme,),
    ).fetchall()
