import os
import sys
import re
import logging
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Tuple, Optional, Any

import trueskill
from mgz.model import parse_match, Player as MgzPlayer # Added MgzPlayer for type hinting
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import json # Added for JSON export

# --- Add project root to sys.path to allow importing config from analyzer_lib ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.append(PROJECT_ROOT)

from analyzer_lib import config

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# --- Constants ---
MIN_GAME_DURATION_SECONDS = 300
PLOT_MIN_GAMES_THRESHOLD = config.PLOT_MIN_GAMES_THRESHOLD if hasattr(config, 'PLOT_MIN_GAMES_THRESHOLD') else 5 # Default if not in config

class PlayerRating:
    """Represents a player's TrueSkill rating and game statistics."""
    def __init__(self, name: str, initial_rating: trueskill.Rating):
        self.name = name
        self.rating: trueskill.Rating = initial_rating
        self.games_played: int = 0

    def update_rating(self, new_rating: trueskill.Rating):
        self.rating = new_rating

    def increment_games_played(self):
        self.games_played += 1

    def get_scaled_mu(self) -> float:
        return self.rating.mu * config.TRUESKILL_ELO_SCALING_FACTOR

    def get_confidence_percent(self, initial_unscaled_sigma: float) -> float:
        if initial_unscaled_sigma == 0: # Avoid division by zero
            return 100.0 if self.rating.sigma == 0 else 0.0
        return max(0.0, (1.0 - self.rating.sigma / initial_unscaled_sigma)) * 100.0

class GameData:
    """Parses and stores relevant information about a single game."""
    def __init__(self, filename: str, datetime_obj: datetime, 
                 human_players: List[MgzPlayer], teams_data: Dict[int, List[MgzPlayer]], 
                 winning_team_id: Optional[int]):
        self.filename = filename
        self.datetime_obj = datetime_obj
        self.human_players = human_players
        self.teams_data = teams_data
        self.winning_team_id = winning_team_id

    @staticmethod
    def _get_datetime_from_filename(filename: str) -> datetime:
        match = re.search(r'@(\d{4}\.\d{2}\.\d{2} \d{6})', filename)
        if match:
            datetime_str = match.group(1)
            try:
                return datetime.strptime(datetime_str, '%Y.%m.%d %H%M%S')
            except ValueError:
                logging.warning(f"Could not parse datetime from {filename}, using min datetime.")
                return datetime.min
        return datetime.min

    @staticmethod
    def _apply_player_aliases(players: List[MgzPlayer], aliases: Dict[str, str]) -> List[MgzPlayer]:
        for p in players:
            p.name = aliases.get(p.name, p.name)
        return players

    @staticmethod
    def _determine_game_outcomes(human_players_from_match: List[MgzPlayer]) -> Tuple[Optional[int], Dict[int, List[MgzPlayer]]]:
        teams_data = defaultdict(list)
        for p in human_players_from_match:
            team_id = p.team_id
            if isinstance(team_id, list): # mgz library can return team_id as a list
                team_id = team_id[0] if team_id else -1 
            teams_data[team_id].append(p)

        winning_team_id = None
        for team_id, players_in_team in teams_data.items():
            if any(p.winner for p in players_in_team):
                winning_team_id = team_id
                break
        return winning_team_id, dict(teams_data)

    @classmethod
    def from_replay_file(cls, file_path: str, player_aliases: Dict[str, str]) -> Optional['GameData']:
        filename = os.path.basename(file_path)
        try:
            with open(file_path, 'rb') as f:
                match_obj = parse_match(f)
            
            if not match_obj:
                logging.debug(f"Skipping file {filename}: Could not find match data.")
                return None
            if match_obj.duration.total_seconds() < MIN_GAME_DURATION_SECONDS:
                logging.debug(f"Skipping file {filename}: Game duration too short.")
                return None

            human_players = [p for p in match_obj.players if not (hasattr(p, 'ai') and p.ai)]
            if len(human_players) < 2: # Need at least two human players
                logging.debug(f"Skipping game {filename}: Not enough human players ({len(human_players)}).")
                return None

            # Check for unknown players before proceeding with team processing
            canonical_player_names = set(config.PLAYER_ALIASES.values())
            for p in human_players:
                original_name = p.name
                aliased_name = config.PLAYER_ALIASES.get(original_name, original_name)
                if aliased_name not in canonical_player_names:
                    logging.warning(
                        f"Skipping game {filename}: Player '{original_name}' (resolved to '{aliased_name}') "
                        f"is not a recognized canonical player name found in PLAYER_ALIASES values."
                    )
                    return None

            human_players = cls._apply_player_aliases(human_players, player_aliases)
            winning_team_id, teams_data = cls._determine_game_outcomes(human_players)
            datetime_obj = cls._get_datetime_from_filename(filename)

            return cls(filename, datetime_obj, human_players, teams_data, winning_team_id)

        except FileNotFoundError:
            logging.warning(f"Skipping file {filename}: File not found.")
            return None
        except Exception as e:
            logging.warning(f"Skipping file {filename}: Error parsing - {e}")
            return None

    def is_valid_for_rating(self) -> bool:
        if self.winning_team_id is None:
            logging.debug(f"Game {self.filename} invalid for rating: No clear winner.")
            return False
        if len(self.teams_data) != 2:
            logging.debug(f"Game {self.filename} invalid for rating: Not exactly 2 teams (found {len(self.teams_data)}).")
            return False
        
        team_player_lists = list(self.teams_data.values())
        if not team_player_lists[0] or not team_player_lists[1]:
            logging.debug(f"Game {self.filename} invalid for rating: At least one team has zero players.")
            return False
        return True

