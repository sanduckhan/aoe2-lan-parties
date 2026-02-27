import hashlib
import logging
import os
import sys
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

import trueskill
from analyzer_lib import config, db
from handicap_recommender import recommended_handicap
from team_balancer import find_balanced_teams, suggest_rebalances_data

logger = logging.getLogger(__name__)

# Lazy singleton for IncrementalProcessor
_processor = None


def _get_db_path() -> str:
    return db.get_db_path(config.DATA_DIR)


def _compute_rating_offset(ratings: List[Dict[str, Any]]) -> float:
    """Compute offset to re-center average displayed rating to 1000.

    TrueSkill is not zero-sum: average mu drifts downward over time.
    This cosmetic offset keeps displayed ratings centered at 1000
    without affecting the underlying TrueSkill calculations.
    """
    if not ratings:
        return 0.0
    avg = sum(r["mu_scaled"] for r in ratings) / len(ratings)
    return 1000.0 - avg


def _get_ts_env() -> trueskill.TrueSkill:
    return trueskill.TrueSkill(
        beta=config.TRUESKILL_BETA,
        draw_probability=config.TRUESKILL_DRAW_PROBABILITY,
    )


def load_ratings() -> List[Dict[str, Any]]:
    data = db.load_player_ratings(_get_db_path())
    if not data:
        raise FileNotFoundError("No player ratings found in database")
    return data


def _ratings_dict() -> Dict[str, Dict[str, Any]]:
    return {p["name"]: p for p in load_ratings()}


def _player_info(data: Dict[str, Any], offset: float = 0.0) -> Dict[str, Any]:
    avg_hc = data.get("avg_handicap_last_30", 100)
    info = {
        "name": data["name"],
        "mu_scaled": round(data["mu_scaled"] + offset, 1),
        "sigma_scaled": round(data["sigma_scaled"], 2),
        "games_played": data["games_played"],
        "games_rated": data.get("games_rated", data["games_played"]),
        "confidence_percent": round(data["confidence_percent"], 1),
        "avg_handicap_last_30": avg_hc,
        "recommended_hc": recommended_handicap(data["mu_scaled"] + offset, avg_hc),
    }
    return info


def get_players_for_api() -> Dict[str, Any]:
    ratings = load_ratings()
    offset = _compute_rating_offset(ratings)
    ranked = sorted(
        [
            r
            for r in ratings
            if r.get("games_rated", r["games_played"]) >= config.MIN_GAMES_FOR_RANKING
        ],
        key=lambda r: r["mu_scaled"],
        reverse=True,
    )
    provisional = sorted(
        [
            r
            for r in ratings
            if r.get("games_rated", r["games_played"]) < config.MIN_GAMES_FOR_RANKING
        ],
        key=lambda r: r["mu_scaled"],
        reverse=True,
    )
    return {
        "ranked": [_player_info(p, offset) for p in ranked],
        "provisional": [_player_info(p, offset) for p in provisional],
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
    offset: float = 0.0,
) -> Dict[str, Any]:
    def p_info(name):
        data = ratings_data[name]
        avg_hc = data.get("avg_handicap_last_30", 100)
        return {
            "name": name,
            "rating": round(data["mu_scaled"] + offset, 1),
            "recommended_hc": recommended_handicap(data["mu_scaled"] + offset, avg_hc),
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


def generate_teams(player_names: List[str], top_n: int = 3) -> Dict[str, Any]:
    all_ratings = load_ratings()
    offset = _compute_rating_offset(all_ratings)
    ratings_data = {p["name"]: p for p in all_ratings}

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
            quality, t1, t2, ratings_data, player_ts_ratings, ts_env, offset
        )
        enriched["benched"] = [
            {"name": n, "rating": round(ratings_data[n]["mu_scaled"] + offset, 1)}
            for n in benched
        ]
        suggestions.append(enriched)

    return {"suggestions": suggestions, "warnings": warnings}


def _apply_offset_to_team_result(result: Dict[str, Any], offset: float) -> None:
    """Apply display offset to avg rating values in rebalance results.

    Player-level ratings and recommended_hc are already offset by
    suggest_rebalances_data via its display_offset parameter.
    Only team avg ratings (computed from raw mu_scaled) need offsetting here.
    """
    if not offset:
        return
    section = result.get("current_setup", {})
    for avg_key in ("team1_avg_rating", "team2_avg_rating"):
        if avg_key in section:
            section[avg_key] = round(section[avg_key] + offset, 0)


def rebalance_teams(
    team1: List[str], team2: List[str], weaker_team: int, top_n: int = 5
) -> Dict[str, Any]:
    all_ratings = load_ratings()
    offset = _compute_rating_offset(all_ratings)
    ratings_data = {p["name"]: p for p in all_ratings}

    all_names = list(set(team1 + team2))
    missing = [n for n in all_names if n not in ratings_data]
    if missing:
        return {"error": f"Players not found in ratings: {', '.join(missing)}"}

    ts_env = _get_ts_env()
    player_ts_ratings = _build_ts_ratings(all_names, ratings_data)

    result = suggest_rebalances_data(
        team1,
        team2,
        weaker_team,
        player_ts_ratings,
        ratings_data,
        ts_env,
        top_n=top_n,
        display_offset=offset,
    )
    _apply_offset_to_team_result(result, offset)
    return result


