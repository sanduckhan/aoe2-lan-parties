import os
from collections import defaultdict
from datetime import timedelta, datetime
from . import config # Added import
# NON_MILITARY_UNITS = {"Villager", "Fishing Ship"} # Removed
from mgz.model import parse_match
import re

# --- Configuration ---
# RECORDED_GAMES_DIR = 'recorded_games' # Removed
# CRUCIAL_UPGRADES = sorted(["Loom", "Double-Bit Axe", "Wheelbarrow", "Horse Collar", "Bow Saw"]) # Removed

# --- Data Structures ---
player_stats = defaultdict(lambda: {
    'games_played': 0,
    'games_for_win_rate': 0, # Games where a winner was determined
    'wins': 0,
    'total_playtime_seconds': 0,
    'total_eapm': 0,
    'games_with_eapm': 0,
    'civs_played': defaultdict(int),
    'civ_wins': defaultdict(int),
    'civ_losses': defaultdict(int),
    'civ_games_for_win_rate': defaultdict(int), # Civ games where a winner was determined
    'units_created': defaultdict(int),
    'total_units_created': 0,
    'market_transactions': 0, # For 'The Market Mogul' award
    'total_resource_units_traded': 0, # Sum of Food, Wood, Stone bought/sold
    'wall_segments_built': 0,
    'buildings_deleted': 0,
    'crucial_researched': defaultdict(int), # For 'Most Likely to Forget Upgrade' award
})

game_stats = {
    'total_games': 0,
    'total_duration_seconds': 0,
    'longest_game': {'duration_seconds': 0, 'file': ''},
    'overall_civ_picks': defaultdict(int),
    'total_units_created_overall': 0, # Added missing key
    'team_matchups': defaultdict(lambda: {'rosters': (), 'wins_A': 0, 'wins_B': 0}),
    'awards': {
        'favorite_unit_fanatic': defaultdict(lambda: {'unit': 'N/A', 'count': 0}),
        'bitter_salt_baron': {'player': None, 'streak': 0},
        'market_mogul': {'player': None, 'transactions': 0}
    }
}


def _get_datetime_from_filename(filename):
    """Extracts datetime from filename to allow chronological sorting."""
    match = re.search(r'@(\d{4}\.\d{2}\.\d{2} \d{6})', filename)
    if match:
        datetime_str = match.group(1)
        try:
            return datetime.strptime(datetime_str, '%Y.%m.%d %H%M%S')
        except ValueError:
            return datetime.min # Should not happen with this regex
    return datetime.min # Files without a timestamp processed first


# --- Main Logic ---
def parse_replay_file(file_path, filename):
    """
    Parses a single replay file and performs initial validation.

    Args:
        file_path (str): The full path to the replay file.
        filename (str): The name of the replay file (for logging).

    Returns:
        mgz.model.Match or None: The parsed match object if successful and valid, 
                                 None otherwise.
    """
    print(f"Analyzing: {filename}")
    try:
        with open(file_path, 'rb') as f:
            match = parse_match(f)

        if not match:
            print(f"  -> Skipping file {filename}: Could not find match data.")
            return None

        duration_seconds = match.duration.total_seconds()
        # Filter out games shorter than 5 minutes (300 seconds)
        if duration_seconds < 300:
            print(f"  -> Skipping file {filename}: Game duration ({timedelta(seconds=int(duration_seconds))}) is less than 5 minutes.\n")
            return None
        
        return match
    except FileNotFoundError:
        print(f"  -> Skipping file {filename}: File not found at '{file_path}'.")
        return None
    except Exception as e:
        print(f"  -> Skipping file {filename}: Error parsing - {e}")
        return None


def _update_general_game_stats(duration_seconds, filename, game_stats):
    """
    Updates general game statistics like total games, duration, and longest game.
    Modifies game_stats in place.

    Args:
        duration_seconds (float): The duration of the game in seconds.
        filename (str): The filename of the game, used for tracking the longest game.
        game_stats (dict): The global dictionary holding aggregated game statistics.
                           This dictionary is modified in place.

    Returns:
        None
    """
    game_stats['total_games'] += 1
    game_stats['total_duration_seconds'] += duration_seconds
    if duration_seconds > game_stats['longest_game']['duration_seconds']:
        game_stats['longest_game']['duration_seconds'] = duration_seconds
        game_stats['longest_game']['file'] = filename


