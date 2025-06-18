# main.py - Main entry point for the AoE2 LAN Party Analyzer

# It's good practice to handle potential issues with imports or execution
# by putting the main logic in a function and calling it from the
# if __name__ == "__main__": block.

# Import the core analysis function
from analyzer_lib.analyze_games import analyze_all_games

# Import the report generation function from report_generator.py
from analyzer_lib.report_generator import print_report

def main():
    """
    Main function to run the AoE2 LAN Party Analyzer.
    It orchestrates the game analysis and report generation.
    """
    print("--- Starting AoE2 LAN Party Analyzer ---")

    # Perform the analysis of all game replays
    # analyze_all_games now returns player_stats, game_stats, and player_trueskill_ratings
    result = analyze_all_games()

    if result is None: # analyze_all_games returns None if dir not found or critical error
        print("Analysis could not be completed. Exiting.")
        return

    analyzed_player_stats, analyzed_game_stats = result

    # Generate and print the analytics report
    print_report(analyzed_player_stats, analyzed_game_stats)

    print("--- AoE2 LAN Party Analyzer Finished ---")

if __name__ == "__main__":
    main()
