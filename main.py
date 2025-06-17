# main.py - Main entry point for the AoE2 LAN Party Analyzer

# It's good practice to handle potential issues with imports or execution
# by putting the main logic in a function and calling it from the
# if __name__ == "__main__": block.

# Import the core analysis function and necessary data structures
# from analyze_games.py
from analyzer_lib.analyze_games import analyze_all_games, player_stats, game_stats

# Import the report generation function from report_generator.py
from analyzer_lib.report_generator import print_report

def main():
    """
    Main function to run the AoE2 LAN Party Analyzer.
    It orchestrates the game analysis and report generation.
    """
    print("--- Starting AoE2 LAN Party Analyzer ---")

    # Perform the analysis of all game replays
    # This will populate player_stats and game_stats
    analyze_all_games()

    # Generate and print the analytics report
    # This uses the populated player_stats and game_stats
    print_report(player_stats, game_stats)

    print("--- AoE2 LAN Party Analyzer Finished ---")

if __name__ == "__main__":
    main()
