"""Display game-by-game results from the database.

Usage:
    python scripts/display_game_results.py
"""

import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analyzer_lib import config, db


def display_game_by_game_results():
    db_path = db.get_db_path(config.DATA_DIR)
    games = db.load_analysis_cache(db_path, "game_results")
    if not games:
        print("No game results found. Run main.py first.")
        return

    print(f"--- Game by Game Results ({len(games)} games) ---\n")

    for g in games:
        dt = g.get("datetime", "?")
        duration = str(timedelta(seconds=int(g.get("duration_seconds", 0))))
        winning_team_id = g.get("winning_team_id")

        print(f"--- {g.get('filename', '?')} ({dt}, {duration}) ---")

        if winning_team_id is None:
            print("  -> No winner determined.\n")
            continue

        for tid, players in g.get("teams", {}).items():
            is_winner = tid == winning_team_id
            label = "Winning Team" if is_winner else "Losing Team"
            print(f"  - {label}:")
            for p in players:
                status = "Won" if is_winner else "Lost"
                civ = p.get("civ", "Unknown")
                print(f"    - {p['name']} ({civ}) [{status}]")

        print("")


if __name__ == "__main__":
    display_game_by_game_results()
