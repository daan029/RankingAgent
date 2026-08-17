from __future__ import annotations

import json
import random
import sqlite3

from rankingagent.db.store import set_clip_rank


def get_used_clip_ids(conn: sqlite3.Connection) -> set[str]:
    used: set[str] = set()
    for row in conn.execute("SELECT clip_ids FROM videos"):
        try:
            used.update(json.loads(row["clip_ids"]))
        except (TypeError, ValueError):
            continue
    return used


def select_and_rank(conn: sqlite3.Connection, theme_name: str, count: int = 5) -> list[dict]:
    used_ids = get_used_clip_ids(conn)

    candidates = conn.execute(
        "SELECT * FROM clips WHERE theme = ? AND status = 'downloaded' ORDER BY score DESC",
        (theme_name,),
    ).fetchall()

    eligible = [row for row in candidates if row["id"] not in used_ids]

    # At most one clip without audio per rendered video (see
    # editing.clip_processor.normalize_clip — a silent clip gets piano.mp3
    # mixed in as a fallback, and using that fallback twice in the same
    # video would be repetitive). has_audio is NULL for rows probed before
    # this column existed, or if the ffprobe check itself failed; treat
    # those as "has audio" rather than blocking selection on missing data.
    top: list[sqlite3.Row] = []
    silent_already_selected = False
    for row in eligible:
        if len(top) >= count:
            break
        is_silent = row["has_audio"] == 0
        if is_silent and silent_already_selected:
            continue
        top.append(row)
        if is_silent:
            silent_already_selected = True

    if not top:
        return []

    # rank 1 = highest score (climax), rank `count` = lowest of the selected set
    ranked = [dict(row, rank=i + 1) for i, row in enumerate(top)]

    # reveal order: rank 1 (climax) always last, the rest shuffled
    climax = next(c for c in ranked if c["rank"] == 1)
    rest = [c for c in ranked if c["rank"] != 1]
    random.shuffle(rest)
    reveal_sequence = rest + [climax]

    for idx, clip in enumerate(reveal_sequence):
        clip["reveal_index"] = idx

    for clip in ranked:
        conn.execute(
            "UPDATE clips SET status = 'selected', updated_at = datetime('now') WHERE id = ?",
            (clip["id"],),
        )
        set_clip_rank(conn, clip["id"], clip["rank"], clip["reveal_index"])

    return sorted(ranked, key=lambda c: c["reveal_index"])