class TrueSkillCalculator:
    """Manages TrueSkill environment, player ratings, and updates."""
    def __init__(self, mu: float, sigma: float, beta: float, tau: float, draw_probability: float):
        self.ts_env = trueskill.TrueSkill(mu=mu, sigma=sigma, beta=beta, tau=tau, draw_probability=draw_probability)
        self.player_ratings: Dict[str, PlayerRating] = {}
        self.rating_history: List[Dict[str, Any]] = []

    def get_or_create_player_rating(self, player_name: str) -> PlayerRating:
        if player_name not in self.player_ratings:
            self.player_ratings[player_name] = PlayerRating(player_name, self.ts_env.create_rating())
        return self.player_ratings[player_name]

    def update_ratings_for_game(self, game_data: GameData, game_index: int):
        team_ids = list(game_data.teams_data.keys())
        team1_id, team2_id = team_ids[0], team_ids[1]

        team1_player_objs = game_data.teams_data[team1_id]
        team2_player_objs = game_data.teams_data[team2_id]

        team1_ratings_dict = {p.name: self.get_or_create_player_rating(p.name).rating for p in team1_player_objs}
        team2_ratings_dict = {p.name: self.get_or_create_player_rating(p.name).rating for p in team2_player_objs}

        if game_data.winning_team_id == team1_id:
            ranks = [0, 1]
        else:
            ranks = [1, 0]

        weights = None
        num_players_team1 = len(team1_player_objs)
        num_players_team2 = len(team2_player_objs)

        if num_players_team1 != num_players_team2 and num_players_team1 > 0 and num_players_team2 > 0:
            logging.info(f"Game {game_data.filename} has unbalanced teams: {num_players_team1} vs {num_players_team2}. Applying fixed weight of 0.3 to all players.")
            team1_weights = [0.3] * num_players_team1
            team2_weights = [0.3] * num_players_team2
            weights = [team1_weights, team2_weights]
        
        try:
            if weights:
                new_ratings_by_team = self.ts_env.rate(
                    [team1_ratings_dict, team2_ratings_dict], 
                    ranks=ranks,
                    weights=weights
                )
            else:
                new_ratings_by_team = self.ts_env.rate(
                    [team1_ratings_dict, team2_ratings_dict], 
                    ranks=ranks
                )
            
            updated_team1_ratings_map, updated_team2_ratings_map = new_ratings_by_team[0], new_ratings_by_team[1]

            for player_name in team1_ratings_dict.keys():
                player_rating_obj = self.get_or_create_player_rating(player_name)
                old_mu_scaled = player_rating_obj.get_scaled_mu()
                old_sigma_scaled = player_rating_obj.rating.sigma * config.TRUESKILL_ELO_SCALING_FACTOR
                
                player_rating_obj.update_rating(updated_team1_ratings_map[player_name])
                
                new_mu_scaled = player_rating_obj.get_scaled_mu()
                new_sigma_scaled = player_rating_obj.rating.sigma * config.TRUESKILL_ELO_SCALING_FACTOR
                delta_mu = new_mu_scaled - old_mu_scaled
                delta_sigma = new_sigma_scaled - old_sigma_scaled
                logging.info(
                    f"Update | Game: {game_data.filename} | Player: {player_name:<15} | "
                    f"μ: {old_mu_scaled:7.2f} → {new_mu_scaled:7.2f} ({delta_mu:+.2f}) | "
                    f"σ: {old_sigma_scaled:6.2f} → {new_sigma_scaled:6.2f} ({delta_sigma:+.2f})"
                )
                self.rating_history.append({
                    'game_index': game_index, 
                    'player_name': player_name, 
                    'mu': player_rating_obj.get_scaled_mu(), 
                    'sigma': player_rating_obj.rating.sigma * config.TRUESKILL_ELO_SCALING_FACTOR
                })

            for player_name in team2_ratings_dict.keys():
                player_rating_obj = self.get_or_create_player_rating(player_name)
                old_mu_scaled = player_rating_obj.get_scaled_mu()
                old_sigma_scaled = player_rating_obj.rating.sigma * config.TRUESKILL_ELO_SCALING_FACTOR
                
                player_rating_obj.update_rating(updated_team2_ratings_map[player_name])
                
                new_mu_scaled = player_rating_obj.get_scaled_mu()
                new_sigma_scaled = player_rating_obj.rating.sigma * config.TRUESKILL_ELO_SCALING_FACTOR
                delta_mu = new_mu_scaled - old_mu_scaled
                delta_sigma = new_sigma_scaled - old_sigma_scaled
                logging.info(
                    f"Update | Game: {game_data.filename} | Player: {player_name:<15} | "
                    f"μ: {old_mu_scaled:7.2f} → {new_mu_scaled:7.2f} ({delta_mu:+.2f}) | "
                    f"σ: {old_sigma_scaled:6.2f} → {new_sigma_scaled:6.2f} ({delta_sigma:+.2f})"
                )
                self.rating_history.append({
                    'game_index': game_index, 
                    'player_name': player_name, 
                    'mu': player_rating_obj.get_scaled_mu(), 
                    'sigma': player_rating_obj.rating.sigma * config.TRUESKILL_ELO_SCALING_FACTOR
                })

        except Exception as e:
            logging.error(f"Error updating TrueSkill ratings for game {game_data.filename}: {type(e).__name__} - {repr(e)}")

