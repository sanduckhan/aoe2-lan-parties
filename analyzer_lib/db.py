"""Shared SQLite database module for all application data.

Provides functions to read/write player ratings, rating history,
LAN events, and analysis cache data. The games table is managed
by GameRegistry in server/processing.py, but shares the same database file.
"""

import json
import logging
import os
import sqlite3

from analyzer_lib import config

logger = logging.getLogger(__name__)

DB_FILENAME = "aoe2_data.db"

_SCHEMA_SQL = """
-- ============ SOURCE OF TRUTH ============

CREATE TABLE IF NOT EXISTS games (
    sha256              TEXT PRIMARY KEY,
    fingerprint         TEXT,
    status              TEXT NOT NULL,
    filename            TEXT,
    datetime            TEXT,
    duration_seconds    REAL DEFAULT 0,
    winning_team_id     TEXT,
    source_path         TEXT,
    uploaded_at         TEXT,
    teams               TEXT NOT NULL DEFAULT '{}',
    player_deltas       TEXT NOT NULL DEFAULT '{}',
    game_level_deltas   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ============ DERIVED: RATINGS ============

CREATE TABLE IF NOT EXISTS player_ratings (
    name                    TEXT PRIMARY KEY,
    mu_scaled               REAL,
    sigma_scaled            REAL,
    mu_unscaled             REAL,
    sigma_unscaled          REAL,
    games_played            INTEGER,
    games_rated             INTEGER,
    confidence_percent      REAL,
    avg_handicap_last_30    REAL
);

-- ============ DERIVED: RATING HISTORY ============

CREATE TABLE IF NOT EXISTS rating_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_index      INTEGER NOT NULL,
    player_name     TEXT NOT NULL,
    mu              REAL NOT NULL,
    sigma           REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS lan_events (
    start_date          TEXT PRIMARY KEY,
    end_date            TEXT,
    label               TEXT,
    num_games           INTEGER,
    game_index_start    INTEGER,
    game_index_end      INTEGER
);

-- ============ DERIVED: ANALYSIS CACHE ============

CREATE TABLE IF NOT EXISTS analysis_cache (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

-- ============ INDEXES ============

CREATE INDEX IF NOT EXISTS idx_games_fingerprint ON games(fingerprint);
CREATE INDEX IF NOT EXISTS idx_games_status ON games(status);
CREATE INDEX IF NOT EXISTS idx_games_datetime ON games(datetime);
CREATE INDEX IF NOT EXISTS idx_games_status_datetime ON games(status, datetime);
CREATE INDEX IF NOT EXISTS idx_rating_history_player ON rating_history(player_name);
CREATE INDEX IF NOT EXISTS idx_rating_history_game ON rating_history(game_index);
"""


def get_db_path(data_dir=None):
    """Return path to the shared SQLite database."""
    return os.path.join(data_dir or config.DATA_DIR, DB_FILENAME)


def get_connection(db_path):
    """Open a WAL-mode connection with busy_timeout."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn):
    """Create all tables and indexes if they don't exist."""
    conn.executescript(_SCHEMA_SQL)


# --- Player Ratings ---


def save_player_ratings(db_path, ratings_list):
    """DELETE + INSERT all ratings in a transaction."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM player_ratings")
            conn.executemany(
                """INSERT INTO player_ratings
                   (name, mu_scaled, sigma_scaled, mu_unscaled, sigma_unscaled,
                    games_played, games_rated, confidence_percent, avg_handicap_last_30)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        r["name"],
                        r["mu_scaled"],
                        r["sigma_scaled"],
                        r["mu_unscaled"],
                        r["sigma_unscaled"],
                        r["games_played"],
                        r["games_rated"],
                        r["confidence_percent"],
                        r.get("avg_handicap_last_30", 100.0),
                    )
                    for r in ratings_list
                ],
            )
        logger.info(f"Saved {len(ratings_list)} player ratings to database")
    finally:
        conn.close()


def load_player_ratings(db_path):
    """SELECT * FROM player_ratings ORDER BY mu_scaled DESC."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM player_ratings ORDER BY mu_scaled DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Rating History ---


def save_rating_history(db_path, history, lan_events):
    """DELETE + INSERT all history rows and lan_events in a transaction."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM rating_history")
            conn.execute("DELETE FROM lan_events")

            conn.executemany(
                """INSERT INTO rating_history (game_index, player_name, mu, sigma)
                   VALUES (?, ?, ?, ?)""",
                [
                    (h["game_index"], h["player_name"], h["mu"], h["sigma"])
                    for h in history
                ],
            )

            conn.executemany(
                """INSERT INTO lan_events
                   (start_date, end_date, label, num_games, game_index_start, game_index_end)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        e["start_date"],
                        e["end_date"],
                        e["label"],
                        e["num_games"],
                        e.get("game_index_start"),
                        e.get("game_index_end"),
                    )
                    for e in (lan_events or [])
                ],
            )
        logger.info(
            f"Saved {len(history)} rating history entries and "
            f"{len(lan_events or [])} LAN events to database"
        )
    finally:
        conn.close()


def load_rating_history(db_path):
    """Return {"history": [...], "lan_events": [...]}."""
    conn = get_connection(db_path)
    try:
        history_rows = conn.execute(
            "SELECT game_index, player_name, mu, sigma FROM rating_history ORDER BY id"
        ).fetchall()
        event_rows = conn.execute(
            "SELECT * FROM lan_events ORDER BY start_date"
        ).fetchall()
        return {
            "history": [dict(r) for r in history_rows],
            "lan_events": [dict(r) for r in event_rows],
        }
    finally:
        conn.close()


def load_lan_events(db_path):
    """SELECT * FROM lan_events ORDER BY start_date DESC."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM lan_events ORDER BY start_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Analysis Cache ---


def save_analysis_data(db_path, analysis_data):
    """Store awards, general_stats, game_results, player_profiles as JSON blobs."""
    conn = get_connection(db_path)
    try:
        with conn:
            for key in ("awards", "general_stats", "game_results", "player_profiles"):
                value = analysis_data.get(key)
                if value is not None:
                    conn.execute(
                        "INSERT OR REPLACE INTO analysis_cache (key, value) VALUES (?, ?)",
                        (key, json.dumps(value, default=str)),
                    )
        logger.info("Saved analysis data to database")
    finally:
        conn.close()


def load_analysis_cache(db_path, key):
    """Load a single analysis cache entry by key, JSON-decoded."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM analysis_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["value"])
    finally:
        conn.close()
