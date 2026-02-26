"""Action-based stat extraction and utility functions for game analysis.

The main analysis pipeline is in registry_stats.accumulate_stats_from_games().
This module provides helpers used during replay parsing and stats rebuilding.
"""

import logging
from collections import defaultdict

from . import config


def _calculate_losing_streaks(player_game_chronology, player_stats):
    """Calculate the maximum losing streak for each player.

    Args:
        player_game_chronology: dict mapping player names to a list of
            game results: [{"won": bool, "has_winner": bool, "timestamp": ...}, ...]
        player_stats: dict to store aggregated stats per player.
            The 'max_losing_streak' key is added/updated for each player.
    """
    logging.debug("Calculating losing streaks...")
    for player_name, games in player_game_chronology.items():
        if not games:
            player_stats[player_name]["max_losing_streak"] = 0
            continue
        sorted_games = sorted(games, key=lambda g: g["timestamp"])
        current_streak = 0
        max_streak = 0
        for game in sorted_games:
            if not game.get("has_winner", True):
                continue
            if not game["won"]:
                current_streak += 1
            else:
                max_streak = max(max_streak, current_streak)
                current_streak = 0
        max_streak = max(max_streak, current_streak)
        player_stats[player_name]["max_losing_streak"] = max_streak


def extract_single_game_deltas(match_obj, human_players):
    """Extract per-game stat deltas from a single parsed match.

    Used by registry_builder.replay_to_registry_entry() during replay parsing.

    Args:
        match_obj: Parsed match object (from mgz.parse_match).
        human_players: List of human player objects (already alias-resolved).

    Returns:
        (player_deltas, game_deltas) where:
        - player_deltas: dict keyed by player name, each containing:
            units_created (dict), total_units_created (int),
            market_transactions (int), total_resource_units_traded (int),
            wall_segments_built (int), buildings_deleted (int),
            crucial_researched (dict of tech_name -> 1)
        - game_deltas: dict with total_units_created_overall (int)
    """
    player_deltas = {}
    for p in human_players:
        player_deltas[p.name] = {
            "units_created": defaultdict(int),
            "total_units_created": 0,
            "market_transactions": 0,
            "total_resource_units_traded": 0,
            "wall_segments_built": 0,
            "buildings_deleted": 0,
            "crucial_researched": {},
        }

    total_units_created_overall = 0
    player_number_to_name = {p.number: p.name for p in human_players}
    human_player_names = {p.name for p in human_players}
    crucial_techs_seen = defaultdict(set)

    if hasattr(match_obj, "inputs") and match_obj.inputs:
        for input_action in match_obj.inputs:
            input_type_name = str(getattr(input_action, "type", "N/A"))

            action_player_name = None
            if hasattr(input_action, "player") and input_action.player is not None:
                if hasattr(input_action.player, "name"):
                    potential_name = input_action.player.name
                    if potential_name in human_player_names:
                        action_player_name = potential_name
                elif isinstance(input_action.player, int):
                    action_player_name = player_number_to_name.get(input_action.player)

            if input_type_name == "Queue":
                player_number_for_queue = getattr(
                    getattr(input_action, "player", None), "number", None
                )
                current_player = player_number_to_name.get(player_number_for_queue)

                payload = getattr(input_action, "payload", {})
                unit_name = payload.get("unit")

                if (
                    unit_name
                    and current_player
                    and unit_name not in config.NON_MILITARY_UNITS
                ):
                    if current_player in player_deltas:
                        player_deltas[current_player]["units_created"][unit_name] += 1
                        player_deltas[current_player]["total_units_created"] += 1
                        total_units_created_overall += 1

            elif input_type_name in ["Buy", "Sell"]:
                if action_player_name and action_player_name in player_deltas:
                    player_deltas[action_player_name]["market_transactions"] += 1
                    payload = input_action.payload
                    if (
                        isinstance(payload, dict)
                        and "resource_id" in payload
                        and "amount" in payload
                    ):
                        if payload["resource_id"] in [0, 1, 2]:
                            player_deltas[action_player_name][
                                "total_resource_units_traded"
                            ] += payload["amount"]

            elif input_type_name == "Wall":
                if action_player_name and action_player_name in player_deltas:
                    player_deltas[action_player_name]["wall_segments_built"] += 1

            elif input_type_name == "Delete":
                if action_player_name and action_player_name in player_deltas:
                    player_deltas[action_player_name]["buildings_deleted"] += 1

            elif input_type_name == "Research":
                if action_player_name and action_player_name in player_deltas:
                    tech_name = getattr(input_action, "param", None)
                    if tech_name in config.CRUCIAL_UPGRADES:
                        if tech_name not in crucial_techs_seen[action_player_name]:
                            crucial_techs_seen[action_player_name].add(tech_name)
                            player_deltas[action_player_name]["crucial_researched"][
                                tech_name
                            ] = 1

    # Convert defaultdicts to regular dicts for JSON serialization
    for name in player_deltas:
        player_deltas[name]["units_created"] = dict(
            player_deltas[name]["units_created"]
        )

    game_deltas = {"total_units_created_overall": total_units_created_overall}
    return player_deltas, game_deltas
