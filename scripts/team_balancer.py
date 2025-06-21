#!/usr/bin/env python3
import argparse
import itertools
import json
import os
import sys
from typing import List, Dict, Tuple, Any

# --- Add project root to sys.path to allow importing config from analyzer_lib ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
ANALYZER_LIB_PATH = os.path.join(PROJECT_ROOT, 'analyzer_lib')
sys.path.insert(0, PROJECT_ROOT) 
sys.path.insert(0, ANALYZER_LIB_PATH)

try:
    from analyzer_lib import config
    TS_BETA = config.TRUESKILL_BETA
    TS_DRAW_PROBABILITY = config.TRUESKILL_DRAW_PROBABILITY
    ELO_SCALING_FACTOR = config.TRUESKILL_ELO_SCALING_FACTOR
    # print(f"Successfully imported TrueSkill params from config: BETA={TS_BETA}, DRAW_PROB={TS_DRAW_PROBABILITY}")
except ImportError as e:
    # print(f"Warning: Could not import config.py ({e}). Using default TrueSkill parameters for team balancing.")
    # Default values from the main script's config.py structure
    TS_MU = 25.0
    TS_SIGMA = TS_MU / 3.0
    TS_BETA = TS_SIGMA / 2.0 # approx 4.1667
    TS_DRAW_PROBABILITY = 0.10
    ELO_SCALING_FACTOR = 40

import trueskill # Placed after sys.path modification

PLAYER_RATINGS_FILE = os.path.join(PROJECT_ROOT, "player_ratings.json")

def load_player_ratings(filepath: str = PLAYER_RATINGS_FILE) -> Dict[str, Dict[str, Any]]:
    """Loads player ratings from the JSON file."""
    try:
        with open(filepath, 'r') as f:
            ratings_data = json.load(f)
        return {player['name']: player for player in ratings_data}
    except FileNotFoundError:
        print(f"Error: Ratings file not found at {filepath}")
        print("Please run calculate_trueskill.py first to generate the ratings file.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {filepath}")
        sys.exit(1)

