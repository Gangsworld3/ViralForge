from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

_INITIALIZED: set[str] = set()


def connect_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def open_db(path: Path):
    conn = connect_db(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_state_db(path: Path) -> None:
    cache_key = str(path.resolve())
    if cache_key in _INITIALIZED:
        return
    with open_db(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_memory_items_kind_created
                ON memory_items(kind, id DESC);

            CREATE TABLE IF NOT EXISTS learning_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS analytics_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                views INTEGER NOT NULL DEFAULT 0,
                likes INTEGER NOT NULL DEFAULT 0,
                comments INTEGER NOT NULL DEFAULT 0,
                shares INTEGER NOT NULL DEFAULT 0,
                watch_time_seconds REAL NOT NULL DEFAULT 0,
                revenue REAL NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_analytics_content_platform
                ON analytics_records(content_id, platform);

            CREATE TABLE IF NOT EXISTS account_profiles (
                account_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                display_name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                api_mode TEXT NOT NULL DEFAULT 'dry_run',
                last_used TEXT,
                usage_count INTEGER NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_account_profiles_platform_active
                ON account_profiles(platform, active, usage_count, last_used);

            CREATE TABLE IF NOT EXISTS posting_records (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                retryable INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 0,
                retry_source TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_posting_records_platform_updated
                ON posting_records(platform, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_posting_records_retry_due
                ON posting_records(retryable, next_attempt_at, updated_at DESC);
            """
        )
    _INITIALIZED.add(cache_key)
