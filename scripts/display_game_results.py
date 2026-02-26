"""Display game-by-game results from analysis_data.json.

Usage:
    python scripts/display_game_results.py
"""

import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analyzer_lib import config

ANALYSIS_DATA_PATH = os.path.join(config.DATA_DIR, "analysis_data.json")


def display_game_by_game_results():
    if not os.path.isfile(ANALYSIS_DATA_PATH):
        print(f"Error: {ANALYSIS_DATA_PATH} not found. Run main.py first.")
        return

    with open(ANALYSIS_DATA_PATH, "r") as f:
        data = json.load(f)

    games = data.get("game_results", [])
    if not games:
        print("No game results found.")
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
