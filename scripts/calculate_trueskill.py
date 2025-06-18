import os
import sys
import re
from datetime import datetime, timedelta
from collections import defaultdict
import trueskill
from mgz.model import parse_match

# --- Add project root to sys.path to allow importing config from analyzer_lib ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.append(PROJECT_ROOT)

from analyzer_lib import config

# --- TrueSkill Environment Setup ---
# Tuned parameters: beta for sensitivity, draw_probability for close games.
ts_env = trueskill.TrueSkill(beta=config.TRUESKILL_BETA, draw_probability=config.TRUESKILL_DRAW_PROBABILITY)

# --- Helper Functions (copied/adapted from analyze_games.py) ---
def _get_datetime_from_filename(filename):
    """Extracts datetime from filename to allow chronological sorting."""
    match = re.search(r'@(\d{4}\.\d{2}\.\d{2} \d{6})', filename)
    if match:
        datetime_str = match.group(1)
        try:
            return datetime.strptime(datetime_str, '%Y.%m.%d %H%M%S')
        except ValueError:
            print(f"Warning: Could not parse datetime from {filename}, using min datetime.")
            return datetime.min
    return datetime.min

def parse_replay_file(file_path, filename):
    """Parses a single replay file and performs initial validation."""
    # print(f"Analyzing: {filename}") # Optional: for verbose output
    try:
        with open(file_path, 'rb') as f:
            match_obj = parse_match(f)
        if not match_obj:
            # print(f"  -> Skipping file {filename}: Could not find match data.")
            return None
        if match_obj.duration.total_seconds() < 300: # Filter out games shorter than 5 minutes
            # print(f"  -> Skipping file {filename}: Game duration too short.")
            return None
        return match_obj
    except FileNotFoundError:
        # print(f"  -> Skipping file {filename}: File not found.")
        return None
    except Exception as e:
        # print(f"  -> Skipping file {filename}: Error parsing - {e}")
        return None

def _determine_game_outcomes(human_players_from_match, filename_for_logging):
    """Determines the winning team and individual player outcomes."""
    teams_data = defaultdict(list)
    for p in human_players_from_match:
        team_id = p.team_id
        if isinstance(team_id, list):
            team_id = team_id[0] if team_id else -1 # Handle cases where team_id might be a list
        teams_data[team_id].append(p)

    winning_team_id = None
    for team_id, players_in_team in teams_data.items():
        if any(p.winner for p in players_in_team):
            winning_team_id = team_id
            break
    
    # Note: player_outcomes dict is not strictly needed for this script but kept for consistency
    player_outcomes = {}
    for player in human_players_from_match:
        player_team_id = player.team_id
        if isinstance(player_team_id, list):
            player_team_id = player_team_id[0] if player_team_id else -1
        player_outcomes[player.name] = (player_team_id == winning_team_id)
        
    return winning_team_id, player_outcomes, teams_data

