"""Shared logic for accumulating stats from game registry entries.

Provides the single source of truth for building player_stats, game_stats,
game_results, and head_to_head from a list of registry game entries. Used by:
  - main.py (CLI analysis)
  - server/processing.py (rebuild_analysis_from_registry)
  - web/services.py (compute_event_awards)
"""

from collections import defaultdict

from .analyze_games import _calculate_losing_streaks


def make_empty_player_stats():
    """Return a defaultdict factory for per-player stats."""
    return defaultdict(lambda: {
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


def make_empty_game_stats():
    """Return a fresh game_stats dict."""
    return {
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


def accumulate_stats_from_games(games):
    """Accumulate player_stats, game_stats, game_results, head_to_head
    from a list of registry game entries.

    Args:
        games: List of game registry entry dicts. Should be pre-sorted
            chronologically and pre-filtered to desired statuses
            (typically "processed" and "no_winner").

    Returns:
        (player_stats, game_stats, game_results, head_to_head) tuple
        matching the output shape of the old analyze_all_games().
    """
    player_stats = make_empty_player_stats()
    game_stats = make_empty_game_stats()
    game_results = []
    head_to_head = defaultdict(
        lambda: defaultdict(lambda: {"wins": 0, "losses": 0})
    )
    player_game_chronology = defaultdict(list)

    for game in games:
        filename = game.get("filename", "")
        duration = game.get("duration_seconds", 0)
        teams = game.get("teams", {})
        winning_tid = game.get("winning_team_id")
        has_winner = winning_tid is not None

        # --- General game stats ---
        game_stats["total_games"] += 1
        game_stats["total_duration_seconds"] += duration
        if duration > game_stats["longest_game"]["duration_seconds"]:
            game_stats["longest_game"]["duration_seconds"] = duration
            game_stats["longest_game"]["file"] = filename

        # --- Per-player core stats ---
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

        # --- Action-based stats from player_deltas ---
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

        # --- Game results for web UI ---
        game_result_teams = {}
        for tid, players in teams.items():
            game_result_teams[tid] = [
                {
                    "name": p["name"],
                    "civilization": p.get("civ", "Unknown"),
                    "winner": bool(p.get("winner", False)),
                }
                for p in players
            ]
        game_results.append({
            "filename": filename,
            "datetime": game.get("datetime", ""),
            "duration_seconds": duration,
            "winning_team_id": winning_tid,
            "teams": game_result_teams,
            "sha256": game.get("sha256", ""),
        })

        # --- Head-to-head ---
        if has_winner and all_winners and all_losers:
            for w in all_winners:
                for l in all_losers:
                    head_to_head[w][l]["wins"] += 1
                    head_to_head[l][w]["losses"] += 1

        # --- Team matchup stats ---
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
                game_stats["team_matchups"][matchup_key][
                    "rosters"
                ] = canonical_rosters

            if winning_tid == team_a_id:
                game_stats["team_matchups"][matchup_key]["wins_A"] += 1
            else:
                game_stats["team_matchups"][matchup_key]["wins_B"] += 1

    # --- Calculate losing streaks ---
    _calculate_losing_streaks(player_game_chronology, player_stats)

    return player_stats, game_stats, game_results, head_to_head
