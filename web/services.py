import hashlib
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

import trueskill
from analyzer_lib import config
from handicap_recommender import recommended_handicap
from team_balancer import find_balanced_teams, suggest_rebalances_data

logger = logging.getLogger(__name__)

RATINGS_PATH = os.path.join(config.DATA_DIR, "player_ratings.json")
ANALYSIS_DATA_PATH = os.path.join(config.DATA_DIR, "analysis_data.json")
RATING_HISTORY_PATH = os.path.join(config.DATA_DIR, "rating_history.json")
GAME_REGISTRY_PATH = os.path.join(config.DATA_DIR, "game_registry.json")


class MtimeCache:
    """Cache that auto-reloads a JSON file when its mtime changes on disk."""

    def __init__(self, path):
        self._path = path
        self._data = None
        self._mtime = 0

    def get(self):
        try:
            current_mtime = os.path.getmtime(self._path)
        except FileNotFoundError:
            return None
        if self._data is None or current_mtime > self._mtime:
            with open(self._path, "r") as f:
                self._data = json.load(f)
            self._mtime = current_mtime
        return self._data


_analysis_cache = MtimeCache(ANALYSIS_DATA_PATH)
_ratings_cache = MtimeCache(RATINGS_PATH)
_rating_history_cache = MtimeCache(RATING_HISTORY_PATH)
_game_registry_cache = MtimeCache(GAME_REGISTRY_PATH)

# Lazy singleton for IncrementalProcessor
_processor = None


def _get_ts_env() -> trueskill.TrueSkill:
    return trueskill.TrueSkill(
        beta=config.TRUESKILL_BETA,
        draw_probability=config.TRUESKILL_DRAW_PROBABILITY,
    )


def load_ratings() -> List[Dict[str, Any]]:
    data = _ratings_cache.get()
    if data is None:
        raise FileNotFoundError(f"Ratings file not found: {RATINGS_PATH}")
    return data


def _ratings_dict() -> Dict[str, Dict[str, Any]]:
    return {p["name"]: p for p in load_ratings()}


def _player_info(data: Dict[str, Any]) -> Dict[str, Any]:
    avg_hc = data.get("avg_handicap_last_30", 100)
    info = {
        "name": data["name"],
        "mu_scaled": round(data["mu_scaled"], 1),
        "sigma_scaled": round(data["sigma_scaled"], 2),
        "games_played": data["games_played"],
        "games_rated": data.get("games_rated", data["games_played"]),
        "confidence_percent": round(data["confidence_percent"], 1),
        "avg_handicap_last_30": avg_hc,
        "recommended_hc": recommended_handicap(data["mu_scaled"], avg_hc),
    }
    return info


