import os
import sys
import logging
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Optional, Any

import json
import trueskill

# --- Add project root to sys.path to allow importing config from analyzer_lib ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.append(PROJECT_ROOT)

from analyzer_lib import config

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# --- Constants ---
PLOT_MIN_GAMES_THRESHOLD = (
    config.PLOT_MIN_GAMES_THRESHOLD
    if hasattr(config, "PLOT_MIN_GAMES_THRESHOLD")
    else 5
)


class PlayerRating:
    """Represents a player's TrueSkill rating and game statistics."""

    def __init__(self, name: str, initial_rating: trueskill.Rating):
        self.name = name
        self.rating: trueskill.Rating = initial_rating
        self.games_played: int = 0
        self.games_rated: int = 0

    def update_rating(self, new_rating: trueskill.Rating):
        self.rating = new_rating

    def increment_games_played(self):
        self.games_played += 1

    def increment_games_rated(self):
        self.games_rated += 1

    def get_scaled_mu(self) -> float:
        return self.rating.mu * config.TRUESKILL_ELO_SCALING_FACTOR

    def get_confidence_percent(self, initial_unscaled_sigma: float) -> float:
        if initial_unscaled_sigma == 0:
            return 100.0 if self.rating.sigma == 0 else 0.0
        return max(0.0, (1.0 - self.rating.sigma / initial_unscaled_sigma)) * 100.0


class _PlayerStub:
    """Lightweight player stub for constructing GameData from registry entries."""

    def __init__(self, name: str, team_id: int, winner: bool, handicap: int = 100):
        self.name = name
        self.team_id = team_id
        self.winner = winner
        self.handicap = handicap


class GameData:
    """Stores relevant information about a single game for TrueSkill calculation."""

    def __init__(
        self,
        filename: str,
        datetime_obj: datetime,
        human_players: list,
        teams_data: dict,
        winning_team_id: Optional[int],
        sha256: str = "",
    ):
        self.filename = filename
        self.datetime_obj = datetime_obj
        self.human_players = human_players
        self.teams_data = teams_data
        self.winning_team_id = winning_team_id
        self.sha256 = sha256

    @classmethod
    def from_registry_entry(cls, entry: Dict[str, Any]) -> Optional["GameData"]:
        """Create a lightweight GameData from a game registry entry.

        Constructs stub player objects with the attributes needed by
        TrueSkillCalculator.update_ratings_for_game() (name, team_id,
        winner, handicap) without parsing a replay file.
        """
        try:
            dt_str = entry.get("datetime", "")
            try:
                datetime_obj = datetime.fromisoformat(dt_str)
            except (ValueError, TypeError):
                datetime_obj = datetime.min

            teams_data = {}
            all_players = []
            for team_id_str, players_list in entry.get("teams", {}).items():
                team_id = int(team_id_str)
                team_players = []
                for p_info in players_list:
                    stub = _PlayerStub(
                        name=p_info["name"],
                        team_id=team_id,
                        winner=p_info.get("winner", False),
                        handicap=p_info.get("handicap", 100),
                    )
                    team_players.append(stub)
                    all_players.append(stub)
                teams_data[team_id] = team_players

            winning_team_id_raw = entry.get("winning_team_id")
            winning_team_id = (
                int(winning_team_id_raw) if winning_team_id_raw is not None else None
            )

            return cls(
                filename=entry.get("filename", ""),
                datetime_obj=datetime_obj,
                human_players=all_players,
                teams_data=teams_data,
                winning_team_id=winning_team_id,
                sha256=entry.get("sha256", ""),
            )
        except Exception as e:
            logging.warning(f"Failed to create GameData from registry entry: {e}")
            return None

    def get_player_handicaps(self) -> Dict[str, int]:
        """Returns a dict mapping player name -> handicap value (100 = normal)."""
        return {p.name: getattr(p, "handicap", 100) for p in self.human_players}

    def is_valid_for_rating(self) -> bool:
        if self.winning_team_id is None:
            logging.debug(f"Game {self.filename} invalid for rating: No clear winner.")
            return False
        if len(self.teams_data) != 2:
            logging.debug(
                f"Game {self.filename} invalid for rating: Not exactly 2 teams (found {len(self.teams_data)})."
            )
            return False

        team_player_lists = list(self.teams_data.values())
        if not team_player_lists[0] or not team_player_lists[1]:
            logging.debug(
                f"Game {self.filename} invalid for rating: At least one team has zero players."
            )
            return False
        return True


