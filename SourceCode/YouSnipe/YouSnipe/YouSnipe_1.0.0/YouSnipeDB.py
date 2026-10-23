from __future__ import annotations

import sqlite3
import os
from contextlib import contextmanager, closing
from pathlib import Path

from YouSnipePaths import appdata_subdirectory
DB_DIR = appdata_subdirectory("Database")
DB_PATH = DB_DIR / "YouSnipe.db"

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uuid TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    source_url TEXT,
    playlist_id TEXT,
    playlist_title TEXT,
    custom_name TEXT,
    target_media_mode TEXT NOT NULL,
    target_format TEXT NOT NULL,
    target_quality TEXT,
    save_path TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    failed_at TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    total_items INTEGER NOT NULL DEFAULT 1,
    selected_items INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS download_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_uuid TEXT NOT NULL UNIQUE,
    job_id INTEGER NOT NULL,
    item_index INTEGER,
    title TEXT,
    webpage_url TEXT,
    extractor_id TEXT,
    duration_seconds REAL,
    status TEXT NOT NULL,
    progress_percent REAL,
    downloaded_bytes INTEGER,
    total_bytes INTEGER,
    speed_bytes_per_second REAL,
    eta_seconds REAL,
    file_path TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    failed_at TEXT,
    error_message TEXT,
    raw_metadata_json TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_items_status ON download_items(status);
CREATE INDEX IF NOT EXISTS idx_items_job_id ON download_items(job_id);

CREATE TABLE IF NOT EXISTS usage_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time TEXT NOT NULL,
    item_id INTEGER,
    bytes_transferred INTEGER NOT NULL,
    source TEXT NOT NULL,
    FOREIGN KEY(item_id) REFERENCES download_items(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_event_time ON usage_ledger(event_time);

CREATE TABLE IF NOT EXISTS data_cap_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled_last_seen INTEGER NOT NULL DEFAULT 0,
    cycle_started_at TEXT,
    bytes_used INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
"""


def ensure_database() -> Path:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.executescript(SCHEMA_SQL)
        job_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        item_columns = {row[1] for row in conn.execute("PRAGMA table_info(download_items)")}
        for column, statement in {
            "error_code": "ALTER TABLE jobs ADD COLUMN error_code TEXT",
            "cancelled_at": "ALTER TABLE jobs ADD COLUMN cancelled_at TEXT",
        }.items():
            if column not in job_columns:
                conn.execute(statement)
        for column, statement in {
            "stage": "ALTER TABLE download_items ADD COLUMN stage TEXT",
            "error_code": "ALTER TABLE download_items ADD COLUMN error_code TEXT",
            "cancelled_at": "ALTER TABLE download_items ADD COLUMN cancelled_at TEXT",
            "retry_count": "ALTER TABLE download_items ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
        }.items():
            if column not in item_columns:
                conn.execute(statement)
        conn.execute("INSERT OR IGNORE INTO data_cap_state (id, enabled_last_seen, bytes_used) VALUES (1, 0, 0)")
        conn.execute(
            """
            INSERT INTO schema_meta (key, value)
            VALUES ('schema_version', '2')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )
        conn.commit()
    return DB_PATH


@contextmanager
def get_connection():
    
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