def get_players_for_api() -> Dict[str, Any]:
    ratings = load_ratings()
    ranked = sorted(
        [r for r in ratings if r.get("games_rated", r["games_played"]) >= config.MIN_GAMES_FOR_RANKING],
        key=lambda r: r["mu_scaled"],
        reverse=True,
    )
    provisional = sorted(
        [r for r in ratings if r.get("games_rated", r["games_played"]) < config.MIN_GAMES_FOR_RANKING],
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
    for quality, t1, t2, benched in balanced:
        enriched = _enrich_suggestion(
            quality, t1, t2, ratings_data, player_ts_ratings, ts_env
        )
        enriched["benched"] = [
            {"name": n, "rating": round(ratings_data[n]["mu_scaled"], 1)}
            for n in benched
        ]
        suggestions.append(enriched)

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


# --- New API service functions ---

def _load_analysis_data() -> Dict[str, Any]:
    data = _analysis_cache.get()
    if data is None:
        raise FileNotFoundError(f"Analysis data not found: {ANALYSIS_DATA_PATH}")
    return data


def get_awards_for_api() -> Dict[str, Any]:
    data = _load_analysis_data()
    return data["awards"]


def get_games_for_api() -> Dict[str, Any]:
    data = _load_analysis_data()
    games = data["game_results"]
    formatted = []
    for g in games:
        winning_team_id = g.get("winning_team_id")
        teams_list = []
        for tid, players in g["teams"].items():
            teams_list.append({
                "team_id": tid,
                "players": players,
                "is_winner": (tid == winning_team_id),
            })
        formatted.append({
            "filename": g["filename"],
            "datetime": g["datetime"],
            "duration_seconds": g["duration_seconds"],
            "duration_display": str(timedelta(seconds=int(g["duration_seconds"]))),
            "teams": teams_list,
            "has_winner": winning_team_id is not None,
        })
    formatted.sort(key=lambda g: g["datetime"], reverse=True)
    return {"games": formatted, "total": len(formatted)}


def get_stats_for_api() -> Dict[str, Any]:
    data = _load_analysis_data()
    return data["general_stats"]


def get_player_profile_for_api(name: str) -> Optional[Dict[str, Any]]:
    data = _load_analysis_data()
    profiles = data.get("player_profiles", {})

    # Try exact match, then case-insensitive
    profile = profiles.get(name)
    if profile is None:
        for pname, pdata in profiles.items():
            if pname.lower() == name.lower():
                profile = pdata
                break

    if profile is None:
        return None

    # Make a copy to avoid mutating the cache
    profile = dict(profile)

    # Enrich with rating data from player_ratings.json
    try:
        ratings_data = _ratings_dict()
        canonical_name = profile["name"]
        if canonical_name in ratings_data:
            rd = ratings_data[canonical_name]
            avg_hc = rd.get("avg_handicap_last_30", 100)
            profile["rating"] = {
                "mu_scaled": round(rd["mu_scaled"], 1),
                "sigma_scaled": round(rd["sigma_scaled"], 2),
                "confidence_percent": round(rd["confidence_percent"], 1),
                "avg_handicap_last_30": avg_hc,
                "recommended_hc": recommended_handicap(rd["mu_scaled"], avg_hc),
            }
    except FileNotFoundError:
        pass

    # Compute trend from rating history
    try:
        history_data = get_rating_history_for_api()
        player_history = [h for h in history_data["history"] if h["player_name"] == profile["name"]]
        if len(player_history) >= 2:
            latest = player_history[-1]["mu"]
            earlier_idx = max(0, len(player_history) - 6)
            earlier = player_history[earlier_idx]["mu"]
            profile["trend"] = round(latest - earlier, 1)
        else:
            profile["trend"] = 0
    except FileNotFoundError:
        profile["trend"] = 0

    return profile


def get_rating_history_for_api() -> Dict[str, Any]:
    data = _rating_history_cache.get()
    if data is None:
        raise FileNotFoundError(f"Rating history not found: {RATING_HISTORY_PATH}")
    # Support both old format (flat list) and new format (dict with history + lan_events)
    if isinstance(data, list):
        return {"history": data, "lan_events": []}
    return data


# --- LAN Events & Scoped Awards ---


def get_lan_events_for_api() -> List[Dict[str, Any]]:
    """Return LAN events from rating_history.json, formatted for the API."""
    data = _rating_history_cache.get()
    if data is None or isinstance(data, list):
        return []
    lan_events = data.get("lan_events", [])
    result = []
    for event in lan_events:
        result.append({
            "id": f"lan-{event['start_date']}",
            "label": event["label"],
            "start_date": event["start_date"],
            "end_date": event["end_date"],
            "num_games": event["num_games"],
        })
    # Sort by start_date descending (most recent first)
    result.sort(key=lambda e: e["start_date"], reverse=True)
    return result


def compute_event_awards(event_id: str) -> Optional[Dict[str, Any]]:
    """Compute awards scoped to a specific LAN event by filtering registry data."""
    from analyzer_lib.analyze_games import _calculate_losing_streaks
    from analyzer_lib.report_generator import compute_all_awards

    # Find the matching event
    events = get_lan_events_for_api()
    event = None
    for e in events:
        if e["id"] == event_id:
            event = e
            break
    if event is None:
        return None

    start_date = event["start_date"]
    end_date = event["end_date"]

    # Load game registry
    registry_data = _game_registry_cache.get()
    if registry_data is None:
        raise FileNotFoundError(f"Game registry not found: {GAME_REGISTRY_PATH}")
    all_games = registry_data.get("games", [])

    # Filter to games within event date range with valid status
    filtered_games = [
        g for g in all_games
        if g.get("status") in ("processed", "no_winner")
        and g.get("datetime", "")[:10] >= start_date
        and g.get("datetime", "")[:10] <= end_date
    ]
    filtered_games.sort(key=lambda g: g.get("datetime", ""))

    # Build player_stats and game_stats (mirrors rebuild_analysis_from_registry)
    player_stats = defaultdict(lambda: {
        "games_played": 0,
        "games_for_win_rate": 0,
        "wins": 0,
        "total_playtime_seconds": 0,
        "total_eapm": 0,
        "games_with_eapm": 0,
        "civs_played": defaultdict(int),
        "civ_wins": defaultdict(int),
        "civ_losses": defaultdict(int),
        "civ_games_for_win_rate": defaultdict(int),
        "units_created": defaultdict(int),
        "total_units_created": 0,
        "market_transactions": 0,
        "total_resource_units_traded": 0,
        "wall_segments_built": 0,
        "buildings_deleted": 0,
        "crucial_researched": defaultdict(int),
    })

    game_stats = {
        "total_games": 0,
        "total_duration_seconds": 0,
        "longest_game": {"duration_seconds": 0, "file": ""},
        "overall_civ_picks": defaultdict(int),
        "total_units_created_overall": 0,
        "team_matchups": defaultdict(
            lambda: {"rosters": (), "wins_A": 0, "wins_B": 0}
        ),
        "awards": {
            "favorite_unit_fanatic": defaultdict(
                lambda: {"unit": "N/A", "count": 0}
            ),
            "bitter_salt_baron": {"player": None, "streak": 0},
            "market_mogul": {"player": None, "transactions": 0},
        },
    }

    player_game_chronology = defaultdict(list)

    for game in filtered_games:
        filename = game.get("filename", "")
        duration = game.get("duration_seconds", 0)
        teams = game.get("teams", {})
        winning_tid = game.get("winning_team_id")
        has_winner = winning_tid is not None

        # General game stats
        game_stats["total_games"] += 1
        game_stats["total_duration_seconds"] += duration
        if duration > game_stats["longest_game"]["duration_seconds"]:
            game_stats["longest_game"]["duration_seconds"] = duration
            game_stats["longest_game"]["file"] = filename

        # Per-player core stats from teams metadata
        all_winners = set()
        all_losers = set()

        for tid, players in teams.items():
            for p_info in players:
                name = p_info["name"]
                civ = p_info.get("civ", "Unknown")
                is_winner = p_info.get("winner", False)
                eapm = p_info.get("eapm")

                player_stats[name]["games_played"] += 1
                if has_winner:
                    player_stats[name]["games_for_win_rate"] += 1
                if is_winner:
                    player_stats[name]["wins"] += 1
                    all_winners.add(name)
                elif has_winner:
                    all_losers.add(name)

                player_stats[name]["total_playtime_seconds"] += duration

                if eapm:
                    player_stats[name]["total_eapm"] += eapm
                    player_stats[name]["games_with_eapm"] += 1

                player_stats[name]["civs_played"][civ] += 1
                game_stats["overall_civ_picks"][civ] += 1
                if has_winner:
                    player_stats[name]["civ_games_for_win_rate"][civ] += 1

                if is_winner:
                    player_stats[name]["civ_wins"][civ] += 1
                elif has_winner:
                    player_stats[name]["civ_losses"][civ] += 1

                player_game_chronology[name].append({
                    "won": is_winner,
                    "has_winner": has_winner,
                    "timestamp": game.get("datetime", ""),
                })

        # Action-based stats from player_deltas
        player_deltas = game.get("player_deltas", {})
        for name, deltas in player_deltas.items():
            for unit, count in deltas.get("units_created", {}).items():
                player_stats[name]["units_created"][unit] += count
            player_stats[name]["total_units_created"] += deltas.get(
                "total_units_created", 0
            )
            player_stats[name]["market_transactions"] += deltas.get(
                "market_transactions", 0
            )
            player_stats[name]["total_resource_units_traded"] += deltas.get(
                "total_resource_units_traded", 0
            )
            player_stats[name]["wall_segments_built"] += deltas.get(
                "wall_segments_built", 0
            )
            player_stats[name]["buildings_deleted"] += deltas.get(
                "buildings_deleted", 0
            )
            for tech, val in deltas.get("crucial_researched", {}).items():
                player_stats[name]["crucial_researched"][tech] += val

        game_level_deltas = game.get("game_level_deltas", {})
        game_stats["total_units_created_overall"] += game_level_deltas.get(
            "total_units_created_overall", 0
        )

        # Team matchup stats
        if has_winner and len(teams) == 2:
            team_rosters = []
            for tid in sorted(teams.keys()):
                roster = tuple(sorted(p["name"] for p in teams[tid]))
                team_rosters.append(roster)
            canonical_rosters = tuple(team_rosters)
            matchup_key = str(canonical_rosters)

            sorted_tids = sorted(teams.keys())
            team_a_id = sorted_tids[0]

            if not game_stats["team_matchups"][matchup_key]["rosters"]:
                game_stats["team_matchups"][matchup_key]["rosters"] = canonical_rosters

            if winning_tid == team_a_id:
                game_stats["team_matchups"][matchup_key]["wins_A"] += 1
            else:
                game_stats["team_matchups"][matchup_key]["wins_B"] += 1

    # Calculate losing streaks
    _calculate_losing_streaks(player_game_chronology, player_stats)

    return compute_all_awards(player_stats, game_stats)


# --- Upload & Rebuild ---


def _get_processor():
    """Lazily initialize the IncrementalProcessor singleton."""
    global _processor
    if _processor is None:
        from server.processing import GameRegistry, IncrementalProcessor

        try:
            from server import storage as storage_module
        except Exception:
            storage_module = None

        registry = GameRegistry(data_dir=config.DATA_DIR)
        _processor = IncrementalProcessor(registry, storage_module=storage_module)
    return _processor


def process_upload(file_bytes: bytes, sha256: str) -> Dict[str, Any]:
    """Process an uploaded replay file end-to-end.

    Verifies SHA256 match, then delegates to IncrementalProcessor.
    """
    actual_sha = hashlib.sha256(file_bytes).hexdigest()
    if actual_sha != sha256:
        return {
            "error": f"SHA256 mismatch: expected {sha256}, got {actual_sha}",
        }

    processor = _get_processor()
    return processor.process_new_replay(file_bytes, sha256)


def trigger_rebuild() -> Dict[str, Any]:
    """Trigger a full rebuild from all bucket replays."""
    processor = _get_processor()
    return processor.full_rebuild()