class TrueSkillCalculator:
    """Manages TrueSkill environment, player ratings, and updates."""

    def __init__(
        self, mu: float, sigma: float, beta: float, tau: float, draw_probability: float
    ):
        self.ts_env = trueskill.TrueSkill(
            mu=mu, sigma=sigma, beta=beta, tau=tau, draw_probability=draw_probability
        )
        self.player_ratings: Dict[str, PlayerRating] = {}
        self.rating_history: List[Dict[str, Any]] = []

    def get_or_create_player_rating(self, player_name: str) -> PlayerRating:
        if player_name not in self.player_ratings:
            self.player_ratings[player_name] = PlayerRating(
                player_name, self.ts_env.create_rating()
            )
        return self.player_ratings[player_name]

    def update_ratings_for_game(
        self, game_data: GameData, game_index: int
    ) -> Dict[str, float]:
        """Update ratings for all players in a game.

        Returns a dict mapping player_name -> rating delta (scaled mu change).
        Returns empty dict on error.
        """
        team_ids = list(game_data.teams_data.keys())
        team1_id, team2_id = team_ids[0], team_ids[1]

        team1_player_objs = game_data.teams_data[team1_id]
        team2_player_objs = game_data.teams_data[team2_id]

        player_handicaps = game_data.get_player_handicaps()

        team1_ratings_dict = {
            p.name: self.get_or_create_player_rating(p.name).rating
            for p in team1_player_objs
        }
        team2_ratings_dict = {
            p.name: self.get_or_create_player_rating(p.name).rating
            for p in team2_player_objs
        }

        if game_data.winning_team_id == team1_id:
            ranks = [0, 1]
        else:
            ranks = [1, 0]

        deltas = {}
        try:
            new_ratings_by_team = self.ts_env.rate(
                [team1_ratings_dict, team2_ratings_dict], ranks=ranks
            )

            updated_team1_ratings_map, updated_team2_ratings_map = (
                new_ratings_by_team[0],
                new_ratings_by_team[1],
            )

            for player_name, updated_map in [
                *[(n, updated_team1_ratings_map) for n in team1_ratings_dict],
                *[(n, updated_team2_ratings_map) for n in team2_ratings_dict],
            ]:
                player_rating_obj = self.get_or_create_player_rating(player_name)
                player_rating_obj.increment_games_rated()
                old_mu_scaled = player_rating_obj.get_scaled_mu()
                old_sigma_scaled = (
                    player_rating_obj.rating.sigma * config.TRUESKILL_ELO_SCALING_FACTOR
                )

                player_rating_obj.update_rating(updated_map[player_name])

                new_mu_scaled = player_rating_obj.get_scaled_mu()
                new_sigma_scaled = (
                    player_rating_obj.rating.sigma * config.TRUESKILL_ELO_SCALING_FACTOR
                )
                delta_mu = new_mu_scaled - old_mu_scaled
                delta_sigma = new_sigma_scaled - old_sigma_scaled
                deltas[player_name] = round(delta_mu, 2)
                handicap = player_handicaps.get(player_name, 100)
                handicap_str = f" [Handicap: {handicap}%]" if handicap > 100 else ""
                logging.debug(
                    f"Update | Game: {game_data.filename} | Player: {player_name:<15}{handicap_str} | "
                    f"mu: {old_mu_scaled:7.2f} -> {new_mu_scaled:7.2f} ({delta_mu:+.2f}) | "
                    f"sigma: {old_sigma_scaled:6.2f} -> {new_sigma_scaled:6.2f} ({delta_sigma:+.2f})"
                )
                self.rating_history.append(
                    {
                        "game_index": game_index,
                        "player_name": player_name,
                        "mu": player_rating_obj.get_scaled_mu(),
                        "sigma": player_rating_obj.rating.sigma
                        * config.TRUESKILL_ELO_SCALING_FACTOR,
                        "handicap": handicap,
                        "datetime": game_data.datetime_obj,
                    }
                )

        except Exception as e:
            logging.error(
                f"Error updating TrueSkill ratings for game {game_data.filename}: {type(e).__name__} - {repr(e)}"
            )

        return deltas


