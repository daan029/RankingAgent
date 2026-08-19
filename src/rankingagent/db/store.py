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
        # Migration for databases created before has_audio existed —
        # CREATE TABLE IF NOT EXISTS above doesn't add columns to an
        # already-existing table.
        try:
            conn.execute("ALTER TABLE clips ADD COLUMN has_audio INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE clips ADD COLUMN duration_seconds REAL")
        except sqlite3.OperationalError:
            pass


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
        INSERT INTO clips (id, theme, platform, source_url, creator, caption, score, num_comments, status, duration_seconds)
        VALUES (:id, :theme, :platform, :source_url, :creator, :caption, :score, :num_comments, :status, :duration_seconds)
        ON CONFLICT(source_url) DO UPDATE SET
            score = excluded.score,
            num_comments = excluded.num_comments,
            duration_seconds = excluded.duration_seconds,
            updated_at = datetime('now')
        """,
        clip,
    )


def mark_clip_downloaded(conn: sqlite3.Connection, clip_id: str, local_path: str) -> None:
    conn.execute(
        "UPDATE clips SET local_path = ?, status = 'downloaded', updated_at = datetime('now') WHERE id = ?",
        (local_path, clip_id),
    )


def mark_clip_audio(conn: sqlite3.Connection, clip_id: str, has_audio: bool) -> None:
    conn.execute(
        "UPDATE clips SET has_audio = ?, updated_at = datetime('now') WHERE id = ?",
        (1 if has_audio else 0, clip_id),
    )


def mark_clip_duration(conn: sqlite3.Connection, clip_id: str, duration_seconds: float) -> None:
    conn.execute(
        "UPDATE clips SET duration_seconds = ?, updated_at = datetime('now') WHERE id = ?",
        (duration_seconds, clip_id),
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


def get_all_source_urls(conn: sqlite3.Connection) -> set[str]:
    """Every source_url ever discovered (any theme, any status) — used to
    skip already-seen posts up front during a fresh discovery run, so a
    part-2 video never re-checks (or re-selects) a clip a previous video
    already used. Global, not per-theme: a clip used for one theme shouldn't
    resurface in another either."""
    rows = conn.execute("SELECT source_url FROM clips").fetchall()
    return {row["source_url"] for row in rows}


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