def _update_trueskill_ratings_for_game(teams_data, winning_team_id, player_trueskill_ratings, current_ts_env, filename):
    """Updates TrueSkill ratings for players based on a single game's outcome."""
    if not (teams_data and winning_team_id is not None and len(teams_data) == 2):
        # print(f"  -> Info: TrueSkill rating skipped for {filename}. Not a 2-team game with a clear winner or no teams_data.")
        return

    game_player_ratings_before = {}
    team_ratings_map = {}
    team_player_names_map = {}

    try:
        for team_id, team_info in teams_data.items():
            player_ratings_for_team = []
            player_names_for_team = []
            for player_obj in team_info:
                player_name = player_obj.name
                player_names_for_team.append(player_name)
                current_rating = player_trueskill_ratings.get(player_name, current_ts_env.Rating())
                player_ratings_for_team.append(current_rating)
                game_player_ratings_before[player_name] = (current_rating.mu, current_rating.sigma)
            
            team_ratings_map[team_id] = tuple(player_ratings_for_team)
            team_player_names_map[team_id] = player_names_for_team

        team_ids = list(team_ratings_map.keys())
        if len(team_ids) != 2:
            # print(f"  -> Info: TrueSkill rating skipped for {filename}. Expected 2 teams, found {len(team_ids)}.")
            return

        winner_team_actual_id = winning_team_id
        loser_team_actual_id = [tid for tid in team_ids if tid != winner_team_actual_id][0]

        ratings_group_winner = team_ratings_map[winner_team_actual_id]
        ratings_group_loser = team_ratings_map[loser_team_actual_id]
        
        new_ratings_winner, new_ratings_loser = current_ts_env.rate([ratings_group_winner, ratings_group_loser], ranks=[0, 1])

        print(f"  -> TrueSkill Update for {filename}:")
        SCALING_FACTOR = config.TRUESKILL_ELO_SCALING_FACTOR

        for i, player_name in enumerate(team_player_names_map[winner_team_actual_id]):
            old_mu_raw, old_sigma_raw = game_player_ratings_before[player_name]
            new_rating_obj = new_ratings_winner[i]
            player_trueskill_ratings[player_name] = new_rating_obj
            
            old_mu_scaled = old_mu_raw * SCALING_FACTOR
            old_sigma_scaled = old_sigma_raw * SCALING_FACTOR
            new_mu_scaled = new_rating_obj.mu * SCALING_FACTOR
            new_sigma_scaled = new_rating_obj.sigma * SCALING_FACTOR
            mu_change_scaled = new_mu_scaled - old_mu_scaled
            
            print(f"     {player_name:<20} (W): Rating {old_mu_scaled:>7.2f} ±{old_sigma_scaled:<6.2f} -> {new_mu_scaled:>7.2f} ±{new_sigma_scaled:<6.2f} (Change: {mu_change_scaled:+.2f})")

        for i, player_name in enumerate(team_player_names_map[loser_team_actual_id]):
            old_mu_raw, old_sigma_raw = game_player_ratings_before[player_name]
            new_rating_obj = new_ratings_loser[i]
            player_trueskill_ratings[player_name] = new_rating_obj

            old_mu_scaled = old_mu_raw * SCALING_FACTOR
            old_sigma_scaled = old_sigma_raw * SCALING_FACTOR
            new_mu_scaled = new_rating_obj.mu * SCALING_FACTOR
            new_sigma_scaled = new_rating_obj.sigma * SCALING_FACTOR
            mu_change_scaled = new_mu_scaled - old_mu_scaled

            print(f"     {player_name:<20} (L): Rating {old_mu_scaled:>7.2f} ±{old_sigma_scaled:<6.2f} -> {new_mu_scaled:>7.2f} ±{new_sigma_scaled:<6.2f} (Change: {mu_change_scaled:+.2f})")

    except Exception as e:
        print(f"  -> Error during TrueSkill rating for {filename}: {e}")

# --- Main Execution Block ---
def main():
    print("--- Starting Standalone TrueSkill Calculation ---")
    player_trueskill_ratings = {}

    if not hasattr(config, 'RECORDED_GAMES_DIR') or not os.path.isdir(config.RECORDED_GAMES_DIR):
        print(f"Error: RECORDED_GAMES_DIR '{config.RECORDED_GAMES_DIR}' not found or not configured.")
        return

    replay_files = [f for f in os.listdir(config.RECORDED_GAMES_DIR) if f.endswith('.aoe2record')]
    replay_files.sort(key=_get_datetime_from_filename)

    print(f"Found {len(replay_files)} replay files to process for TrueSkill ratings.")

    for filename in replay_files:
        file_path = os.path.join(config.RECORDED_GAMES_DIR, filename)
        match_obj = parse_replay_file(file_path, filename)

        if not match_obj:
            continue

        human_players_from_match = [p for p in match_obj.players if hasattr(p, 'profile_id') and p.profile_id is not None]
        
        # Apply Player Aliases
        for player_obj in human_players_from_match:
            player_obj.name = config.PLAYER_ALIASES.get(player_obj.name, player_obj.name)

        # --- Filter games to include only known players from PLAYER_ALIASES ---
        known_players = set(config.PLAYER_ALIASES.values())
        game_player_names = {p.name for p in human_players_from_match}

        if not game_player_names.issubset(known_players):
            unknown_players = game_player_names - known_players
            # print(f"  -> Info: Skipping game {filename}. Contains unknown players: {', '.join(unknown_players)}")
            continue

        winning_team_id, _, teams_data = _determine_game_outcomes(human_players_from_match, filename)
        _update_trueskill_ratings_for_game(teams_data, winning_team_id, player_trueskill_ratings, ts_env, filename)
    
    print("\n--- Final TrueSkill Player Rankings ---")
    SCALING_FACTOR = config.TRUESKILL_ELO_SCALING_FACTOR
    sorted_players = sorted(player_trueskill_ratings.items(), key=lambda item: item[1].mu, reverse=True)

    print("  Rank  Player               Mu (μ)     Sigma (σ) ")
    print("  --------------------------------------------------")
    for i, (player_name, rating) in enumerate(sorted_players):
        mu_scaled = rating.mu * SCALING_FACTOR
        sigma_scaled = rating.sigma * SCALING_FACTOR # Scale sigma for consistency if desired
        print(f"  {i+1:<5} {player_name:<20} {mu_scaled:<10.2f} {sigma_scaled:<9.2f} ")
    print("  Lower Sigma (σ) indicates higher confidence in the Mu (μ) rating.")
    print("--- TrueSkill Calculation Complete ---")

if __name__ == "__main__":
    main()