class ReportGenerator:
    """Generates textual and graphical reports for TrueSkill ratings."""

    def __init__(
        self,
        elo_scaling_factor: float,
        initial_unscaled_sigma: float,
        plot_min_games: int,
    ):
        self.elo_scaling_factor = elo_scaling_factor
        self.initial_unscaled_sigma = initial_unscaled_sigma
        self.plot_min_games_threshold = plot_min_games

    def print_final_rankings(
        self, player_ratings_map: Dict[str, PlayerRating], min_games_for_ranking: int
    ):
        logging.info("\n--- Final TrueSkill Player Rankings ---")

        all_players_sorted = sorted(
            player_ratings_map.values(), key=lambda p: p.rating.mu, reverse=True
        )

        ranked_players = [
            p for p in all_players_sorted if p.games_rated >= min_games_for_ranking
        ]
        provisional_players = [
            p for p in all_players_sorted if p.games_rated < min_games_for_ranking
        ]

        print(
            "\n--- Final TrueSkill Player Rankings ({} or more games) ---".format(
                min_games_for_ranking
            )
        )
        print("  Rank  Player               Mu (mu)    Confidence   Games")
        print("  -------------------------------------------------------------")
        if not ranked_players:
            print("  No players meet the minimum game requirement for ranking.")
        else:
            for i, p_rating in enumerate(ranked_players):
                mu_scaled = p_rating.get_scaled_mu()
                confidence = p_rating.get_confidence_percent(
                    self.initial_unscaled_sigma
                )
                print(
                    f"  {i+1:<5} {p_rating.name:<20} {mu_scaled:<10.2f} {confidence:>9.1f}%   {p_rating.games_played:>5}"
                )

        if provisional_players:
            print(
                "\n--- Provisional Ratings (Less than {} games) ---".format(
                    min_games_for_ranking
                )
            )
            print("        Player               Mu (mu)    Confidence   Games")
            print("  -------------------------------------------------------------")
            for p_rating in provisional_players:
                mu_scaled = p_rating.get_scaled_mu()
                confidence = p_rating.get_confidence_percent(
                    self.initial_unscaled_sigma
                )
                print(
                    f"        {p_rating.name:<20} {mu_scaled:<10.2f} {confidence:>9.1f}%   {p_rating.games_played:>5}"
                )
        print("\n  Higher Confidence indicates a more stable Mu rating.")

    def plot_rating_evolution(
        self,
        rating_history: List[Dict[str, Any]],
        lan_events: List[Dict[str, Any]] = None,
        output_filename: str = "trueskill_evolution.png",
    ):
        if not rating_history:
            logging.info("No rating history recorded, skipping plot generation.")
            return

        import pandas as pd
        import matplotlib.pyplot as plt
        import seaborn as sns

        df = pd.DataFrame(rating_history)
        plt.style.use("seaborn-v0_8-whitegrid")
        plt.figure(figsize=(18, 10))

        player_game_counts = df.groupby("player_name")["game_index"].nunique()
        players_to_plot = player_game_counts[
            player_game_counts > self.plot_min_games_threshold
        ].index
        df_filtered = df[df["player_name"].isin(players_to_plot)]

        if df_filtered.empty:
            logging.info(
                f"No players have enough games (>{self.plot_min_games_threshold}) to be plotted. Skipping plot generation."
            )
            return

        plt.figure(figsize=(15, 10))
        sns.set_style("whitegrid")
        sns.set_palette("tab20")

        df_plot = df[df["player_name"].isin(players_to_plot)]

        if df_plot.empty:
            logging.info("No players meet the minimum game threshold for plotting.")
            plt.close()
            return

        sns.lineplot(
            data=df_plot,
            x="game_index",
            y="mu",
            hue="player_name",
            legend="full",
            markers=True,
            dashes=False,
            linewidth=2.5,
        )

        for player_name_val in df_filtered["player_name"].unique():
            player_data = df_filtered[df_filtered["player_name"] == player_name_val]
            plt.fill_between(
                player_data["game_index"],
                player_data["mu"] - player_data["sigma"],
                player_data["mu"] + player_data["sigma"],
                alpha=0.2,
            )

        plt.title("TrueSkill Rating Evolution", fontsize=18, fontweight="bold")
        plt.xlabel("Game Index (Chronological)", fontsize=14)
        plt.ylabel(
            f"TrueSkill Rating (Scaled by {self.elo_scaling_factor})", fontsize=14
        )
        plt.legend(
            title="Player",
            bbox_to_anchor=(1.05, 1),
            loc="upper left",
            borderaxespad=0.0,
        )
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True, which="both", linestyle="--", linewidth=0.5)

        if lan_events:
            y_min, y_max = plt.ylim()
            for event in lan_events:
                plt.axvspan(
                    event["game_index_start"] - 0.5,
                    event["game_index_end"] + 0.5,
                    alpha=0.08,
                    color="#c9a84c",
                    zorder=0,
                )
                plt.axvline(
                    x=event["game_index_start"],
                    color="#c9a84c",
                    linestyle="--",
                    alpha=0.4,
                    linewidth=1,
                    zorder=1,
                )
                mid = (event["game_index_start"] + event["game_index_end"]) / 2
                plt.text(
                    mid,
                    y_max - (y_max - y_min) * 0.02,
                    event["label"],
                    ha="center",
                    va="top",
                    fontsize=7,
                    color="#b08930",
                    fontweight="bold",
                    rotation=90,
                )

        plt.tight_layout(rect=[0, 0, 0.85, 1])

        try:
            plot_dir = os.path.join(PROJECT_ROOT, "plots")
            os.makedirs(plot_dir, exist_ok=True)
            plot_path = os.path.join(plot_dir, output_filename)
            plt.savefig(plot_path)
            logging.info(f"Rating evolution plot saved to: {plot_path}")
        except Exception as e:
            logging.error(f"Error saving plot: {e}")
        finally:
            plt.close()


