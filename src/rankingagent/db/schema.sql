CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    theme TEXT NOT NULL,
    platform TEXT NOT NULL,
    source_url TEXT NOT NULL UNIQUE,
    creator TEXT,
    caption TEXT,
    score REAL NOT NULL DEFAULT 0,
    num_comments INTEGER NOT NULL DEFAULT 0,
    local_path TEXT,
    has_audio INTEGER,
    rank INTEGER,
    reveal_index INTEGER,
    reaction TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_clips_theme_status ON clips (theme, status);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    theme TEXT NOT NULL,
    title TEXT,
    youtube_video_id TEXT,
    local_path TEXT NOT NULL,
    clip_ids TEXT NOT NULL,
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