def _determine_game_outcomes(human_players_from_match, filename_for_logging):
    """
    Determines the winning team and individual player outcomes for a single game.

    Args:
        human_players_from_match (list): List of player objects considered human.
        filename_for_logging (str): The filename, used for logging warnings.

    Returns:
        tuple: (winning_team_id, player_outcomes, teams_data)
               winning_team_id (int or None): ID of the winning team, or None.
               player_outcomes (dict): Maps player_name to boolean (True if winner).
               teams_data (defaultdict): Maps team_id to list of player objects.
    """
    teams_data = defaultdict(list)
    for p in human_players_from_match:
        team_id = p.team_id
        if isinstance(team_id, list):
            team_id = team_id[0] if team_id else -1
        teams_data[team_id].append(p)

    winning_team_id = None
    for team_id, players_in_team in teams_data.items():
        if any(p.winner for p in players_in_team):
            winning_team_id = team_id
            break
    
    if winning_team_id is None and len(teams_data) > 1:
        print(f"  -> WARNING: Could not determine a winner for {filename_for_logging}. Win/loss stats will be skipped for this game.")

    player_outcomes = {}
    for player in human_players_from_match:
        player_team_id = player.team_id
        if isinstance(player_team_id, list):
            player_team_id = player_team_id[0] if player_team_id else -1
        player_outcomes[player.name] = (player_team_id == winning_team_id)
        
    return winning_team_id, player_outcomes, teams_data


def _update_player_core_stats(player, match_obj, is_winner, winning_team_id, duration_seconds, player_stats, player_game_chronology, game_stats):
    """
    Updates core statistics for a single player from a single game.
    Modifies player_stats, player_game_chronology, and game_stats in place.

    Args:
        player (mgz.model.Player): The player object from the match.
        match_obj (mgz.model.Match): The parsed match object.
        is_winner (bool): True if the player won the game, False otherwise.
        winning_team_id (int or None): The ID of the winning team, if applicable.
        duration_seconds (float): The duration of the game in seconds.
        player_stats (defaultdict): Dictionary to store aggregated stats per player. Modified in place.
        player_game_chronology (defaultdict): Dictionary to store game results chronologically per player. Modified in place.
        game_stats (dict): Global dictionary for game-wide stats (e.g., civ picks). Modified in place.

    Returns:
        None
    """
    player_name = config.PLAYER_ALIASES.get(player.name, player.name) # Use aliased name

    player_stats[player_name]['games_played'] += 1
    if winning_team_id is not None:  # Game has a determined winner
        player_stats[player_name]['games_for_win_rate'] += 1
    if is_winner:
        player_stats[player_name]['wins'] += 1
    player_stats[player_name]['total_playtime_seconds'] += duration_seconds

    # Track eAPM
    if player.eapm:
        player_stats[player_name]['total_eapm'] += player.eapm
        player_stats[player_name]['games_with_eapm'] += 1

    civ_name = player.civilization
    player_stats[player_name]['civs_played'][civ_name] += 1
    game_stats['overall_civ_picks'][civ_name] += 1  # Also update global civ picks here
    if winning_team_id is not None:  # Game has a determined winner
        player_stats[player_name]['civ_games_for_win_rate'][civ_name] += 1

    if is_winner:
        player_stats[player_name]['civ_wins'][civ_name] += 1
    else:
        player_stats[player_name]['civ_losses'][civ_name] += 1
    
    player_game_chronology[player_name].append({'won': is_winner, 'timestamp': match_obj.timestamp})