def detect_lan_events(rating_history, min_player_games=10):
    """Detect LAN party events from clusters of games played within a few days.

    A LAN event is a group of dates (at most 2-day gaps between consecutive days)
    where at least one player participated in ``min_player_games`` or more games.
    """
    game_dates = {}
    game_players = defaultdict(set)
    for h in rating_history:
        gi = h["game_index"]
        dt = h["datetime"]
        if dt.year > 1:  # skip datetime.min
            if gi not in game_dates:
                game_dates[gi] = dt
            game_players[gi].add(h["player_name"])

    if not game_dates:
        return []

    date_games = defaultdict(list)
    for gi, dt in game_dates.items():
        date_games[dt.date()].append(gi)

    sorted_dates = sorted(date_games.keys())
    if not sorted_dates:
        return []

    clusters = []
    current_cluster = [sorted_dates[0]]
    for i in range(1, len(sorted_dates)):
        if (sorted_dates[i] - sorted_dates[i - 1]).days <= 2:
            current_cluster.append(sorted_dates[i])
        else:
            clusters.append(current_cluster)
            current_cluster = [sorted_dates[i]]
    clusters.append(current_cluster)

    lan_events = []
    for cluster in clusters:
        all_gis = []
        for d in cluster:
            all_gis.extend(date_games[d])

        player_counts = defaultdict(int)
        for gi in all_gis:
            for name in game_players[gi]:
                player_counts[name] += 1

        if max(player_counts.values(), default=0) >= min_player_games:
            lan_events.append(
                {
                    "start_date": cluster[0].isoformat(),
                    "end_date": cluster[-1].isoformat(),
                    "game_index_start": min(all_gis),
                    "game_index_end": max(all_gis),
                    "num_games": len(all_gis),
                    "label": f"LAN {cluster[0].strftime('%d %b %y')}",
                }
            )

    return lan_events


