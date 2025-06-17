import os
from collections import defaultdict
from mgz.model import parse_match

# --- Configuration ---
RECORDED_GAMES_DIR = 'recorded_games'

def display_game_by_game_results():
    """Loops through recorded games and displays the winner/loser for each game."""
    if not os.path.isdir(RECORDED_GAMES_DIR):
        print(f"Error: Directory '{RECORDED_GAMES_DIR}' not found.")
        return

    print(f"--- Game by Game Results from '{RECORDED_GAMES_DIR}' ---\n")

    # Get a sorted list of game files to process them in a consistent order
    game_files = sorted([f for f in os.listdir(RECORDED_GAMES_DIR) if f.endswith(('.aoe2record', '.mgz', '.mgx'))])

    for filename in game_files:
        file_path = os.path.join(RECORDED_GAMES_DIR, filename)
        print(f"--- Analyzing: {filename} ---")

        try:
            with open(file_path, 'rb') as f:
                match = parse_match(f)

            if not match:
                print("  -> Could not find match data.\n")
                continue

            human_players = [p for p in match.players if hasattr(p, 'profile_id') and p.profile_id is not None]

            # Group players by team
            teams = defaultdict(list)
            for p in human_players:
                team_id = p.team_id
                if isinstance(team_id, list):
                    team_id = team_id[0] if team_id else -1
                teams[team_id].append(p)

            # Determine winning team
            winning_team_id = None
            for team_id, players_in_team in teams.items():
                if any(p.winner for p in players_in_team):
                    winning_team_id = team_id
                    break
            
            if winning_team_id is None and len(teams) > 1:
                print("  -> WARNING: Could not determine a winner for this game.\n")
                continue

            # Display results
            print("  - Winning Team:")
            for player in teams.get(winning_team_id, []):
                print(f"    - {player.name} (Won)")

            print("  - Losing Team(s):")
            for team_id, players_in_team in teams.items():
                if team_id != winning_team_id:
                    for player in players_in_team:
                        print(f"    - {player.name} (Lost)")
            
            print("") # Add a newline for spacing

        except Exception as e:
            print(f"  -> Could not process file: {e}\n")
            continue

if __name__ == "__main__":
    display_game_by_game_results()