def _update_team_matchup_stats(teams_data, winning_team_id, game_stats):
    """
    Updates team matchup statistics based on the game's outcome.
    Modifies game_stats in place.

    Args:
        teams_data (defaultdict): Maps team_id to a list of player objects on that team.
        winning_team_id (int or None): The ID of the winning team. If None, no matchup stats are updated.
        game_stats (dict): The global dictionary holding aggregated game statistics,
                           specifically the 'team_matchups' key. Modified in place.

    Returns:
        None
    """
    team_rosters = []
    for team_id in sorted(teams_data.keys()):
        player_names = sorted([config.PLAYER_ALIASES.get(p.name, p.name) for p in teams_data[team_id]]) # Use aliased names for rosters
        team_rosters.append(tuple(player_names))
    
    canonical_rosters = tuple(team_rosters)

    if len(canonical_rosters) == 2 and winning_team_id is not None:
        matchup_key = str(canonical_rosters) # Use a string representation as the key
        # Determine which of the canonical_rosters corresponds to team_A_id for consistent win tracking
        team_A_players_tuple = canonical_rosters[0]
        team_A_id = None
        for tid, players_in_team_object_list in teams_data.items():
            current_team_player_names_tuple = tuple(sorted([p.name for p in players_in_team_object_list]))
            if current_team_player_names_tuple == team_A_players_tuple:
                team_A_id = tid
                break

        if not game_stats['team_matchups'][matchup_key]['rosters']:
            game_stats['team_matchups'][matchup_key]['rosters'] = canonical_rosters

        if winning_team_id == team_A_id:
            game_stats['team_matchups'][matchup_key]['wins_A'] += 1
        else:
            game_stats['team_matchups'][matchup_key]['wins_B'] += 1


def _process_action_based_stats(match_obj, human_players_from_match, player_stats, game_stats):
    """
    Processes action-based statistics from match.inputs (units, market, walls, etc.).
    Modifies player_stats and game_stats in place.

    Args:
        match_obj (mgz.model.Match): The parsed match object containing player inputs.
        human_players_from_match (list): List of human player objects in the match.
        player_stats (defaultdict): Dictionary to store aggregated stats per player. Modified in place.
        game_stats (dict): Global dictionary for game-wide stats. Modified in place.

    Returns:
        None
    """
    player_number_to_name = {p.number: p.name for p in human_players_from_match}
    human_player_names_in_match = {p.name for p in human_players_from_match} # For quick lookups
    crucial_techs_researched_this_game_by_player = defaultdict(set) # Tracks crucial techs researched by each player in THIS game

    if hasattr(match_obj, 'inputs') and match_obj.inputs:
        for input_action in match_obj.inputs:
            input_type_name = str(getattr(input_action, 'type', 'N/A'))
            
            action_player_name = None
            # Determine player name for actions that have a direct player attribute
            if hasattr(input_action, 'player') and input_action.player is not None:
                if hasattr(input_action.player, 'name'):
                    potential_name = input_action.player.name
                    if potential_name in human_player_names_in_match: # human_player_names_in_match contains original names
                        action_player_name = config.PLAYER_ALIASES.get(potential_name, potential_name) # Alias the name for stats key
                elif isinstance(input_action.player, int): # Fallback for older parsed data or different structures
                    original_action_player_name = player_number_to_name.get(input_action.player)
                    if original_action_player_name:
                        action_player_name = config.PLAYER_ALIASES.get(original_action_player_name, original_action_player_name) # Alias the name for stats key

            if input_type_name == 'Queue':
                # For 'Queue', player might be under 'player_number' in payload or direct 'player' attribute
                player_number_for_queue = getattr(getattr(input_action, 'player', None), 'number', None)
                original_current_action_player_name = player_number_to_name.get(player_number_for_queue)
                current_action_player_name = None # Default to None
                if original_current_action_player_name:
                    current_action_player_name = config.PLAYER_ALIASES.get(original_current_action_player_name, original_current_action_player_name) # Alias for stats key

                payload = getattr(input_action, 'payload', {})
                unit_name = payload.get('unit')
                
                if unit_name and current_action_player_name and unit_name not in config.NON_MILITARY_UNITS:
                    player_stats[current_action_player_name]['units_created'][unit_name] += 1
                    player_stats[current_action_player_name]['total_units_created'] += 1
                    game_stats['total_units_created_overall'] += 1
            
            elif input_type_name in ['Buy', 'Sell']:
                if action_player_name: # If we successfully identified a tracked human player
                    player_stats[action_player_name]['market_transactions'] += 1
                    payload = input_action.payload
                    if isinstance(payload, dict) and 'resource_id' in payload and 'amount' in payload:
                        resource_id = payload['resource_id']
                        amount = payload['amount']
                        if resource_id in [0, 1, 2]: # Food, Wood, Stone
                            player_stats[action_player_name]['total_resource_units_traded'] += amount
            
            elif input_type_name == 'Wall':
                if action_player_name:
                    player_stats[action_player_name]['wall_segments_built'] += 1
            
            elif input_type_name == 'Delete':
                if action_player_name:
                    player_stats[action_player_name]['buildings_deleted'] += 1
            
            elif input_type_name == 'Research':
                if action_player_name:
                    tech_name = getattr(input_action, 'param', None)
                    if tech_name in config.CRUCIAL_UPGRADES:
                        if tech_name not in crucial_techs_researched_this_game_by_player[action_player_name]:
                            crucial_techs_researched_this_game_by_player[action_player_name].add(tech_name)
                            player_stats[action_player_name]['crucial_researched'][tech_name] += 1