def find_balanced_teams(player_ts_ratings: Dict[str, trueskill.Rating], ts_env: trueskill.TrueSkill, top_n: int = 3) -> List[Tuple[float, List[str], List[str]]]:
    """
    Finds the most balanced team combinations for a given list of players.
    Returns a list of tuples: (quality_score, team1_names, team2_names)
    """
    players_in_game = list(player_ts_ratings.keys())
    num_players = len(players_in_game)
    
    if num_players < 2:
        print("Need at least 2 players to form two teams.")
        return []

    possible_matchups = []
    processed_matchups = set()

    # Iterate through all possible team sizes for team 1
    for team1_size in range(1, num_players // 2 + 1):
        # Iterate through all combinations for team 1 of that size
        for team1_tuple in itertools.combinations(players_in_game, team1_size):
            team1_names = list(team1_tuple)
            team2_names = [p for p in players_in_game if p not in team1_names]

            # Create a canonical representation to avoid duplicates
            canonical_matchup = tuple(sorted((tuple(sorted(team1_names)), tuple(sorted(team2_names)))))
            if canonical_matchup in processed_matchups:
                continue
            processed_matchups.add(canonical_matchup)

            team1_ratings = tuple(player_ts_ratings[name] for name in team1_names)
            team2_ratings = tuple(player_ts_ratings[name] for name in team2_names)

            if not team1_ratings or not team2_ratings:
                continue

            quality = ts_env.quality([team1_ratings, team2_ratings])
            possible_matchups.append((quality, sorted(team1_names), sorted(team2_names)))

    # Sort all found matchups by quality, descending
    possible_matchups.sort(key=lambda x: x[0], reverse=True)
    
    return possible_matchups[:top_n]

def main():
    parser = argparse.ArgumentParser(description="Suggest balanced teams for AoE2 LAN parties based on TrueSkill ratings.")
    parser.add_argument("players", nargs='+', help="A list of player names to form teams from.")
    parser.add_argument("--top_n", type=int, default=3, help="Number of top balanced team suggestions to show.")
    
    args = parser.parse_args()
    
    requested_player_names = sorted(list(set(args.players))) # Unique player names, sorted

    if len(requested_player_names) < 2:
        print("Error: Please provide at least two unique player names.")
        sys.exit(1)
    
    print(f"Attempting to balance teams for: {', '.join(requested_player_names)}")
    # print(f"Using TrueSkill Beta: {TS_BETA:.4f}, Draw Probability: {TS_DRAW_PROBABILITY:.2f}\n")

    all_player_ratings_data = load_player_ratings()
    
    player_ts_ratings: Dict[str, trueskill.Rating] = {}
    valid_player_names_for_balancing = []
    missing_players_from_ratings = []

    for name in requested_player_names:
        if name in all_player_ratings_data:
            player_data = all_player_ratings_data[name]
            player_ts_ratings[name] = trueskill.Rating(mu=player_data['mu_unscaled'], sigma=player_data['sigma_unscaled'])
            valid_player_names_for_balancing.append(name)
        else:
            missing_players_from_ratings.append(name)
    
    if missing_players_from_ratings:
        print(f"\nWarning: The following players were not found in '{PLAYER_RATINGS_FILE}' and will be excluded:")
        for p_name in sorted(missing_players_from_ratings):
            print(f"  - {p_name}")
        
        if not valid_player_names_for_balancing:
            print("\nError: None of the provided players were found in the ratings file. Exiting.")
            sys.exit(1)
        print(f"\nProceeding with balancing for: {', '.join(sorted(valid_player_names_for_balancing))}\n")
    else:
        print("All requested players found in ratings file.\n")

    if len(valid_player_names_for_balancing) < 2:
        print("Error: Need at least two players with available ratings to form teams.")
        sys.exit(1)

    # Initialize TrueSkill environment. Only beta and draw_probability from the env are used by quality().
    ts_env = trueskill.TrueSkill(beta=TS_BETA, draw_probability=TS_DRAW_PROBABILITY)
                                 
    # Filter player_ts_ratings to only include valid players for find_balanced_teams
    final_player_ts_ratings = {name: rating for name, rating in player_ts_ratings.items() if name in valid_player_names_for_balancing}

    balanced_teams = find_balanced_teams(final_player_ts_ratings, ts_env, top_n=args.top_n)
    
    if not balanced_teams:
        print("Could not find any balanced team combinations (perhaps too few players after filtering or an issue in logic).")
    else:
        print(f"--- Top {min(args.top_n, len(balanced_teams))} Most Balanced Team Combinations ---")
        print(f"(Based on TrueSkill Beta: {TS_BETA:.4f}, a configured draw probability of {TS_DRAW_PROBABILITY*100:.1f}% is used for rating updates)")
        print("Match Quality is the calculated probability of a draw. A higher percentage indicates a more balanced and unpredictable game.")

        for i, (quality, team1_names_sorted, team2_names_sorted) in enumerate(balanced_teams):
            print(f"\n--- Suggestion #{i+1} ---")
            print(f"Match Quality: {quality*100:.2f}%")
            print(f"  Team 1: {', '.join(team1_names_sorted)}")
            print(f"  Team 2: {', '.join(team2_names_sorted)}")

            # Determine Expected Winner by comparing sum of ratings
            team1_mu_sum = sum(final_player_ts_ratings[name].mu for name in team1_names_sorted)
            team2_mu_sum = sum(final_player_ts_ratings[name].mu for name in team2_names_sorted)
            
            if abs(team1_mu_sum - team2_mu_sum) < 0.01: # Arbitrary small threshold
                expected_winner = "Too close to call"
            elif team1_mu_sum > team2_mu_sum:
                expected_winner = "Team 1"
            else:
                expected_winner = "Team 2"
            print(f"  Expected Winner: {expected_winner}")

            # --- Simulate outcomes and store deltas ---
            team1_ratings = tuple(final_player_ts_ratings[name] for name in team1_names_sorted)
            team2_ratings = tuple(final_player_ts_ratings[name] for name in team2_names_sorted)
            
            potential_changes = {}

            if team1_ratings and team2_ratings:
                # Simulate Team 1 winning (Team 2 loses)
                t1_wins_ratings = ts_env.rate([team1_ratings, team2_ratings], ranks=[0, 1])
                # Simulate Team 2 winning (Team 1 loses)
                t2_wins_ratings = ts_env.rate([team1_ratings, team2_ratings], ranks=[1, 0])

                # Populate changes for Team 1 players
                for idx, player_name in enumerate(team1_names_sorted):
                    old_mu = team1_ratings[idx].mu
                    potential_changes[player_name] = {
                        'win': (t1_wins_ratings[0][idx].mu - old_mu) * ELO_SCALING_FACTOR,
                        'loss': (t2_wins_ratings[0][idx].mu - old_mu) * ELO_SCALING_FACTOR
                    }
                
                # Populate changes for Team 2 players
                for idx, player_name in enumerate(team2_names_sorted):
                    old_mu = team2_ratings[idx].mu
                    potential_changes[player_name] = {
                        'win': (t2_wins_ratings[1][idx].mu - old_mu) * ELO_SCALING_FACTOR,
                        'loss': (t1_wins_ratings[1][idx].mu - old_mu) * ELO_SCALING_FACTOR
                    }

            # --- Print the simplified summary ---
            if potential_changes:
                print("\n  Potential Rating Changes (Win / Loss):")
                print("    Team 1:")
                for player_name in team1_names_sorted:
                    changes = potential_changes[player_name]
                    print(f"      {player_name:<16}: {changes['win']:+6.2f} / {changes['loss']:+6.2f}")
                print("    Team 2:")
                for player_name in team2_names_sorted:
                    changes = potential_changes[player_name]
                    print(f"      {player_name:<16}: {changes['win']:+6.2f} / {changes['loss']:+6.2f}")

if __name__ == "__main__":
    main()
