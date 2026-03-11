import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


INIT_SQL = """
CREATE TABLE IF NOT EXISTS users (
    telegram_user_id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tracked_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    steam_profile_url TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    auto_reports_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_match_id TEXT,
    last_sent_match_id TEXT,
    UNIQUE(telegram_user_id, player_id)
);

CREATE TABLE IF NOT EXISTS player_match_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    match_datetime TEXT NOT NULL,
    hero_name TEXT NOT NULL,
    is_win INTEGER NOT NULL,
    kills INTEGER NOT NULL,
    deaths INTEGER NOT NULL,
    assists INTEGER NOT NULL,
    souls INTEGER NOT NULL,
    damage INTEGER NOT NULL,
    raw_payload_json TEXT NOT NULL,
    UNIQUE(player_id, match_id)
);

CREATE TABLE IF NOT EXISTS matches_cache (
    match_id TEXT PRIMARY KEY,
    raw_payload_json TEXT NOT NULL,
    parsed_payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sent_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(telegram_user_id, player_id, match_id)
);
"""


class Database:
    def __init__(self, database_url: str):
        if not database_url.startswith("sqlite:///"):
            raise ValueError("Для MVP поддерживается только SQLite: sqlite:///path/to/db")
        self.db_path = Path(database_url.replace("sqlite:///", "", 1))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connection() as conn:
            conn.executescript(INIT_SQL)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(tracked_players)").fetchall()}
            if "steam_profile_url" not in columns:
                conn.execute("ALTER TABLE tracked_players ADD COLUMN steam_profile_url TEXT")