def _calculate_losing_streaks(player_game_chronology, player_stats):
    """
    Calculates the maximum losing streak for each player.
    Modifies player_stats in place.

    Args:
        player_game_chronology (defaultdict): A dictionary mapping player names to a list
                                              of their game results (timestamp, won).
        player_stats (defaultdict): Dictionary to store aggregated stats per player.
                                    The 'max_losing_streak' key is added/updated for each player.
                                    Modified in place.

    Returns:
        None
    """
    print("--- Calculating Losing Streaks ---")
    for player_name, games in player_game_chronology.items():
        if not games: 
            player_stats[player_name]['max_losing_streak'] = 0
            continue
        # Sort games by timestamp to process in chronological order
        sorted_games = sorted(games, key=lambda g: g['timestamp'])
        current_streak = 0
        max_streak = 0
        for game in sorted_games:
            if not game['won']:
                current_streak += 1
            else:
                max_streak = max(max_streak, current_streak)
                current_streak = 0
        max_streak = max(max_streak, current_streak) # Final check for streak ending with last game
        player_stats[player_name]['max_losing_streak'] = max_streak


def analyze_all_games():
    """Loops through recorded games, parses them, and aggregates stats."""
    if not os.path.isdir(config.RECORDED_GAMES_DIR):
        print(f"Error: Directory '{config.RECORDED_GAMES_DIR}' not found.")
        return

    print(f"--- Starting Analysis of Games in '{config.RECORDED_GAMES_DIR}' ---")
    player_game_chronology = defaultdict(list) # To store game results chronologically per player

    replay_files = [f for f in os.listdir(config.RECORDED_GAMES_DIR) if f.endswith('.aoe2record')]
    replay_files.sort(key=_get_datetime_from_filename) # Sort files chronologically

    total_files = len(replay_files)
    print(f"Found {total_files} replay files to analyze.")

    for filename in replay_files:
        file_path = os.path.join(config.RECORDED_GAMES_DIR, filename)
        match = parse_replay_file(file_path, filename)

        if not match:
            continue
        
        # Try block for analyzing the successfully parsed match data
        try:
            duration_seconds = match.duration.total_seconds()
            human_players_from_match = [p for p in match.players if hasattr(p, 'profile_id') and p.profile_id is not None]

            # --- Apply Player Aliases ---
            for player in human_players_from_match:
                player.name = config.PLAYER_ALIASES.get(player.name, player.name)

            human_player_names_in_match = {p.name for p in human_players_from_match}

            # --- Aggregate General Game Stats ---
            _update_general_game_stats(duration_seconds, filename, game_stats)

            # --- Determine Game Outcomes ---
            winning_team_id, player_outcomes, teams_data = _determine_game_outcomes(human_players_from_match, filename)

            # --- Per-Player Stats and Chronology ---
            for player in human_players_from_match:
                is_winner = player_outcomes.get(player.name, False)
                _update_player_core_stats(player, match, is_winner, winning_team_id, duration_seconds, player_stats, player_game_chronology, game_stats)

            # --- Team Matchup Stats ---
            _update_team_matchup_stats(teams_data, winning_team_id, game_stats)

            # --- Action-Based Stats (Units, Market, Walls, Techs, etc.) ---
            _process_action_based_stats(match, human_players_from_match, player_stats, game_stats)

        except Exception as e:
            print(f"  -> Error analyzing data for {filename} (after parsing): {e}")
    print(f"--- Analysis Complete ---")

    # --- Calculate Losing Streaks ---
    _calculate_losing_streaks(player_game_chronology, player_stats)

    return player_stats, game_stats
