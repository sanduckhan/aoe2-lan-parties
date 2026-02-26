#!/usr/bin/env python3
"""One-time migration: convert all JSON data files to SQLite.

Reads game_registry.json, player_ratings.json, rating_history.json,
and analysis_data.json, then populates aoe2_data.db with all data.

Does NOT delete JSON files (kept as backup).
"""

import json
import logging
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from analyzer_lib import config, db

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main():
    data_dir = config.DATA_DIR
    db_path = db.get_db_path(data_dir)

    if os.path.exists(db_path):
        print(f"Database already exists: {db_path}")
        print("Delete it manually if you want to re-migrate.")
        return

    # --- Paths ---
    registry_path = os.path.join(data_dir, "game_registry.json")
    ratings_path = os.path.join(data_dir, "player_ratings.json")
    history_path = os.path.join(data_dir, "rating_history.json")
    analysis_path = os.path.join(data_dir, "analysis_data.json")

    # --- Create database and schema ---
    conn = db.get_connection(db_path)
    db.init_schema(conn)
    print(f"Created database: {db_path}")

    # --- 1. Migrate game_registry.json ---
    games_count = 0
    if os.path.exists(registry_path):
        with open(registry_path, "r") as f:
            registry_data = json.load(f)

        games = registry_data.get("games", [])
        games_count = len(games)

        from server.processing import _entry_to_row, _GAME_INSERT_SQL

        with conn:
            conn.executemany(_GAME_INSERT_SQL, [_entry_to_row(g) for g in games])
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("total_processed", str(registry_data.get("total_processed", 0))),
            )
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("last_updated", registry_data.get("last_updated", "")),
            )

        actual = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        print(f"  game_registry.json: {games_count} games -> {actual} rows")
        if actual != games_count:
            print(f"  WARNING: row count mismatch ({actual} != {games_count})")
    else:
        print(f"  game_registry.json: not found, skipping")

    # --- 2. Migrate player_ratings.json ---
    ratings_count = 0
    if os.path.exists(ratings_path):
        with open(ratings_path, "r") as f:
            ratings_list = json.load(f)
        ratings_count = len(ratings_list)

        with conn:
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
        actual = conn.execute("SELECT COUNT(*) FROM player_ratings").fetchone()[0]
        print(f"  player_ratings.json: {ratings_count} players -> {actual} rows")
    else:
        print(f"  player_ratings.json: not found, skipping")

    # --- 3. Migrate rating_history.json ---
    history_count = 0
    events_count = 0
    if os.path.exists(history_path):
        with open(history_path, "r") as f:
            history_data = json.load(f)

        # Handle both old format (flat list) and new format (dict)
        if isinstance(history_data, list):
            history = history_data
            lan_events = []
        else:
            history = history_data.get("history", [])
            lan_events = history_data.get("lan_events", [])

        history_count = len(history)
        events_count = len(lan_events)

        with conn:
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
                    for e in lan_events
                ],
            )
        actual_history = conn.execute("SELECT COUNT(*) FROM rating_history").fetchone()[
            0
        ]
        actual_events = conn.execute("SELECT COUNT(*) FROM lan_events").fetchone()[0]
        print(
            f"  rating_history.json: {history_count} entries -> {actual_history} rows, {events_count} events -> {actual_events} rows"
        )
    else:
        print(f"  rating_history.json: not found, skipping")

    # --- 4. Migrate analysis_data.json ---
    if os.path.exists(analysis_path):
        with open(analysis_path, "r") as f:
            analysis_data = json.load(f)

        keys_migrated = []
        with conn:
            for key in ("awards", "general_stats", "game_results", "player_profiles"):
                value = analysis_data.get(key)
                if value is not None:
                    conn.execute(
                        "INSERT OR REPLACE INTO analysis_cache (key, value) VALUES (?, ?)",
                        (key, json.dumps(value, default=str)),
                    )
                    keys_migrated.append(key)
        print(f"  analysis_data.json: migrated keys: {', '.join(keys_migrated)}")
    else:
        print(f"  analysis_data.json: not found, skipping")

    conn.close()

    print(f"\nMigration complete!")
    print(f"  Database: {db_path}")
    print(f"  Games: {games_count}")
    print(f"  Player ratings: {ratings_count}")
    print(f"  Rating history: {history_count} entries, {events_count} LAN events")
    print(f"\nJSON files have been preserved as backup.")


if __name__ == "__main__":
    main()
