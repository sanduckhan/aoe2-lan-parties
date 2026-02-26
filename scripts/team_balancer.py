#!/usr/bin/env python3
import argparse
import itertools
import os
import sys
from typing import List, Dict, Tuple, Any

# --- Add project root to sys.path to allow importing config from analyzer_lib ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
ANALYZER_LIB_PATH = os.path.join(PROJECT_ROOT, "analyzer_lib")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, ANALYZER_LIB_PATH)

try:
    from analyzer_lib import config, db

    TS_BETA = config.TRUESKILL_BETA
    TS_DRAW_PROBABILITY = config.TRUESKILL_DRAW_PROBABILITY
    ELO_SCALING_FACTOR = config.TRUESKILL_ELO_SCALING_FACTOR
except ImportError as e:
    TS_MU = 25.0
    TS_SIGMA = TS_MU / 3.0
    TS_BETA = TS_SIGMA / 2.0
    TS_DRAW_PROBABILITY = 0.10
    ELO_SCALING_FACTOR = 40

import trueskill
from handicap_recommender import recommended_handicap

MAX_TEAM_SIZE = 4  # AoE2 DE supports up to 4v4


def load_player_ratings() -> Dict[str, Dict[str, Any]]:
    """Loads player ratings from the SQLite database."""
    db_path = db.get_db_path(config.DATA_DIR)
    ratings_list = db.load_player_ratings(db_path)
    if not ratings_list:
        print("Error: No player ratings found in database.")
        print("Please run main.py first to generate ratings.")
        sys.exit(1)
    return {player["name"]: player for player in ratings_list}


def suggest_rebalances_data(
    team1_names: List[str],
    team2_names: List[str],
    weaker_team: int,
    player_ts_ratings: Dict[str, trueskill.Rating],
    all_ratings_data: Dict[str, Dict[str, Any]],
    ts_env: trueskill.TrueSkill,
    top_n: int = 5,
) -> Dict[str, Any]:
    """Return structured rebalance data instead of printing."""
    if weaker_team == 1:
        weak_names, strong_names = list(team1_names), list(team2_names)
    else:
        weak_names, strong_names = list(team2_names), list(team1_names)

    def team_mu_scaled(names):
        return sum(all_ratings_data[n]["mu_scaled"] for n in names)

    def team_quality(t1, t2):
        r1 = tuple(player_ts_ratings[n] for n in t1)
        r2 = tuple(player_ts_ratings[n] for n in t2)
        if not r1 or not r2:
            return 0.0
        return ts_env.quality([r1, r2])

    def player_info(name):
        data = all_ratings_data[name]
        avg_hc = data.get("avg_handicap_last_30", 100)
        return {
            "name": name,
            "rating": data["mu_scaled"],
            "recommended_hc": recommended_handicap(data["mu_scaled"], avg_hc),
            "games_played": data["games_played"],
        }

    current_weak_mu = team_mu_scaled(weak_names)
    current_quality = team_quality(team1_names, team2_names)
    t1_avg = team_mu_scaled(team1_names) / len(team1_names)
    t2_avg = team_mu_scaled(team2_names) / len(team2_names)

    result = {
        "current_setup": {
            "team1": [player_info(n) for n in sorted(team1_names)],
            "team2": [player_info(n) for n in sorted(team2_names)],
            "team1_avg_rating": round(t1_avg, 0),
            "team2_avg_rating": round(t2_avg, 0),
            "weaker_team": weaker_team,
            "match_quality": round(current_quality * 100, 2),
        },
        "suggestions": [],
    }

    candidates = []  # (mu_gain_for_weak, description, new_t1, new_t2)

    # Swaps: one from strong team <-> one from weak team
    for s in strong_names:
        for w in weak_names:
            new_weak = [p for p in weak_names if p != w] + [s]
            new_strong = [p for p in strong_names if p != s] + [w]
            if weaker_team == 1:
                new_t1, new_t2 = new_weak, new_strong
            else:
                new_t1, new_t2 = new_strong, new_weak
            new_weak_mu = team_mu_scaled(new_weak)
            gain = new_weak_mu - current_weak_mu
            if gain > 0:
                candidates.append((gain, f"Swap {w} \u2194 {s}", new_t1, new_t2))

    # Moves: one player from strong team to weak team (only if weak team has room)
    for s in strong_names:
        new_weak = weak_names + [s]
        new_strong = [p for p in strong_names if p != s]
        if not new_strong:
            continue
        if len(new_weak) > MAX_TEAM_SIZE:
            continue
        if weaker_team == 1:
            new_t1, new_t2 = new_weak, new_strong
        else:
            new_t1, new_t2 = new_strong, new_weak
        new_weak_mu = team_mu_scaled(new_weak)
        gain = new_weak_mu - current_weak_mu
        if gain > 0:
            candidates.append((gain, f"Move {s} to Team {weaker_team}", new_t1, new_t2))

    # Sort by smallest gain first (least disruption)
    candidates.sort(key=lambda x: x[0])

    for gain, desc, new_t1, new_t2 in candidates[:top_n]:
        quality = team_quality(new_t1, new_t2)
        result["suggestions"].append(
            {
                "description": desc,
                "team1": [player_info(n) for n in sorted(new_t1)],
                "team2": [player_info(n) for n in sorted(new_t2)],
                "rating_gain": round(gain, 0),
                "match_quality": round(quality * 100, 2),
            }
        )

    return result