# --- API service functions ---


def get_awards_for_api() -> Dict[str, Any]:
    data = db.load_analysis_cache(_get_db_path(), "awards")
    if data is None:
        raise FileNotFoundError("No awards data found in database")
    return data


def _format_game_results(games: List[Dict]) -> List[Dict[str, Any]]:
    """Format raw game_results into API-ready dicts, sorted chronologically with game_number."""
    formatted = []
    for g in games:
        winning_team_id = g.get("winning_team_id")
        if winning_team_id is None:
            continue
        teams_list = []
        for tid, players in g["teams"].items():
            teams_list.append(
                {
                    "team_id": tid,
                    "players": players,
                    "is_winner": (tid == winning_team_id),
                }
            )
        formatted.append(
            {
                "filename": g["filename"],
                "datetime": g["datetime"],
                "duration_seconds": g["duration_seconds"],
                "duration_display": str(timedelta(seconds=int(g["duration_seconds"]))),
                "teams": teams_list,
                "has_winner": True,
                "sha256": g.get("sha256"),
                "rating_changes": g.get("rating_changes"),
            }
        )
    formatted.sort(key=lambda g: g["datetime"])
    for i, g in enumerate(formatted, 1):
        g["game_number"] = i
    return formatted


def _compute_streaks(games: List[Dict[str, Any]]) -> None:
    """Compute running win/loss streaks in-place. Games must be in chronological order."""
    streaks = {}  # player_name -> current streak count (positive=wins, negative=losses)
    for g in games:
        game_streaks = {}
        for team in g["teams"]:
            for p in team["players"]:
                name = p["name"]
                if team["is_winner"]:
                    streaks[name] = max(0, streaks.get(name, 0)) + 1
                    if streaks[name] >= 3:
                        game_streaks[name] = f"W{streaks[name]}"
                else:
                    streaks[name] = min(0, streaks.get(name, 0)) - 1
                    if streaks[name] <= -3:
                        game_streaks[name] = f"L{abs(streaks[name])}"
        g["streaks"] = game_streaks


def get_games_for_api() -> Dict[str, Any]:
    games = db.load_analysis_cache(_get_db_path(), "game_results")
    if games is None:
        raise FileNotFoundError("No game results found in database")
    formatted = _format_game_results(games)
    return {"games": formatted, "total": len(formatted)}


def get_games_paginated(
    offset: int = 0,
    limit: int = 30,
    search: str = "",
    sort: str = "desc",
) -> Dict[str, Any]:
    """Return paginated, searchable game results with streaks."""
    games = db.load_analysis_cache(_get_db_path(), "game_results")
    if games is None:
        raise FileNotFoundError("No game results found in database")

    formatted = _format_game_results(games)
    _compute_streaks(formatted)

    if search:
        q = search.lower()
        formatted = [
            g
            for g in formatted
            if any(
                q in p["name"].lower()
                for team in g["teams"]
                for p in team["players"]
            )
        ]

    total = len(formatted)

    if sort == "desc":
        formatted.reverse()

    page = formatted[offset : offset + limit]

    return {
        "games": page,
        "total": total,
        "has_more": (offset + limit) < total,
    }


def get_game_detail_for_api(sha256: str) -> Optional[Dict[str, Any]]:
    """Return full game detail from registry + rating changes from analysis data."""
    registry = _get_registry()
    entry = registry.get_game_by_sha256(sha256)

    if entry is None:
        return None

    result = {
        "sha256": entry.get("sha256"),
        "filename": entry.get("filename"),
        "datetime": entry.get("datetime"),
        "duration_seconds": entry.get("duration_seconds", 0),
        "duration_display": str(
            timedelta(seconds=int(entry.get("duration_seconds", 0)))
        ),
        "status": entry.get("status"),
        "winning_team_id": entry.get("winning_team_id"),
        "teams": {},
        "player_deltas": entry.get("player_deltas", {}),
        "game_level_deltas": entry.get("game_level_deltas", {}),
        "rating_changes": {},
    }

    for tid, players in entry.get("teams", {}).items():
        result["teams"][tid] = {
            "team_id": tid,
            "is_winner": (tid == str(entry.get("winning_team_id"))),
            "players": [
                {
                    "name": p["name"],
                    "civilization": p.get("civ", "Unknown"),
                    "winner": p.get("winner", False),
                    "handicap": p.get("handicap", 100),
                    "eapm": p.get("eapm"),
                }
                for p in players
            ],
        }

    # Get rating changes from analysis cache
    try:
        game_results = db.load_analysis_cache(_get_db_path(), "game_results")
        if game_results:
            for gr in game_results:
                if gr.get("sha256") == sha256:
                    result["rating_changes"] = gr.get("rating_changes", {})
                    break
    except Exception:
        pass

    return result


