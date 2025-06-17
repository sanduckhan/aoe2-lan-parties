import os
from collections import defaultdict
from datetime import timedelta

NON_MILITARY_UNITS = {"Villager", "Fishing Ship"}
from mgz.model import parse_match

# --- Configuration ---
RECORDED_GAMES_DIR = 'recorded_games'
CRUCIAL_UPGRADES = sorted(["Loom", "Double-Bit Axe", "Wheelbarrow", "Horse Collar", "Bow Saw"])

# --- Data Structures ---
player_stats = defaultdict(lambda: {
    'games_played': 0,
    'games_for_win_rate': 0, # Games where a winner was determined
    'wins': 0,
    'total_playtime_seconds': 0,
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
    player_name = player.name

    player_stats[player_name]['games_played'] += 1
    if winning_team_id is not None:  # Game has a determined winner
        player_stats[player_name]['games_for_win_rate'] += 1
    if is_winner:
        player_stats[player_name]['wins'] += 1
    player_stats[player_name]['total_playtime_seconds'] += duration_seconds

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
        player_names = sorted([p.name for p in teams_data[team_id]])
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
                    if potential_name in human_player_names_in_match:
                        action_player_name = potential_name
                elif isinstance(input_action.player, int): # Fallback for older parsed data or different structures
                    action_player_name = player_number_to_name.get(input_action.player)

            if input_type_name == 'Queue':
                # For 'Queue', player might be under 'player_number' in payload or direct 'player' attribute
                player_number_for_queue = getattr(getattr(input_action, 'player', None), 'number', None)
                current_action_player_name = player_number_to_name.get(player_number_for_queue)
                payload = getattr(input_action, 'payload', {})
                unit_name = payload.get('unit')
                
                if unit_name and current_action_player_name and unit_name not in NON_MILITARY_UNITS:
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
                    if tech_name in CRUCIAL_UPGRADES:
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
    if not os.path.isdir(RECORDED_GAMES_DIR):
        print(f"Error: Directory '{RECORDED_GAMES_DIR}' not found.")
        return

    print(f"--- Starting Analysis of Games in '{RECORDED_GAMES_DIR}' ---")
    player_game_chronology = defaultdict(list) # To store game results chronologically per player

    for filename in os.listdir(RECORDED_GAMES_DIR):
        if not filename.endswith(('.aoe2record', '.mgz', '.mgx')):
            continue

        file_path = os.path.join(RECORDED_GAMES_DIR, filename)
        match = parse_replay_file(file_path, filename)

        if not match:
            continue
        
        # Try block for analyzing the successfully parsed match data
        try:
            duration_seconds = match.duration.total_seconds()
            human_players_from_match = [p for p in match.players if hasattr(p, 'profile_id') and p.profile_id is not None]
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

def _print_most_balanced_team_matchup(game_stats):
    """Prints the most balanced team matchup based on game statistics."""
    print("\n--- Most Balanced Team Matchup ---")
    
    most_balanced_matchup_data = None

    # Try with MIN_GAMES_FOR_BALANCE = 3
    MIN_GAMES_FOR_BALANCE = 3
    relevant_matchups = {
        k: v for k, v in game_stats.get('team_matchups', {}).items()
        if (v.get('wins_A', 0) + v.get('wins_B', 0)) >= MIN_GAMES_FOR_BALANCE
    }

    if not relevant_matchups:
        # Try with a lower threshold if no matchups found
        MIN_GAMES_FOR_BALANCE = 1
        relevant_matchups = {
            k: v for k, v in game_stats.get('team_matchups', {}).items()
            if (v.get('wins_A', 0) + v.get('wins_B', 0)) >= MIN_GAMES_FOR_BALANCE
        }

    if relevant_matchups:
        # Find the matchup with the smallest win difference, then most games played
        # Ensure rosters exist and are tuples/lists before processing
        valid_matchups_for_min = [
            v for v in relevant_matchups.values()
            if isinstance(v.get('rosters'), (list, tuple)) and len(v['rosters']) == 2 and 
               isinstance(v['rosters'][0], (list, tuple)) and isinstance(v['rosters'][1], (list, tuple))
        ]
        if valid_matchups_for_min:
            most_balanced_matchup_data = min(
                valid_matchups_for_min,
                key=lambda v: (abs(v.get('wins_A', 0) - v.get('wins_B', 0)), -(v.get('wins_A', 0) + v.get('wins_B', 0)))
            )

    if most_balanced_matchup_data:
        team_A_roster = ', '.join(sorted(list(most_balanced_matchup_data['rosters'][0])))
        team_B_roster = ', '.join(sorted(list(most_balanced_matchup_data['rosters'][1])))
        wins_A = most_balanced_matchup_data['wins_A']
        wins_B = most_balanced_matchup_data['wins_B']
        print(f"  - Matchup: [{team_A_roster}] vs [{team_B_roster}]")
        print(f"  - Head-to-head: {wins_A} - {wins_B}")
        print(f"  - Total Games: {wins_A + wins_B}")
    else:
        print("  - Not enough team games played with consistent rosters (or at all) to determine a balanced matchup.")


def _print_general_game_statistics(game_stats):
    """Prints general game statistics like total games, average duration, and longest game."""
    print("\n--- General Game Statistics ---")
    print(f"Total Games Analyzed: {game_stats['total_games']}")
    if game_stats['total_games'] > 0:
        avg_duration_seconds = game_stats['total_duration_seconds'] / game_stats['total_games']
        avg_duration_str = str(timedelta(seconds=int(avg_duration_seconds)))
        print(f"Average Game Duration: {avg_duration_str}")

        longest_duration_str = str(timedelta(seconds=int(game_stats['longest_game']['duration_seconds'])))
        longest_game_file = game_stats['longest_game']['file']
        print(f"Longest Game: {longest_duration_str} (File: {longest_game_file})")


def _print_favorite_unit_fanatic(player_stats, game_stats):
    """Prints the 'Favorite Unit Fanatic' for each player and updates game_stats."""
    print("\n--- Favorite Unit Fanatic ---")
    excluded_units = ['Palisade Wall', 'Stone Wall', 'Farm', 'Villager', 'City Wall', 'Goat', 'Town Center', 'Sheep', 'City Gate']
    for player_name, stats in player_stats.items():
        if stats['units_created']:
            # Filter out excluded units
            filtered_units = {
                unit: count for unit, count in stats['units_created'].items() 
                if unit not in excluded_units
            }
            if filtered_units:
                most_common_unit, count = max(filtered_units.items(), key=lambda item: item[1])
                game_stats['awards']['favorite_unit_fanatic'][player_name] = {'unit': most_common_unit, 'count': count}
                print(f"  - {player_name}: {most_common_unit} ({count} times)")
            else:
                game_stats['awards']['favorite_unit_fanatic'][player_name] = {'unit': 'N/A (Filtered)', 'count': 0}
                print(f"  - {player_name}: N/A (Only created excluded units or no units)")
        else:
            game_stats['awards']['favorite_unit_fanatic'][player_name] = {'unit': 'N/A', 'count': 0}
            print(f"  - {player_name}: N/A (No unit data)")


def _print_bitter_salt_baron(player_stats, game_stats):
    """Determines and prints 'The Bitter Salt Baron' (longest losing streak) and updates game_stats."""
    # Determine The Bitter Salt Baron (longest losing streak)
    overall_longest_losing_streak = 0
    salt_baron_players = [] # Use a list to handle ties correctly
    for player_name, stats in player_stats.items():
        if stats['max_losing_streak'] > overall_longest_losing_streak:
            overall_longest_losing_streak = stats['max_losing_streak']
            salt_baron_players = [player_name] # New leader
        elif stats['max_losing_streak'] == overall_longest_losing_streak and overall_longest_losing_streak > 0:
            salt_baron_players.append(player_name) # Add to tie list

    print("\n--- The Bitter Salt Baron ---")
    if salt_baron_players and overall_longest_losing_streak > 0:
        salt_baron_player_str = ", ".join(salt_baron_players)
        game_stats['awards']['bitter_salt_baron'] = {'player': salt_baron_player_str, 'streak': overall_longest_losing_streak}
        print(f"  {salt_baron_player_str} with a streak of {overall_longest_losing_streak} losses.")
    else:
        # Ensure the key exists in game_stats even if no one qualifies
        # This check is important if the calculation logic didn't set it to N/A already
        if 'bitter_salt_baron' not in game_stats['awards'] or \
           (game_stats['awards'].get('bitter_salt_baron', {}).get('player') != 'N/A' and \
            game_stats['awards'].get('bitter_salt_baron', {}).get('streak', -1) != 0):
             game_stats['awards']['bitter_salt_baron'] = {'player': 'N/A', 'streak': 0}
        print("  No significant losing streaks found or everyone's a winner!")


def _print_wall_street_tycoon_award(player_stats):
    """Prints 'The Wall Street Tycoon' award for most walls built."""
    if not player_stats:
        return

    unique_wall_counts = sorted(list(set(s['wall_segments_built'] for s in player_stats.values() if s['wall_segments_built'] > 0)), reverse=True)
    
    if unique_wall_counts:
        max_walls = unique_wall_counts[0]
        winners = [p for p, s in player_stats.items() if s['wall_segments_built'] == max_walls]
        print("\n--- \"The Wall Street Tycoon\" Award ---")
        if len(winners) > 1:
            print(f"A tie for first place: {', '.join(winners)} with {max_walls} wall sections built each!")
        else:
            print(f"Winner: {winners[0]} with {max_walls} wall sections built!")

        if len(unique_wall_counts) > 1:
            second_max_walls = unique_wall_counts[1]
            runners_up = [p for p, s in player_stats.items() if s['wall_segments_built'] == second_max_walls]
            if runners_up:
                if len(runners_up) > 1:
                    print(f"  - Second place (tie): {', '.join(runners_up)} with {second_max_walls} each.")
                else:
                    print(f"  - Second place: {runners_up[0]} with {second_max_walls}.")


def _print_demolition_expert_award(player_stats):
    """Prints 'The Demolition Expert' award for most buildings deleted."""
    if not player_stats:
        return

    unique_delete_counts = sorted(list(set(s['buildings_deleted'] for s in player_stats.values() if s['buildings_deleted'] > 0)), reverse=True)

    if unique_delete_counts:
        max_deletes = unique_delete_counts[0]
        winners = [p for p, s in player_stats.items() if s['buildings_deleted'] == max_deletes]
        print("\n--- \"The Demolition Expert\" Award ---")
        if len(winners) > 1:
            print(f"A tie for first place: {', '.join(winners)} with {max_deletes} buildings deleted each!")
        else:
            print(f"Winner: {winners[0]} with {max_deletes} buildings deleted!")

        if len(unique_delete_counts) > 1:
            second_max_deletes = unique_delete_counts[1]
            runners_up = [p for p, s in player_stats.items() if s['buildings_deleted'] == second_max_deletes]
            if runners_up:
                if len(runners_up) > 1:
                    print(f"  - Second place (tie): {', '.join(runners_up)} with {second_max_deletes} each.")
                else:
                    print(f"  - Second place: {runners_up[0]} with {second_max_deletes}.")


def _print_market_mogul_award(player_stats):
    """Prints 'The Market Mogul' award for most market transactions and units traded."""
    if not player_stats:
        return

    unique_transaction_counts = sorted(list(set(s['market_transactions'] for s in player_stats.values() if s['market_transactions'] > 0)), reverse=True)

    if unique_transaction_counts:
        max_transactions = unique_transaction_counts[0]
        winners = [(p, s.get('total_resource_units_traded', 0)) for p, s in player_stats.items() if s['market_transactions'] == max_transactions]
        print("\n--- \"The Market Mogul\" Award ---")
        if len(winners) > 1:
            details = [f"{name} ({player_stats[name]['market_transactions']} transactions, {traded:,} units)" for name, traded in winners]
            print(f"A tie for first place: {', '.join(details)}")
        else:
            winner_name, units_traded = winners[0]
            print(f"Winner: {winner_name} with {max_transactions} transactions, trading a total of {units_traded:,} resource units.")

        if len(unique_transaction_counts) > 1:
            second_max_transactions = unique_transaction_counts[1]
            runners_up = [(p, s.get('total_resource_units_traded', 0)) for p, s in player_stats.items() if s['market_transactions'] == second_max_transactions]
            if runners_up:
                if len(runners_up) > 1:
                    details = [f"{name} ({second_max_transactions} transactions, {traded:,} units)" for name, traded in runners_up]
                    print(f"  - Second place (tie): {', '.join(details)}.")
                else:
                    runner_up_name, units_traded = runners_up[0]
                    print(f"  - Second place: {runner_up_name} with {second_max_transactions} transactions, trading {units_traded:,} units.")
    # Removed the 'else' for no market transactions as it's handled by unique_transaction_counts check


def _print_forgetful_upgrades_award(player_stats):
    """Prints the 'Most Likely to Forget Crucial Upgrades' award."""
    if not player_stats:
        return

    forgetful_players_data = []
    for player_name, stats in player_stats.items():
        games_played = stats['games_played']
        if games_played == 0:
            continue

        total_forget_percentage_sum = 0.0
        num_crucial_upgrades = len(CRUCIAL_UPGRADES)
        individual_forget_details = {}

        for tech_name in CRUCIAL_UPGRADES:
            researched_count = stats['crucial_researched'].get(tech_name, 0)
            not_researched_count = games_played - researched_count
            forget_percentage_for_ranking = (not_researched_count / games_played) * 100
            researched_percentage_for_details = (researched_count / games_played) * 100 # Percentage of games researched
            total_forget_percentage_sum += forget_percentage_for_ranking
            individual_forget_details[tech_name] = researched_percentage_for_details
        
        average_forget_percentage = total_forget_percentage_sum / num_crucial_upgrades if num_crucial_upgrades > 0 else 0
        forgetful_players_data.append({
            'name': player_name, 
            'avg_forget': average_forget_percentage, 
            'details': individual_forget_details
        })

    # Sort by average forgetfulness, descending
    forgetful_players_data.sort(key=lambda x: x['avg_forget'], reverse=True)

    if forgetful_players_data:
        print("\n--- \"Most Likely to Forget Crucial Upgrades\" Award ---")
        # Winner
        winner = forgetful_players_data[0]
        # Details show percentage of games where upgrade WAS researched for clarity
        winner_details_str = ", ".join([f"{tech}: {winner['details'][tech]:.0f}%" for tech in CRUCIAL_UPGRADES])
        print(f"Winner: {winner['name']} (Average Forgetfulness: {winner['avg_forget']:.1f}%)")
        print(f"  - Details: {winner_details_str} of games.")

        # Runner-up
        if len(forgetful_players_data) > 1:
            runner_up = forgetful_players_data[1]
            # Check if runner-up score is different from winner to avoid showing same person or 0% forgetfulness as runner-up if only one person forgot anything
            if runner_up['avg_forget'] < winner['avg_forget'] and runner_up['avg_forget'] > 0:
                runner_up_details_str = ", ".join([f"{tech}: {runner_up['details'][tech]:.0f}%" for tech in CRUCIAL_UPGRADES])
                print(f"  - Second place: {runner_up['name']} (Average Forgetfulness: {runner_up['avg_forget']:.1f}%)")
                print(f"    - Details: {runner_up_details_str} of games.")


def _print_player_leaderboard(player_stats):
    """Prints the player leaderboard with core statistics."""
    print("\n--- Player Leaderboard & Stats ---")
    # Sort by win rate (desc), then wins (desc), then games played (desc)
    sorted_players = sorted(player_stats.items(), key=lambda item: (
        item[1]['wins'] / item[1]['games_for_win_rate'] if item[1].get('games_for_win_rate', 0) > 0 else 0,
        item[1]['wins'],
        item[1]['games_played']
    ), reverse=True)

    for player_name, stats in sorted_players:
        games_for_win_rate = stats.get('games_for_win_rate', 0)
        win_rate = (stats['wins'] / games_for_win_rate * 100) if games_for_win_rate > 0 else 0
        playtime_str = str(timedelta(seconds=int(stats['total_playtime_seconds'])))

        print(f"\n- {player_name}:")
        print(f"  - Games Played: {stats['games_played']}")
        print(f"  - Wins: {stats['wins']} (Win Rate: {win_rate:.1f}% based on {games_for_win_rate} games with a determined winner)")
        print(f"  - Total Playtime: {playtime_str}")


def _print_player_civilization_performance(player_stats):
    """Prints civilization performance statistics for each player."""
    print("\n--- Player Civilization Performance ---")
    # Sort players the same way as in the leaderboard for consistent ordering
    sorted_players = sorted(player_stats.items(), key=lambda item: (
        item[1]['wins'] / item[1]['games_for_win_rate'] if item[1].get('games_for_win_rate', 0) > 0 else 0,
        item[1]['wins'],
        item[1]['games_played']
    ), reverse=True)

    for player_name, stats in sorted_players:
        print(f"\n- {player_name}:")
        if not stats['civs_played']:
            print("  - No civilization data available.")
            continue

        # Find the highest play count for this player's civs
        max_played = max(stats['civs_played'].values())
        # Find all civs with that play count (to handle ties)
        most_played_civs = [civ for civ, count in stats['civs_played'].items() if count == max_played]

        print("  - Most Played Civ(s):")
        for civ in most_played_civs:
            wins = stats['civ_wins'].get(civ, 0)
            civ_games_for_win_rate = stats['civ_games_for_win_rate'].get(civ, 0)
            civ_win_rate = (wins / civ_games_for_win_rate * 100) if civ_games_for_win_rate > 0 else 0
            # 'count' is the total number of times the civ was played
            print(f"    - {civ}: {stats['civs_played'][civ]} game(s), {civ_win_rate:.1f}% win rate (based on {civ_games_for_win_rate} games with a determined winner)")


def _print_overall_civilization_popularity(game_stats):
    """Prints the top 10 most popular civilizations overall."""
    print("\n--- Top 10 Most Popular Civilizations ---")
    sorted_civs = sorted(game_stats['overall_civ_picks'].items(), key=lambda item: item[1], reverse=True)
    print("Most Picked Civilizations Overall:")
    for i, (civ, count) in enumerate(sorted_civs):
        if i >= 10:
            break
        print(f"  - {civ}: {count} times")


def print_report(player_stats, game_stats):
    """Prints the final analytics report."""
    print("\n--- Analysis Complete ---")
    print("\nLAN Party Analytics Report")

    _print_general_game_statistics(game_stats)

    _print_favorite_unit_fanatic(player_stats, game_stats)

    _print_most_balanced_team_matchup(game_stats)

    # --- AWARDS SECTION ---
    _print_wall_street_tycoon_award(player_stats)

    _print_demolition_expert_award(player_stats)

    _print_market_mogul_award(player_stats)

    _print_forgetful_upgrades_award(player_stats)

    _print_bitter_salt_baron(player_stats, game_stats) # Moved here

    _print_player_leaderboard(player_stats)

    _print_player_civilization_performance(player_stats)

    _print_overall_civilization_popularity(game_stats)

# --- Execution ---
if __name__ == "__main__":
    analyze_all_games()
    print_report(player_stats, game_stats)
