# main.py - Main entry point for the AoE2 LAN Party Analyzer

import logging
import os
import sys

from analyzer_lib import config, db
from analyzer_lib.registry_builder import sync_registry_from_disk
from analyzer_lib.registry_stats import accumulate_stats_from_games
from analyzer_lib.report_generator import (
    print_report,
    compute_all_awards,
    compute_general_stats,
    compute_player_profiles,
)

# Allow importing from scripts/ and server/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
from calculate_trueskill import run_trueskill_from_registry

from server.processing import GameRegistry

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main():
    """
    Main function to run the AoE2 LAN Party Analyzer.
    Uses a registry-first approach: only parses new replays, then
    rebuilds stats and ratings from the cached registry.
    """
    print("--- Starting AoE2 LAN Party Analyzer ---")

    # Step 1: Load or create registry, sync from local replay files
    registry = GameRegistry(data_dir=config.DATA_DIR)
    sync_result = sync_registry_from_disk(registry)
    print(f"Registry sync: {sync_result}")

    # Step 2: Get all analysis-eligible games from registry
    all_games = registry.get_all_data()["games"]
    analysis_games = [
        g for g in all_games if g.get("status") in ("processed", "no_winner")
    ]
    analysis_games.sort(key=lambda g: g.get("datetime", ""))

    if not analysis_games:
        print("No valid games found. Exiting.")
        return

    print(f"--- Rebuilding stats from {len(analysis_games)} games ---")

    # Step 3: Run TrueSkill first (to get per-game rating deltas)
    ratable_games = registry.get_games(status=["processed", "no_winner"])
    _, _, _, rating_deltas = run_trueskill_from_registry(
        ratable_games, data_dir=config.DATA_DIR
    )

    # Step 4: Accumulate stats from registry (no replay parsing)
    player_stats, game_stats, game_results, head_to_head = accumulate_stats_from_games(
        analysis_games
    )

    # Step 5: Merge rating deltas into game_results
    for gr in game_results:
        sha = gr.get("sha256")
        if sha and sha in rating_deltas:
            gr["rating_changes"] = rating_deltas[sha]

    # Step 6: Print CLI report
    print_report(player_stats, game_stats)

    # Step 7: Save analysis data to SQLite
    analysis_data = {
        "awards": compute_all_awards(player_stats, game_stats),
        "general_stats": compute_general_stats(game_stats),
        "game_results": game_results,
        "player_profiles": compute_player_profiles(player_stats, head_to_head),
    }

    db_path = db.get_db_path(config.DATA_DIR)
    db.save_analysis_data(db_path, analysis_data)
    print(f"Analysis data saved to {db_path}")

    print("--- AoE2 LAN Party Analyzer Finished ---")


if __name__ == "__main__":
    main()
