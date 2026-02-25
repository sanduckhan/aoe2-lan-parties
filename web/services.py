import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

import trueskill
from analyzer_lib import config
from handicap_recommender import recommended_handicap
from team_balancer import find_balanced_teams, suggest_rebalances_data

RATINGS_PATH = os.path.join(PROJECT_ROOT, "player_ratings.json")


def _get_ts_env() -> trueskill.TrueSkill:
    return trueskill.TrueSkill(
        beta=config.TRUESKILL_BETA,
        draw_probability=config.TRUESKILL_DRAW_PROBABILITY,
    )


def load_ratings() -> List[Dict[str, Any]]:
    with open(RATINGS_PATH, "r") as f:
        return json.load(f)


def _ratings_dict() -> Dict[str, Dict[str, Any]]:
    return {p["name"]: p for p in load_ratings()}


def _player_info(data: Dict[str, Any]) -> Dict[str, Any]:
    avg_hc = data.get("avg_handicap_last_30", 100)
    info = {
        "name": data["name"],
        "mu_scaled": round(data["mu_scaled"], 1),
        "sigma_scaled": round(data["sigma_scaled"], 2),
        "games_played": data["games_played"],
        "confidence_percent": round(data["confidence_percent"], 1),
        "avg_handicap_last_30": avg_hc,
        "recommended_hc": recommended_handicap(data["mu_scaled"], avg_hc),
    }
    return info


def get_players_for_api() -> Dict[str, Any]:
    ratings = load_ratings()
    ranked = sorted(
        [r for r in ratings if r["games_played"] >= config.MIN_GAMES_FOR_RANKING],
        key=lambda r: r["mu_scaled"],
        reverse=True,
    )
    provisional = sorted(
        [r for r in ratings if r["games_played"] < config.MIN_GAMES_FOR_RANKING],
        key=lambda r: r["mu_scaled"],
        reverse=True,
    )
    return {
        "ranked": [_player_info(p) for p in ranked],
        "provisional": [_player_info(p) for p in provisional],
        "min_games_for_ranking": config.MIN_GAMES_FOR_RANKING,
    }


def _build_ts_ratings(
    names: List[str], ratings_data: Dict[str, Dict[str, Any]]
) -> Dict[str, trueskill.Rating]:
    return {
        n: trueskill.Rating(
            mu=ratings_data[n]["mu_unscaled"],
            sigma=ratings_data[n]["sigma_unscaled"],
        )
        for n in names
    }


def _enrich_suggestion(
    quality: float,
    team1_names: List[str],
    team2_names: List[str],
    ratings_data: Dict[str, Dict[str, Any]],
    player_ts_ratings: Dict[str, trueskill.Rating],
    ts_env: trueskill.TrueSkill,
) -> Dict[str, Any]:
    def p_info(name):
        data = ratings_data[name]
        avg_hc = data.get("avg_handicap_last_30", 100)
        return {
            "name": name,
            "rating": round(data["mu_scaled"], 1),
            "recommended_hc": recommended_handicap(data["mu_scaled"], avg_hc),
            "games_played": data["games_played"],
        }

    t1_sorted = sorted(team1_names)
    t2_sorted = sorted(team2_names)
    team1_info = [p_info(n) for n in t1_sorted]
    team2_info = [p_info(n) for n in t2_sorted]

    # Simulate rating changes
    team1_ratings = tuple(player_ts_ratings[n] for n in t1_sorted)
    team2_ratings = tuple(player_ts_ratings[n] for n in t2_sorted)
    rating_changes = {}
    elo_factor = config.TRUESKILL_ELO_SCALING_FACTOR

    if team1_ratings and team2_ratings:
        t1_wins = ts_env.rate([team1_ratings, team2_ratings], ranks=[0, 1])
        t2_wins = ts_env.rate([team1_ratings, team2_ratings], ranks=[1, 0])

        for idx, name in enumerate(t1_sorted):
            old_mu = team1_ratings[idx].mu
            rating_changes[name] = {
                "win": round((t1_wins[0][idx].mu - old_mu) * elo_factor, 2),
                "loss": round((t2_wins[0][idx].mu - old_mu) * elo_factor, 2),
            }
        for idx, name in enumerate(t2_sorted):
            old_mu = team2_ratings[idx].mu
            rating_changes[name] = {
                "win": round((t2_wins[1][idx].mu - old_mu) * elo_factor, 2),
                "loss": round((t1_wins[1][idx].mu - old_mu) * elo_factor, 2),
            }

    # Expected winner
    t1_mu = sum(player_ts_ratings[n].mu for n in team1_names)
    t2_mu = sum(player_ts_ratings[n].mu for n in team2_names)
    if abs(t1_mu - t2_mu) < 0.01:
        expected_winner = "Too close to call"
    elif t1_mu > t2_mu:
        expected_winner = "Team 1"
    else:
        expected_winner = "Team 2"

    return {
        "match_quality": round(quality * 100, 2),
        "team1": team1_info,
        "team2": team2_info,
        "expected_winner": expected_winner,
        "rating_changes": rating_changes,
    }


def generate_teams(
    player_names: List[str], top_n: int = 3
) -> Dict[str, Any]:
    ratings_data = _ratings_dict()

    valid = []
    warnings = []
    for name in player_names:
        if name in ratings_data:
            valid.append(name)
        else:
            warnings.append(f"Player '{name}' not found in ratings")

    if len(valid) < 2:
        return {"error": "Need at least 2 players with ratings", "warnings": warnings}

    ts_env = _get_ts_env()
    player_ts_ratings = _build_ts_ratings(valid, ratings_data)
    balanced = find_balanced_teams(player_ts_ratings, ts_env, top_n=top_n)

    suggestions = []
    for quality, t1, t2 in balanced:
        suggestions.append(
            _enrich_suggestion(quality, t1, t2, ratings_data, player_ts_ratings, ts_env)
        )

    return {"suggestions": suggestions, "warnings": warnings}


def rebalance_teams(
    team1: List[str], team2: List[str], weaker_team: int, top_n: int = 5
) -> Dict[str, Any]:
    ratings_data = _ratings_dict()

    all_names = list(set(team1 + team2))
    missing = [n for n in all_names if n not in ratings_data]
    if missing:
        return {"error": f"Players not found in ratings: {', '.join(missing)}"}

    ts_env = _get_ts_env()
    player_ts_ratings = _build_ts_ratings(all_names, ratings_data)

    return suggest_rebalances_data(
        team1, team2, weaker_team,
        player_ts_ratings, ratings_data, ts_env, top_n=top_n,
    )