class ReportGenerator:
    """Generates textual and graphical reports for TrueSkill ratings."""
    def __init__(self, elo_scaling_factor: float, initial_unscaled_sigma: float, plot_min_games: int):
        self.elo_scaling_factor = elo_scaling_factor
        self.initial_unscaled_sigma = initial_unscaled_sigma
        self.plot_min_games_threshold = plot_min_games

    def print_final_rankings(self, player_ratings_map: Dict[str, PlayerRating], min_games_for_ranking: int):
        logging.info("\n--- Final TrueSkill Player Rankings ---")
        
        all_players_sorted = sorted(player_ratings_map.values(), key=lambda p: p.rating.mu, reverse=True)

        ranked_players = [p for p in all_players_sorted if p.games_played >= min_games_for_ranking]
        provisional_players = [p for p in all_players_sorted if p.games_played < min_games_for_ranking]

        print("\n--- Final TrueSkill Player Rankings ({} or more games) ---".format(min_games_for_ranking))
        print("  Rank  Player               Mu (μ)     Confidence   Games")
        print("  -------------------------------------------------------------")
        if not ranked_players:
            print("  No players meet the minimum game requirement for ranking.")
        else:
            for i, p_rating in enumerate(ranked_players):
                mu_scaled = p_rating.get_scaled_mu()
                confidence = p_rating.get_confidence_percent(self.initial_unscaled_sigma)
                print(f"  {i+1:<5} {p_rating.name:<20} {mu_scaled:<10.2f} {confidence:>9.1f}%   {p_rating.games_played:>5}")

        if provisional_players:
            print("\n--- Provisional Ratings (Less than {} games) ---".format(min_games_for_ranking))
            print("        Player               Mu (μ)     Confidence   Games")
            print("  -------------------------------------------------------------")
            for p_rating in provisional_players:
                mu_scaled = p_rating.get_scaled_mu()
                confidence = p_rating.get_confidence_percent(self.initial_unscaled_sigma)
                print(f"        {p_rating.name:<20} {mu_scaled:<10.2f} {confidence:>9.1f}%   {p_rating.games_played:>5}")
        print("\n  Higher Confidence indicates a more stable Mu (μ) rating.")

    def plot_rating_evolution(self, rating_history: List[Dict[str, Any]], output_filename: str = 'trueskill_evolution.png'):
        if not rating_history:
            logging.info("No rating history recorded, skipping plot generation.")
            return

        df = pd.DataFrame(rating_history)
        plt.style.use('seaborn-v0_8-whitegrid')
        plt.figure(figsize=(18, 10))

        player_game_counts = df.groupby('player_name')['game_index'].nunique()
        players_to_plot = player_game_counts[player_game_counts > self.plot_min_games_threshold].index
        df_filtered = df[df['player_name'].isin(players_to_plot)]

        if df_filtered.empty:
            logging.info(f"No players have enough games (>{self.plot_min_games_threshold}) to be plotted. Skipping plot generation.")
            return

        plt.figure(figsize=(15, 10))
        sns.set_style("whitegrid")
        sns.set_palette("tab20") # Use a more diverse color palette

        # Filter players with enough games for plotting
        df_plot = df[df['player_name'].isin(players_to_plot)]

        if df_plot.empty:
            logging.info("No players meet the minimum game threshold for plotting.")
            plt.close()
            return
        
        # Plotting with Seaborn
        sns.lineplot(
            data=df_plot, 
            x='game_index', 
            y='mu', 
            hue='player_name', 
            legend='full',
            markers=True, # Add distinct markers for each line
            dashes=False,   # Ensure all lines are solid
            linewidth=2.5
        )

        for player_name_val in df_filtered['player_name'].unique(): # Renamed to avoid conflict
            player_data = df_filtered[df_filtered['player_name'] == player_name_val]
            plt.fill_between(
                player_data['game_index'],
                player_data['mu'] - player_data['sigma'],
                player_data['mu'] + player_data['sigma'],
                alpha=0.2
            )

        plt.title('TrueSkill Rating Evolution (μ ± σ, Scaled)', fontsize=18, fontweight='bold')
        plt.xlabel('Game Index (Chronological)', fontsize=14)
        plt.ylabel(f'TrueSkill Rating (μ, Scaled by {self.elo_scaling_factor})', fontsize=14)
        plt.legend(title='Player', bbox_to_anchor=(1.05, 1), loc='upper left', borderaxespad=0.)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True, which='both', linestyle='--', linewidth=0.5)
        plt.tight_layout(rect=[0, 0, 0.85, 1])

        try:
            plot_dir = os.path.join(PROJECT_ROOT, 'plots')
            os.makedirs(plot_dir, exist_ok=True)
            plot_path = os.path.join(plot_dir, output_filename)
            plt.savefig(plot_path)
            logging.info(f"Rating evolution plot saved to: {plot_path}")
        except Exception as e:
            logging.error(f"Error saving plot: {e}")
        finally:
            plt.close()

    def save_ratings_to_json(self, player_ratings_map: Dict[str, PlayerRating], output_filename: str = "player_ratings.json"):
        """Saves the player ratings to a JSON file."""
        ratings_list = []
        for player_name, player_rating_obj in player_ratings_map.items():
            ratings_list.append({
                "name": player_name,
                "mu_scaled": round(player_rating_obj.get_scaled_mu(), 2),
                "sigma_scaled": round(player_rating_obj.rating.sigma * self.elo_scaling_factor, 2),
                "mu_unscaled": round(player_rating_obj.rating.mu, 4),
                "sigma_unscaled": round(player_rating_obj.rating.sigma, 4),
                "games_played": player_rating_obj.games_played,
                "confidence_percent": round(player_rating_obj.get_confidence_percent(self.initial_unscaled_sigma), 1)
            })
        
        # Sort by scaled mu descending for consistent order in JSON
        ratings_list.sort(key=lambda x: x['mu_scaled'], reverse=True)

        output_path = os.path.join(PROJECT_ROOT, output_filename)
        try:
            with open(output_path, 'w') as f:
                json.dump(ratings_list, f, indent=2)
            logging.info(f"Player ratings saved to: {output_path}")
        except Exception as e:
            logging.error(f"Error saving player ratings to JSON: {e}")