def suggest_rebalances(
    team1_names: List[str],
    team2_names: List[str],
    weaker_team: int,
    player_ts_ratings: Dict[str, trueskill.Rating],
    all_ratings_data: Dict[str, Dict[str, Any]],
    ts_env: trueskill.TrueSkill,
    top_n: int = 5,
):
    """Suggest minimal changes (swaps/moves) to help the weaker team."""
    data = suggest_rebalances_data(
        team1_names,
        team2_names,
        weaker_team,
        player_ts_ratings,
        all_ratings_data,
        ts_env,
        top_n,
    )

    setup = data["current_setup"]
    weak_label = lambda t: " (weaker)" if t == setup["weaker_team"] else ""
    fmt = lambda p: f"{p['name']} ({p['recommended_hc']}%)"

    print(f"\n--- Current Setup ---")
    print(f"  Team 1{weak_label(1)}: {', '.join(fmt(p) for p in setup['team1'])}")
    print(f"  Team 2{weak_label(2)}: {', '.join(fmt(p) for p in setup['team2'])}")
    print(
        f"  Team 1 Avg Rating: {setup['team1_avg_rating']:.0f}  |  Team 2 Avg Rating: {setup['team2_avg_rating']:.0f}"
    )
    print(f"  Match Quality: {setup['match_quality']:.2f}%")

    if not data["suggestions"]:
        print("\n  No single swap or move can help the weaker team.")
        return

    print(
        f"\n--- Suggestions to help Team {setup['weaker_team']} (smallest change first) ---"
    )
    for i, s in enumerate(data["suggestions"]):
        print(f"\n  #{i+1}: {s['description']}")
        print(f"    Team 1: {', '.join(fmt(p) for p in s['team1'])}")
        print(f"    Team 2: {', '.join(fmt(p) for p in s['team2'])}")
        print(
            f"    Team {setup['weaker_team']} gains +{s['rating_gain']:.0f} rating  |  Match Quality: {s['match_quality']:.2f}%"
        )


def find_balanced_teams(
    player_ts_ratings: Dict[str, trueskill.Rating],
    ts_env: trueskill.TrueSkill,
    top_n: int = 3,
) -> List[Tuple[float, List[str], List[str], List[str]]]:
    """
    Finds the most balanced team combinations for a given list of players.
    When more than MAX_TEAM_SIZE*2 players are provided, some will be benched.
    Returns a list of tuples: (quality_score, team1_names, team2_names, benched_names)
    """
    players = list(player_ts_ratings.keys())
    num_players = len(players)

    if num_players < 2:
        print("Need at least 2 players to form two teams.")
        return []

    possible_matchups = []
    processed_matchups = set()
    players_set = set(players)
    needs_bench = num_players > MAX_TEAM_SIZE * 2

    for team1_size in range(1, min(num_players, MAX_TEAM_SIZE) + 1):
        for team1_tuple in itertools.combinations(players, team1_size):
            team1_names = list(team1_tuple)
            remaining = [p for p in players if p not in team1_names]

            if needs_bench:
                # Allow benching: team2 can be any size from team1_size to MAX_TEAM_SIZE
                min_t2 = team1_size
                max_t2 = min(MAX_TEAM_SIZE, len(remaining))
            else:
                # No bench: team2 is everyone else (original behavior)
                if len(remaining) > MAX_TEAM_SIZE or len(remaining) < 1:
                    continue
                min_t2 = len(remaining)
                max_t2 = len(remaining)

            for team2_size in range(min_t2, max_t2 + 1):
                for team2_tuple in itertools.combinations(remaining, team2_size):
                    team2_names = list(team2_tuple)

                    canonical = tuple(
                        sorted((tuple(sorted(team1_names)), tuple(sorted(team2_names))))
                    )
                    if canonical in processed_matchups:
                        continue
                    processed_matchups.add(canonical)

                    t1_ratings = tuple(player_ts_ratings[n] for n in team1_names)
                    t2_ratings = tuple(player_ts_ratings[n] for n in team2_names)

                    quality = ts_env.quality([t1_ratings, t2_ratings])
                    benched = sorted(players_set - set(team1_names) - set(team2_names))
                    possible_matchups.append(
                        (quality, sorted(team1_names), sorted(team2_names), benched)
                    )

    # Sort: fewest benched first (maximize players in game), then by quality descending
    possible_matchups.sort(key=lambda x: (len(x[3]), -x[0]))

    return possible_matchups[:top_n]


