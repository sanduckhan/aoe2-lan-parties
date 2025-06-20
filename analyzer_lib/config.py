# Configuration file for AoE2 LAN Party Analyzer

# Directory where recorded game files (.aoe2record, .mgz, .mgx) are stored.
RECORDED_GAMES_DIR = 'recorded_games'

# Player aliases to consolidate stats for players who might use different names.
# Example: PLAYER_ALIASES = {"OldName1": "CanonicalName", "AnotherName": "CanonicalName"}
PLAYER_ALIASES = {
    "Claquettes Chaussettes": "Boivinos",
    "Boivinos": "Boivinos",
    "LiKiD": "LiKiD",
    "Fatmonkey": "Fatmonkey",
    "youri basmati": "youri basmati",
    "Bigfouine007": "Bigfouine007",
    "Sanduck": "Sanduck",
    "Djokolonel": "Djokolonel",
    "Bedev": "Bedev",
    "Coton Ouaté": "Coton Ouaté",
    "vodkite49": "vodkite49",
    "Jolly Roger": "Jolly Roger",
    "Tfirda": "Tfirda",
    "cornichonmasquez": "cornichonmasquez"
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
# TrueSkill Parameters
TRUESKILL_MU = 25.0              # Initial mean skill
TRUESKILL_SIGMA = TRUESKILL_MU / 3 # Initial skill uncertainty (standard deviation)
TRUESKILL_BETA = TRUESKILL_SIGMA / 3 # Skill variance, lower is more reactive to upsets
TRUESKILL_TAU = TRUESKILL_SIGMA / 100 # Dynamic factor, how much ratings change over time (per game)
TRUESKILL_DRAW_PROBABILITY = 0.10 # Probability of a draw
TRUESKILL_ELO_SCALING_FACTOR = 40 # Factor to scale TrueSkill mu/sigma to ELO-like numbers (e.g., 25*40=1000)
MIN_GAMES_FOR_RANKING = 60       # Minimum games a player must have played to be in the main ranking table
PLOT_MIN_GAMES_THRESHOLD = 5     # Minimum games a player must have played to be included in the rating evolution plot

# Original line to be replaced was just the TRUESKILL_MU line, but we need to insert the new params here.
# So, effectively, we are replacing the start of the TrueSkill params section to include the new ones.
# The actual TRUESKILL_MU line is re-added below to ensure it's not lost.
TRUESKILL_MU = 25.0              # Initial mean skill


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
