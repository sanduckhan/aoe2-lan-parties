# AoE2 LAN Party Analyzer

This project analyzes Age of Empires II recorded game files (typically from LAN parties) to generate interesting statistics, player leaderboards, and fun awards.

## Prerequisites

- Python 3.9+ (tested with Python 3.9, see `pyproject.toml` for exact version constraints)
- [Poetry](https://python-poetry.org/docs/#installation) for dependency management.

## Setup

1.  **Clone the repository (if you haven't already):**
    ```bash
    git clone <your-repository-url>
    cd aoe2-lan-party-analyzer
    ```

2.  **Install dependencies using Poetry:**
    This will create a virtual environment and install the necessary packages (`aoc-mgz`).
    ```bash
    poetry install
    ```

## Directory Structure

-   `main.py`: The main entry point script. Run this to perform the full analysis and generate the report.
-   `analyzer_lib/`: This directory forms the core Python package for the analyzer.
    -   `__init__.py`: Makes `analyzer_lib` a Python package.
    -   `analyze_games.py`: Contains the primary logic for parsing replay files, processing game data, and aggregating statistics.
    -   `report_generator.py`: Responsible for formatting and printing the final analytics report to the console.
    -   `config.py`: Stores configuration constants such as the path to replay files, player aliases, and lists of crucial upgrades or non-military units.
-   `scripts/`: Contains various utility and standalone scripts.
    -   `parse_single_game.py`: A command-line utility to parse a single AoE2 replay file and save its structured data as a JSON file. Useful for debugging or detailed inspection of one game. (Original path: root)
    -   `display_game_results.py`: Iterates through game replay files in `recorded_games/`, parses each, and prints a game-by-game summary identifying winning and losing players. (Original path: root)
    -   `debug_summary_output.py`: Processes a replay file using `mgz.summary.Summary` and dumps the entire `Summary` object to a JSON file for deep inspection of its raw data structure. (Original path: root)
    -   `parse.py`: A script to parse all replay files in the `recorded_games/` directory and save each as a separate JSON file in the `parsed_games/` directory. (Original path: root)
    -   `calculate_trueskill.py`: A standalone script to calculate and display player rankings using the TrueSkill algorithm. It processes replay files chronologically, updating player ratings after each game. This script is independent of the main analysis pipeline and is designed for generating a competitive leaderboard. It only considers games where all players are defined in the `PLAYER_ALIASES` map in `config.py`. To run it: `poetry run python3 scripts/calculate_trueskill.py`.
-   `recorded_games/`: Place your `.aoe2record` (or other supported replay) files in this directory. This is the primary input for `main.py`.
-   `parsed_games/`: This directory can be used by scripts like `scripts/parse_single_game.py` or `scripts/parse.py` to store JSON versions of individual parsed replays. The main analysis via `main.py` processes replays directly from `recorded_games/` in memory.
-   `pyproject.toml`: Poetry configuration file, defining project metadata and dependencies.
-   `requirements.txt`: Standard Python requirements file, typically generated from `poetry.lock` for environments where Poetry is not used.

## Usage

1.  **Place your replay files:**
    Ensure your Age of Empires II recorded game files (e.g., `.aoe2record`) are in the `recorded_games/` directory.

2.  **Run the analysis:**
    Activate the Poetry virtual environment and run the main analysis script:
    ```bash
    poetry shell
    python main.py
    ```
    The script (`main.py`) will orchestrate the parsing of each replay from the `recorded_games/` directory (using `analyzer_lib.analyze_games`), generate statistics, and then print a consolidated analytics report to the console (using `analyzer_lib.report_generator`).

## Awards Implemented

-   Favorite Unit Fanatic
-   The Bitter Salt Baron (longest losing streak)
-   Most Balanced Team Matchup
-   "The Wall Street Tycoon" (most wall segments built)
-   "The Demolition Expert" (most buildings deleted)
-   "The Market Mogul" (most market transactions & resources traded)
-   "Most Likely to Forget Crucial Upgrades" (tracks who forgets key economic/blacksmith upgrades)

## Contributing

(TODO: Add contribution guidelines if others will be working on this.)

## Understanding the Parsed Game Data (JSON Structure)

The `parse_single_game.py` script uses the `aoc-mgz` library's `parse_match` function to process replay files and then serializes the output to JSON. The structure of this JSON file is complex and reflects the rich data available in AoE2 replays. The following is a summary based on observed data; the exact fields can vary based on game version and recorded events.

### Top-Level Keys:

-   **`version`**: Game version identifier (e.g., "DE" for Definitive Edition).
-   **`game_version`**: Specific game version string (e.g., "VER 9.4").
-   **`build_version`**: Build number of the game (e.g., 145651).
-   **`log_version`**: Version of the replay log format.
-   **`save_version`**: Save version of the game file.
-   **`timestamp`**: Date and time the game was recorded (e.g., "2025-06-14 00:48:41").
-   **`duration`**: Total game duration (e.g., "0:56:07.626000").
-   **`completed`**: Boolean, true if the game reached a conclusion.
-   **`cheats`**: Boolean, true if cheats were enabled.
-   **`guid`**: Unique identifier for the game match.
-   **`hash`**: A hash of the replay content (distinct from `file.hash`).
-   **`dataset`**: Game dataset (e.g., "Definitive Edition").
-   **`dataset_id`**: ID for the dataset.
-   **`lobby`**: Name of the game lobby if applicable (e.g., "Nomad 1100-1300 rdm civ 3v3/4v4").
-   **`file`**: Object containing metadata about the original replay file:
    -   `hash`: SHA1 hash of the file.
    -   `size`: File size in bytes.
    -   `language`: Language of the game client (e.g., "fr").
-   **`map`**: Detailed information about the game map:
    -   `name`: Map name (e.g., "ZN@HyperRandomNomad", "Arena").
    -   `custom`: Boolean, true if it's a custom map.
    -   `id`: Map ID.
    -   `size`: Map size description (e.g., "Large").
    -   `dimension`: Map dimensions (e.g., 220 for a large map).
    -   `seed`: Map generation seed.
    -   `tiles`: Array of map tile data, including `position` and `terrain` ID.
-   **`settings` / Game Parameters** (various top-level keys define game settings):
    -   `type`: Game type description (e.g., "Random Map").
    -   `type_id`: ID for the game type.
    -   `difficulty`: Game difficulty (e.g., "Hardest").
    -   `difficulty_id`: ID for difficulty.
    -   `population`: Population limit.
    -   `speed`: Game speed (e.g., "Fast").
    -   `speed_id`: ID for game speed.
    -   `map_reveal`: Map visibility setting (e.g., "Normal").
    -   `map_reveal_id`: ID for map visibility.
    -   `starting_age`: Starting age (e.g., "Dark").
    -   `starting_age_id`: ID for starting age.
    -   `diplomacy_type`: (e.g., "TG" for Team Game).
    -   `lock_teams`, `lock_speed`, `team_together`, `multiqueue`, `hidden_civs`, `all_technologies`, `allow_specs`, `private`, `rated`: Booleans for various game settings.
-   **`players`**: An array of player objects. Each player object contains:
    -   `name`: Player's in-game name.
    -   `number`: Player number (1-8).
    -   `profile_id`: Player's profile ID.
    -   `civilization`: Civilization name (e.g., "Georgians").
    -   `civilization_id`: ID of the civilization.
    -   `color`: Player color name.
    -   `color_id`: Player color ID.
    -   `team_id`: The team number the player belongs to.
    -   `winner`: Boolean, true if the player was on the winning team.
    -   `eapm`: Effective Actions Per Minute (if available).
    -   `rate_snapshot`: Player's rating at the time of the game.
    -   `objects`: List of initial units/buildings for the player, with `name`, `object_id`, `position`, etc.
    -   Nested `team` objects can appear if players are grouped into teams, showing teammates' details.
-   **`teams`**: Often an array defining team structures, usually by listing player numbers per team. Player objects also contain `team_id` for individual team assignment.
-   **`gaia`**: Array of Gaia (neutral) objects on the map, with `name`, `object_id`, `position`, etc. (e.g., "Elephant", "Gold Mine").
-   **`chat`**: Array of chat messages, each with `timestamp`, `player` (sender), `message`, and `audience`.

### Player Commands (`inputs` key):
This is a crucial list of **player-initiated commands** and is heavily used by `analyze_games.py` for award calculations. Each item in the `inputs` array represents a command issued by a player.
-   `player`: Player number who issued the command.
-   `timestamp`: When the command was issued.
-   `type`: The general category of the command. Examples from CSV: "Target", "De Tribute", "Resign", "Reseed", "Patrol". Other common types include "Build", "Research", "Train", "Wall", "Delete", "Buy", "Sell".
-   `param`: Often a human-readable name for the target of the command, like the name of a unit, building, or technology (e.g., "Man-at-Arms", "House", "Loom").
-   `payload`: A dictionary with detailed parameters for the command:
    -   `unit_id`, `building_id`, `technology_id`: Specific IDs for units, buildings, or techs.
    -   `object_ids`: Array of object IDs being commanded.
    -   `x`, `y`: Coordinates for actions like building placement or movement.
    -   `x_end`, `y_end`: End coordinates for patrol or attack-move.
    -   `resource_id`, `amount`: For transactions (Buy/Sell) or tributes.
    -   `formation_id`, `stance_id` (usually part of `command_id` interpretation).
    -   `message`: For chat inputs.

### Game Events (`actions` key):
This list contains more granular, timed game events. These are distinct from `inputs` and might represent lower-level game engine events, automated processes, or the results of complex commands. While `inputs` capture player intent, `actions` often capture the execution or specific sub-events.
-   `player`: Player number associated with the event.
-   `timestamp`: Precise time of the event.
-   `type`: Type of game event. Examples from CSV: "RESIGN", "DE_QUEUE" (dequeue from production), "DE_MULTI_GATHERPOINT", "DE_ATTACK_MOVE", "DE_TRANSFORM" (e.g. Trebuchet pack/unpack). Some types like "RESIGN" might appear in both `inputs` and `actions` but represent different stages or aspects of the event.
-   `position`: `x`, `y` coordinates related to the event.
-   `payload`: Details specific to the event type:
    -   `command`, `command_id`: Game-internal command identifiers (e.g., "Farm Autoqueue").
    -   `order`, `order_id`: Specific orders (e.g., "Garrison").
    -   `unit`, `building`, `technology`: Names of involved entities.
    -   `unit_id`, `building_id`, `technology_id`: IDs of involved entities.
    -   `amount`, `resource`, `resource_id`: For resource-related events.
    -   `target_id`, `target_type`: Information about the target of an action.

To explore the exact structure for a specific replay, you can examine the JSON files generated in the `parsed_games/` directory or use the `debug_summary_output.py` script for a more direct view of the `aoc-mgz` objects.