def main():
    parser = argparse.ArgumentParser(
        description="Suggest balanced teams for AoE2 LAN parties based on TrueSkill ratings."
    )
    parser.add_argument(
        "players",
        nargs="*",
        help="A list of player names to form teams from (generation mode).",
    )
    parser.add_argument(
        "--team1", nargs="+", default=None, help="Team 1 player names (rebalance mode)."
    )
    parser.add_argument(
        "--team2", nargs="+", default=None, help="Team 2 player names (rebalance mode)."
    )
    parser.add_argument(
        "--weaker",
        type=int,
        choices=[1, 2],
        default=None,
        help="Which team is weaker (1 or 2).",
    )
    parser.add_argument(
        "--top_n", type=int, default=3, help="Number of top suggestions to show."
    )

    args = parser.parse_args()

    rebalance_mode = args.team1 is not None and args.team2 is not None
    if rebalance_mode and args.weaker is None:
        print(
            "Error: --weaker is required in rebalance mode (--team1 ... --team2 ... --weaker 1|2)"
        )
        sys.exit(1)
    if rebalance_mode and (
        len(args.team1) > MAX_TEAM_SIZE or len(args.team2) > MAX_TEAM_SIZE
    ):
        print(
            f"Error: Each team can have at most {MAX_TEAM_SIZE} players (AoE2 {MAX_TEAM_SIZE}v{MAX_TEAM_SIZE} max)."
        )
        sys.exit(1)
    if not rebalance_mode and not args.players:
        print(
            "Error: Provide player names, or use --team1 ... --team2 ... --weaker 1|2 for rebalance mode."
        )
        sys.exit(1)
    if not rebalance_mode and len(args.players) > MAX_TEAM_SIZE * 2:
        print(
            f"Note: {len(args.players)} players selected. Some will be benched per suggestion (max {MAX_TEAM_SIZE}v{MAX_TEAM_SIZE})."
        )

    all_player_ratings_data = load_player_ratings()
    ts_env = trueskill.TrueSkill(beta=TS_BETA, draw_probability=TS_DRAW_PROBABILITY)

    if rebalance_mode:
        all_names = list(set(args.team1 + args.team2))
        missing = [n for n in all_names if n not in all_player_ratings_data]
        if missing:
            print(f"Error: Players not found in ratings: {', '.join(missing)}")
            sys.exit(1)
        player_ts_ratings = {
            n: trueskill.Rating(
                mu=all_player_ratings_data[n]["mu_unscaled"],
                sigma=all_player_ratings_data[n]["sigma_unscaled"],
            )
            for n in all_names
        }
        suggest_rebalances(
            args.team1,
            args.team2,
            args.weaker,
            player_ts_ratings,
            all_player_ratings_data,
            ts_env,
            top_n=args.top_n,
        )
        return

    requested_player_names = sorted(list(set(args.players)))

    if len(requested_player_names) < 2:
        print("Error: Please provide at least two unique player names.")
        sys.exit(1)

    print(f"Attempting to balance teams for: {', '.join(requested_player_names)}")

    player_ts_ratings: Dict[str, trueskill.Rating] = {}
    valid_player_names_for_balancing = []
    missing_players_from_ratings = []

    for name in requested_player_names:
        if name in all_player_ratings_data:
            player_data = all_player_ratings_data[name]
            player_ts_ratings[name] = trueskill.Rating(
                mu=player_data["mu_unscaled"], sigma=player_data["sigma_unscaled"]
            )
            valid_player_names_for_balancing.append(name)
        else:
            missing_players_from_ratings.append(name)

    if missing_players_from_ratings:
        print(
            f"\nWarning: The following players were not found in the ratings database and will be excluded:"
        )
        for p_name in sorted(missing_players_from_ratings):
            print(f"  - {p_name}")

        if not valid_player_names_for_balancing:
            print(
                "\nError: None of the provided players were found in the ratings file. Exiting."
            )
            sys.exit(1)
        print(
            f"\nProceeding with balancing for: {', '.join(sorted(valid_player_names_for_balancing))}\n"
        )
    else:
        print("All requested players found in ratings file.\n")

    if len(valid_player_names_for_balancing) < 2:
        print("Error: Need at least two players with available ratings to form teams.")
        sys.exit(1)

    # Filter player_ts_ratings to only include valid players for find_balanced_teams
    final_player_ts_ratings = {
        name: rating
        for name, rating in player_ts_ratings.items()
        if name in valid_player_names_for_balancing
    }

    balanced_teams = find_balanced_teams(
        final_player_ts_ratings, ts_env, top_n=args.top_n
    )

    if not balanced_teams:
        print(
            "Could not find any balanced team combinations (perhaps too few players after filtering or an issue in logic)."
        )
    else:
        print(
            f"--- Top {min(args.top_n, len(balanced_teams))} Most Balanced Team Combinations ---"
        )
        print(
            f"(Based on TrueSkill Beta: {TS_BETA:.4f}, a configured draw probability of {TS_DRAW_PROBABILITY*100:.1f}% is used for rating updates)"
        )
        print(
            "Match Quality is the calculated probability of a draw. A higher percentage indicates a more balanced and unpredictable game."
        )

        def fmt_player(name):
            data = all_player_ratings_data[name]
            avg_hc = data.get("avg_handicap_last_30", 100)
            rec = recommended_handicap(data["mu_scaled"], avg_hc)
            return f"{name} ({rec}%)"

        for i, (
            quality,
            team1_names_sorted,
            team2_names_sorted,
            benched_names,
        ) in enumerate(balanced_teams):
            print(f"\n--- Suggestion #{i+1} ---")
            print(f"Match Quality: {quality*100:.2f}%")
            print(f"  Team 1: {', '.join(fmt_player(n) for n in team1_names_sorted)}")
            print(f"  Team 2: {', '.join(fmt_player(n) for n in team2_names_sorted)}")
            if benched_names:
                print(f"  Benched: {', '.join(benched_names)}")

            # Determine Expected Winner by comparing sum of ratings
            team1_mu_sum = sum(
                final_player_ts_ratings[name].mu for name in team1_names_sorted
            )
            team2_mu_sum = sum(
                final_player_ts_ratings[name].mu for name in team2_names_sorted
            )

            if abs(team1_mu_sum - team2_mu_sum) < 0.01:  # Arbitrary small threshold
                expected_winner = "Too close to call"
            elif team1_mu_sum > team2_mu_sum:
                expected_winner = "Team 1"
            else:
                expected_winner = "Team 2"
            print(f"  Expected Winner: {expected_winner}")

            # --- Simulate outcomes and store deltas ---
            team1_ratings = tuple(
                final_player_ts_ratings[name] for name in team1_names_sorted
            )
            team2_ratings = tuple(
                final_player_ts_ratings[name] for name in team2_names_sorted
            )

            potential_changes = {}

            if team1_ratings and team2_ratings:
                # Simulate Team 1 winning (Team 2 loses)
                t1_wins_ratings = ts_env.rate(
                    [team1_ratings, team2_ratings], ranks=[0, 1]
                )
                # Simulate Team 2 winning (Team 1 loses)
                t2_wins_ratings = ts_env.rate(
                    [team1_ratings, team2_ratings], ranks=[1, 0]
                )

                # Populate changes for Team 1 players
                for idx, player_name in enumerate(team1_names_sorted):
                    old_mu = team1_ratings[idx].mu
                    potential_changes[player_name] = {
                        "win": (t1_wins_ratings[0][idx].mu - old_mu)
                        * ELO_SCALING_FACTOR,
                        "loss": (t2_wins_ratings[0][idx].mu - old_mu)
                        * ELO_SCALING_FACTOR,
                    }

                # Populate changes for Team 2 players
                for idx, player_name in enumerate(team2_names_sorted):
                    old_mu = team2_ratings[idx].mu
                    potential_changes[player_name] = {
                        "win": (t2_wins_ratings[1][idx].mu - old_mu)
                        * ELO_SCALING_FACTOR,
                        "loss": (t1_wins_ratings[1][idx].mu - old_mu)
                        * ELO_SCALING_FACTOR,
                    }

            # --- Print the simplified summary ---
            if potential_changes:
                print("\n  Potential Rating Changes (Win / Loss):")
                print("    Team 1:")
                for player_name in team1_names_sorted:
                    changes = potential_changes[player_name]
                    print(
                        f"      {player_name:<16}: {changes['win']:+6.2f} / {changes['loss']:+6.2f}"
                    )
                print("    Team 2:")
                for player_name in team2_names_sorted:
                    changes = potential_changes[player_name]
                    print(
                        f"      {player_name:<16}: {changes['win']:+6.2f} / {changes['loss']:+6.2f}"
                    )


if __name__ == "__main__":
    main()
