# main.py - Main entry point for the AoE2 LAN Party Analyzer

import json
import os
import sys

from analyzer_lib.replay_parser import parse_replays_parallel
from analyzer_lib.analyze_games import analyze_all_games
from analyzer_lib.report_generator import (
    print_report,
    compute_all_awards,
    compute_general_stats,
    compute_player_profiles,
)

# Allow importing from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
from calculate_trueskill import run_trueskill


def main():
    """
    Main function to run the AoE2 LAN Party Analyzer.
    Parses all replays once in parallel, then feeds them to both
    the analysis pipeline and TrueSkill calculation.
    """
    print("--- Starting AoE2 LAN Party Analyzer ---")

    # Parse all replays once (parallel), reuse for both analysis and TrueSkill
    parsed_matches = parse_replays_parallel()
    if not parsed_matches:
        print("No valid games found. Exiting.")
        return

    result = analyze_all_games(parsed_matches=parsed_matches)

    if result is None:
        print("Analysis could not be completed. Exiting.")
        return

    analyzed_player_stats, analyzed_game_stats, game_results, head_to_head = result

    # Generate and print the analytics report
    print_report(analyzed_player_stats, analyzed_game_stats)

    # Save analysis data as JSON for the web UI
    analysis_data = {
        "awards": compute_all_awards(analyzed_player_stats, analyzed_game_stats),
        "general_stats": compute_general_stats(analyzed_game_stats),
        "game_results": game_results,
        "player_profiles": compute_player_profiles(analyzed_player_stats, head_to_head),
    }

    with open("analysis_data.json", "w") as f:
        json.dump(analysis_data, f, indent=2, default=str)
    print("Analysis data saved to analysis_data.json")

    # Run TrueSkill with the same parsed replays (no re-parsing)
    run_trueskill(parsed_matches=parsed_matches)

    print("--- AoE2 LAN Party Analyzer Finished ---")

if __name__ == "__main__":
    main()
