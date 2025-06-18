# Configuration file for AoE2 LAN Party Analyzer

# Directory where recorded game files (.aoe2record, .mgz, .mgx) are stored.
RECORDED_GAMES_DIR = 'recorded_games'

# Player aliases to consolidate stats for players who might use different names.
# Example: PLAYER_ALIASES = {"OldName1": "CanonicalName", "AnotherName": "CanonicalName"}
PLAYER_ALIASES = {
    "Claquettes Chaussettes": "Boivinos",
    "Boivinos": "Boivinos"
}

# List of crucial upgrades. Used for the 'Most Likely to Forget Crucial Upgrade' award.
# These are examples, adjust as per your game version and what you consider crucial.
CRUCIAL_UPGRADES = sorted([
    "Loom",
    "Wheelbarrow",
    "Bow Saw",
    "Double-Bit Axe",
    "Horse Collar",
    # Add economic building upgrades if desired (e.g., Market, Blacksmith)
    # Add military unit line upgrades if desired (e.g., Man-at-Arms, Crossbowman, Knight)
])

# Set of unit names that are considered non-military. 
# Used to filter units for certain stats, e.g., when determining favorite military unit.
NON_MILITARY_UNITS = {
    "Villager",
    "Fishing Ship",
    "Trade Cart",
    "Trade Cog",
    # Add other non-combat/economic units if needed (e.g., "Transport Ship" if not used for combat drops)
}

# You can add other configurations here as needed, for example:
# MIN_GAME_DURATION_MINUTES = 5
# TEAM_GAME_MIN_PLAYERS = 4
