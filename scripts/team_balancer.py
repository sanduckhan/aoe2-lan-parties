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
    player_names = list(player_ts_ratings.keys())
    n_players = len(player_names)
    
    if n_players < 2:
        # This case should ideally be caught before calling this function
        print("Need at least 2 players to form two teams.")
        return []

    possible_matchups = []

    for team1_size in range(1, n_players // 2 + 1):
        for team1_tuple in itertools.combinations(player_names, team1_size):
            team1_list = list(team1_tuple)
            team2_list = [p for p in player_names if p not in team1_list]

            if not team1_list or not team2_list:
                continue

            team1_ratings = tuple(player_ts_ratings[name] for name in team1_list)
            team2_ratings = tuple(player_ts_ratings[name] for name in team2_list)
            
            match_quality = ts_env.quality([team1_ratings, team2_ratings])
            possible_matchups.append((match_quality, sorted(team1_list), sorted(team2_list)))

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
            print(f"\nSuggestion #{i+1} (Match Quality: {quality*100:.2f}%)")
            print(f"  Team 1: {', '.join(team1_names_sorted)} (Size: {len(team1_names_sorted)})")
            print(f"  Team 2: {', '.join(team2_names_sorted)} (Size: {len(team2_names_sorted)})")

            # Prepare rating objects for simulation
            team1_current_ratings_tuple = tuple(final_player_ts_ratings[name] for name in team1_names_sorted)
            team2_current_ratings_tuple = tuple(final_player_ts_ratings[name] for name in team2_names_sorted)

            # Simulate Team 1 wins
            if team1_current_ratings_tuple and team2_current_ratings_tuple: # Ensure teams are not empty
                new_ratings_t1_wins = ts_env.rate([team1_current_ratings_tuple, team2_current_ratings_tuple], ranks=[0, 1])
                print("\n  Potential Outcomes & Rating Changes (Scaled Mu ± Scaled Sigma):")
                print("  -----------------------------------------------------------------------")
                print("  IF Team 1 WINS:")
                for idx, player_name in enumerate(team1_names_sorted):
                    old_r = team1_current_ratings_tuple[idx]
                    new_r = new_ratings_t1_wins[0][idx]
                    delta_mu_scaled = (new_r.mu - old_r.mu) * ELO_SCALING_FACTOR
                    print(f"    {player_name:<18}: μ {old_r.mu * ELO_SCALING_FACTOR:7.2f} → {new_r.mu * ELO_SCALING_FACTOR:7.2f} ({delta_mu_scaled:+6.2f}) | σ {old_r.sigma * ELO_SCALING_FACTOR:5.2f} → {new_r.sigma * ELO_SCALING_FACTOR:5.2f}")
                for idx, player_name in enumerate(team2_names_sorted):
                    old_r = team2_current_ratings_tuple[idx]
                    new_r = new_ratings_t1_wins[1][idx]
                    delta_mu_scaled = (new_r.mu - old_r.mu) * ELO_SCALING_FACTOR
                    print(f"    {player_name:<18}: μ {old_r.mu * ELO_SCALING_FACTOR:7.2f} → {new_r.mu * ELO_SCALING_FACTOR:7.2f} ({delta_mu_scaled:+6.2f}) | σ {old_r.sigma * ELO_SCALING_FACTOR:5.2f} → {new_r.sigma * ELO_SCALING_FACTOR:5.2f}")

            # Simulate Team 2 wins
            if team1_current_ratings_tuple and team2_current_ratings_tuple: # Ensure teams are not empty
                new_ratings_t2_wins = ts_env.rate([team1_current_ratings_tuple, team2_current_ratings_tuple], ranks=[1, 0])
                print("  -----------------------------------------------------------------------")
                print("  IF Team 2 WINS:")
                for idx, player_name in enumerate(team1_names_sorted):
                    old_r = team1_current_ratings_tuple[idx]
                    new_r = new_ratings_t2_wins[0][idx]
                    delta_mu_scaled = (new_r.mu - old_r.mu) * ELO_SCALING_FACTOR
                    print(f"    {player_name:<18}: μ {old_r.mu * ELO_SCALING_FACTOR:7.2f} → {new_r.mu * ELO_SCALING_FACTOR:7.2f} ({delta_mu_scaled:+6.2f}) | σ {old_r.sigma * ELO_SCALING_FACTOR:5.2f} → {new_r.sigma * ELO_SCALING_FACTOR:5.2f}")
                for idx, player_name in enumerate(team2_names_sorted):
                    old_r = team2_current_ratings_tuple[idx]
                    new_r = new_ratings_t2_wins[1][idx]
                    delta_mu_scaled = (new_r.mu - old_r.mu) * ELO_SCALING_FACTOR
                    print(f"    {player_name:<18}: μ {old_r.mu * ELO_SCALING_FACTOR:7.2f} → {new_r.mu * ELO_SCALING_FACTOR:7.2f} ({delta_mu_scaled:+6.2f}) | σ {old_r.sigma * ELO_SCALING_FACTOR:5.2f} → {new_r.sigma * ELO_SCALING_FACTOR:5.2f}")
                print("  -----------------------------------------------------------------------")

if __name__ == "__main__":
    main()