def get_stats_for_api() -> Dict[str, Any]:
    data = db.load_analysis_cache(_get_db_path(), "general_stats")
    if data is None:
        raise FileNotFoundError("No stats data found in database")
    return data


def get_player_profile_for_api(name: str) -> Optional[Dict[str, Any]]:
    profiles = db.load_analysis_cache(_get_db_path(), "player_profiles")
    if profiles is None:
        return None

    # Try exact match, then case-insensitive
    profile = profiles.get(name)
    if profile is None:
        for pname, pdata in profiles.items():
            if pname.lower() == name.lower():
                profile = pdata
                break

    if profile is None:
        return None

    # Make a copy to avoid mutating cached data
    profile = dict(profile)

    # Enrich with rating data
    try:
        all_ratings = load_ratings()
        offset = _compute_rating_offset(all_ratings)
        ratings_data = {p["name"]: p for p in all_ratings}
        canonical_name = profile["name"]
        if canonical_name in ratings_data:
            rd = ratings_data[canonical_name]
            avg_hc = rd.get("avg_handicap_last_30", 100)
            profile["rating"] = {
                "mu_scaled": round(rd["mu_scaled"] + offset, 1),
                "sigma_scaled": round(rd["sigma_scaled"], 2),
                "confidence_percent": round(rd["confidence_percent"], 1),
                "avg_handicap_last_30": avg_hc,
                "recommended_hc": recommended_handicap(
                    rd["mu_scaled"] + offset, avg_hc
                ),
            }
    except FileNotFoundError:
        pass

    # Compute trend from rating history
    try:
        history_data = get_rating_history_for_api()
        player_history = [
            h for h in history_data["history"] if h["player_name"] == profile["name"]
        ]
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
    data = db.load_rating_history(_get_db_path())
    if not data or (not data.get("history") and not data.get("lan_events")):
        raise FileNotFoundError("No rating history found in database")
    # Apply re-centering offset to chart mu values
    ratings = load_ratings()
    offset = _compute_rating_offset(ratings)
    if offset:
        for h in data["history"]:
            h["mu"] = round(h["mu"] + offset, 2)
    return data


# --- LAN Events & Scoped Awards ---


def get_lan_events_for_api() -> List[Dict[str, Any]]:
    """Return LAN events from the database, formatted for the API."""
    events = db.load_lan_events(_get_db_path())
    result = []
    for event in events:
        result.append(
            {
                "id": f"lan-{event['start_date']}",
                "label": event["label"],
                "start_date": event["start_date"],
                "end_date": event["end_date"],
                "num_games": event["num_games"],
            }
        )
    return result


def compute_event_awards(event_id: str) -> Optional[Dict[str, Any]]:
    """Compute awards scoped to a specific LAN event by filtering registry data."""
    from analyzer_lib.registry_stats import accumulate_stats_from_games
    from analyzer_lib.report_generator import compute_all_awards

    events = get_lan_events_for_api()
    event = next((e for e in events if e["id"] == event_id), None)
    if event is None:
        return None

    start_date = event["start_date"]
    end_date = event["end_date"]

    registry = _get_registry()
    filtered_games = registry.get_games_in_date_range(
        status_list=["processed", "no_winner"],
        date_from=start_date,
        date_to=end_date,
    )
    filtered_games.sort(key=lambda g: g.get("datetime", ""))

    player_stats, game_stats, _, _ = accumulate_stats_from_games(filtered_games)
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


def _get_registry():
    """Get the shared GameRegistry from the processor singleton."""
    return _get_processor()._registry


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


def get_replay_download(sha256: str) -> Optional[Tuple[bytes, str]]:
    """Get replay file bytes and filename for download.

    Checks local disk first (source_path), then falls back to bucket storage.
    Returns (file_bytes, filename) or None if not found.
    """
    registry = _get_registry()
    entry = registry.get_game_by_sha256(sha256)

    if entry is None:
        return None

    filename = entry.get("filename", f"{sha256[:12]}.aoe2record")

    # Try local file first
    source_path = entry.get("source_path")
    if source_path:
        full_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), source_path
        )
        if os.path.isfile(full_path):
            with open(full_path, "rb") as f:
                return f.read(), filename

    # Fall back to bucket storage
    try:
        from server import storage

        file_bytes = storage.download_replay(sha256)
        return file_bytes, filename
    except Exception:
        return None


def trigger_rebuild() -> Dict[str, Any]:
    """Trigger a full rebuild from all bucket replays."""
    processor = _get_processor()
    return processor.full_rebuild()


def get_rebuild_status() -> Dict[str, Any]:
    """Return current full rebuild progress."""
    processor = _get_processor()
    return processor.full_rebuild_status