def main():
    logging.info("--- Starting TrueSkill Calculation (Refactored) ---")
    recorded_games_path = os.path.join(PROJECT_ROOT, config.RECORDED_GAMES_DIR)
    if not os.path.exists(recorded_games_path):
        logging.error(f"Recorded games directory not found at {recorded_games_path}")
        return

    replay_files_paths = []
    for root, _, files in os.walk(recorded_games_path):
        for file in files:
            if file.endswith(('.aoe2record', '.mgz', '.mgx')):
                replay_files_paths.append(os.path.join(root, file))

    # Sort files by datetime in filename to process chronologically
    # GameData._get_datetime_from_filename is used here before GameData objects are created
    replay_files_paths.sort(key=lambda f: GameData._get_datetime_from_filename(os.path.basename(f)))

    calculator = TrueSkillCalculator(
        mu=config.TRUESKILL_MU,
        sigma=config.TRUESKILL_SIGMA,
        beta=config.TRUESKILL_BETA,
        tau=config.TRUESKILL_TAU,
        draw_probability=config.TRUESKILL_DRAW_PROBABILITY
    )
    reporter = ReportGenerator(
        elo_scaling_factor=config.TRUESKILL_ELO_SCALING_FACTOR,
        initial_unscaled_sigma=config.TRUESKILL_SIGMA,
        plot_min_games=PLOT_MIN_GAMES_THRESHOLD
    )

    game_index_rated = 0
    invalid_games_skipped = 0

    logging.info(f"Found {len(replay_files_paths)} replay files. Processing...")

    for file_path in replay_files_paths:
        game_data = GameData.from_replay_file(file_path, config.PLAYER_ALIASES)

        if not game_data:
            invalid_games_skipped += 1
            continue

        # Update game counts for all participating (aliased) human players
        # This needs to be done for every player in a parsed game, even if not rated
        for player_obj in game_data.human_players:
            player_rating = calculator.get_or_create_player_rating(player_obj.name)
            player_rating.increment_games_played()

        if not game_data.is_valid_for_rating():
            invalid_games_skipped += 1
            continue
        
        game_index_rated += 1
        calculator.update_ratings_for_game(game_data, game_index_rated)
    
    reporter.print_final_rankings(calculator.player_ratings, config.MIN_GAMES_FOR_RANKING)
    reporter.plot_rating_evolution(calculator.rating_history)
    reporter.save_ratings_to_json(calculator.player_ratings)

    logging.info("\n--- Skipped Games Summary ---")
    logging.info(f"  Games skipped due to parsing errors, duration, or invalid teams: {invalid_games_skipped}")

    logging.info("\n--- Parameters Used ---")
    logging.info(f"  MU={config.TRUESKILL_MU}, SIGMA={config.TRUESKILL_SIGMA:.4f}, BETA={config.TRUESKILL_BETA:.4f}, TAU={config.TRUESKILL_TAU:.4f}")
    logging.info(f"  DRAW_PROB={config.TRUESKILL_DRAW_PROBABILITY}, ELO_SCALING={config.TRUESKILL_ELO_SCALING_FACTOR}")
    logging.info(f"  MIN_GAMES_FOR_RANKING={config.MIN_GAMES_FOR_RANKING}, PLOT_MIN_GAMES={PLOT_MIN_GAMES_THRESHOLD}")
    logging.info("-" * 61)
    logging.info("--- TrueSkill Calculation Complete ---")

if __name__ == "__main__":
    main()
