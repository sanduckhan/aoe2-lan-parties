from . import config
from datetime import timedelta

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
        num_crucial_upgrades = len(config.CRUCIAL_UPGRADES)
        individual_forget_details = {}

        for tech_name in config.CRUCIAL_UPGRADES:
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
        winner_details_str = ", ".join([f"{tech}: {winner['details'][tech]:.0f}%" for tech in config.CRUCIAL_UPGRADES])
        print(f"Winner: {winner['name']} (Average Forgetfulness: {winner['avg_forget']:.1f}%)")
        print(f"  - Details (% Researched): {winner_details_str} of games.")

        # Runner-up
        if len(forgetful_players_data) > 1:
            runner_up = forgetful_players_data[1]
            # Check if runner-up score is different from winner to avoid showing same person or 0% forgetfulness as runner-up if only one person forgot anything
            if runner_up['avg_forget'] < winner['avg_forget'] and runner_up['avg_forget'] > 0:
                runner_up_details_str = ", ".join([f"{tech}: {runner_up['details'][tech]:.0f}%" for tech in config.CRUCIAL_UPGRADES])
                print(f"  - Second place: {runner_up['name']} (Average Forgetfulness: {runner_up['avg_forget']:.1f}%)")
                print(f"    - Details (% Researched): {runner_up_details_str} of games.")


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