def run_trueskill_from_registry(registry_games, data_dir=None):
    """Rebuild TrueSkill ratings from game registry entries.

    Takes a list of game entries (status "processed" and "no_winner"),
    constructs lightweight GameData objects from registry metadata,
    sorts chronologically, processes through TrueSkillCalculator, and
    saves player_ratings.json and rating_history.json.

    Args:
        registry_games: List of game dicts from the registry (status="processed").
        data_dir: Optional base directory for output files. Defaults to PROJECT_ROOT.

    Returns:
        (player_ratings_map, rating_history, lan_events, rating_deltas) tuple,
        where rating_deltas is a dict mapping sha256 -> {player_name -> delta}.
    """
    output_dir = data_dir or PROJECT_ROOT

    ts_params = dict(
        mu=config.TRUESKILL_MU,
        sigma=config.TRUESKILL_SIGMA,
        beta=config.TRUESKILL_BETA,
        tau=config.TRUESKILL_TAU,
        draw_probability=config.TRUESKILL_DRAW_PROBABILITY,
    )
    calculator = TrueSkillCalculator(**ts_params)
    reporter = ReportGenerator(
        elo_scaling_factor=config.TRUESKILL_ELO_SCALING_FACTOR,
        initial_unscaled_sigma=config.TRUESKILL_SIGMA,
        plot_min_games=PLOT_MIN_GAMES_THRESHOLD,
    )

    sorted_games = sorted(registry_games, key=lambda g: g.get("datetime", ""))

    game_index_rated = 0
    rating_deltas = {}  # sha256 -> {player_name -> delta}

    for entry in sorted_games:
        game_data = GameData.from_registry_entry(entry)
        if not game_data:
            continue

        for player_obj in game_data.human_players:
            player_rating = calculator.get_or_create_player_rating(player_obj.name)
            player_rating.increment_games_played()

        if not game_data.is_valid_for_rating():
            continue

        game_index_rated += 1
        deltas = calculator.update_ratings_for_game(game_data, game_index_rated)
        if game_data.sha256 and deltas:
            rating_deltas[game_data.sha256] = deltas

    lan_events = detect_lan_events(calculator.rating_history)

    # Build ratings list
    ratings_list = []
    for player_name, player_rating_obj in calculator.player_ratings.items():
        player_history = [
            h for h in calculator.rating_history if h["player_name"] == player_name
        ]
        last_30 = player_history[-30:]
        last_30_handicaps = [h.get("handicap", 100) for h in last_30]
        avg_hc = (
            round(sum(last_30_handicaps) / len(last_30_handicaps), 1)
            if last_30_handicaps
            else 100.0
        )
        ratings_list.append(
            {
                "name": player_name,
                "mu_scaled": round(player_rating_obj.get_scaled_mu(), 2),
                "sigma_scaled": round(
                    player_rating_obj.rating.sigma
                    * config.TRUESKILL_ELO_SCALING_FACTOR,
                    2,
                ),
                "mu_unscaled": round(player_rating_obj.rating.mu, 4),
                "sigma_unscaled": round(player_rating_obj.rating.sigma, 4),
                "games_played": player_rating_obj.games_played,
                "games_rated": player_rating_obj.games_rated,
                "confidence_percent": round(
                    player_rating_obj.get_confidence_percent(config.TRUESKILL_SIGMA), 1
                ),
                "avg_handicap_last_30": avg_hc,
            }
        )
    ratings_list.sort(key=lambda x: x["mu_scaled"], reverse=True)

    # Build rating history
    serializable_history = [
        {
            "game_index": h["game_index"],
            "player_name": h["player_name"],
            "mu": round(h["mu"], 2),
            "sigma": round(h["sigma"], 2),
        }
        for h in calculator.rating_history
    ]

    # Save to SQLite database
    from analyzer_lib import db as db_module

    db_path = db_module.get_db_path(output_dir)
    db_module.save_player_ratings(db_path, ratings_list)
    db_module.save_rating_history(db_path, serializable_history, lan_events or [])
    logging.info(f"Ratings and history saved to database: {db_path}")

    return (
        calculator.player_ratings,
        calculator.rating_history,
        lan_events,
        rating_deltas,
    )


def main():
    """Standalone entry point: load registry, run TrueSkill from it."""
    from server.processing import GameRegistry

    registry = GameRegistry(data_dir=config.DATA_DIR)
    ratable_games = registry.get_games(status="processed")
    if not ratable_games:
        logging.error("No processed games in registry. Run main.py first.")
        return
    logging.info(
        f"Running TrueSkill on {len(ratable_games)} games from registry..."
    )
    run_trueskill_from_registry(ratable_games, data_dir=config.DATA_DIR)
    logging.info("Done.")


if __name__ == "__main__":
    main()
