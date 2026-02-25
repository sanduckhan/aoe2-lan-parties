# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AoE2 LAN Party Analyzer — a Python tool that parses Age of Empires II replay files (`.aoe2record`) to generate player statistics, leaderboards, fun awards, and TrueSkill competitive ratings for LAN party events.

## Commands

```bash
# Install dependencies
poetry install

# Run full analysis (parses all replays, prints report)
poetry run python main.py

# Calculate TrueSkill ratings and generate evolution plot
poetry run python scripts/calculate_trueskill.py

# Suggest balanced teams (generation mode)
poetry run python scripts/team_balancer.py Player1 Player2 Player3 Player4

# Rebalance existing teams (help the weaker team with minimal changes)
poetry run python scripts/team_balancer.py --team1 Player1 Player2 --team2 Player3 Player4 --weaker 2

# Show player ratings and recommended handicaps
poetry run python scripts/handicap_recommender.py
poetry run python scripts/handicap_recommender.py Player1 Player2  # filter to specific players

# Display game-by-game results
poetry run python scripts/display_game_results.py

# Parse a single replay to JSON
poetry run python scripts/parse_single_game.py path/to/file.aoe2record

# Batch export all replays to JSON
poetry run python scripts/parse.py

# Start the web UI (accessible on LAN at http://<your-ip>:5050)
poetry run python run_web.py

# Formatting and linting
poetry run black .
poetry run flake8
```

## Architecture

### Data Flow

Replay files in `recorded_games/` → `mgz.parse_match()` parsing → validation (>5 min games only) → player alias resolution → stat aggregation → console report output. TrueSkill ratings are calculated separately via `scripts/calculate_trueskill.py` and saved to `player_ratings.json`.

### Core Package (`analyzer_lib/`)

- **config.py** — Single source of truth for all configuration: player aliases, TrueSkill parameters, crucial upgrades list, non-military unit filters, directory paths, and ranking thresholds. Modify this file to add players, adjust parameters, or change tracked metrics.
- **analyze_games.py** — Core parsing and stats engine. `analyze_all_games()` orchestrates the pipeline: parse replays chronologically (datetime extracted from filenames), determine outcomes, aggregate per-player and per-team stats, process action-based metrics (units, market, walls, building deletions, upgrades).
- **report_generator.py** — Formats and prints the analysis report: game stats, fun awards (8 categories), player leaderboard, civilization performance.

### Key Design Decisions

- **Player aliasing**: Players with multiple accounts are consolidated via `PLAYER_ALIASES` in config.py. Applied everywhere during analysis.
- **Chronological ordering**: Games are sorted by datetime parsed from replay filenames (regex). This is critical for losing streak calculation and TrueSkill evolution accuracy.
- **Team roster canonicalization**: Team matchups use sorted tuples of player names as dictionary keys to ensure consistent head-to-head tracking regardless of player order.
- **Action-based stats**: Parsed from replay command stream (inputs/commands), not summary data. This includes units created, market transactions, wall segments, building deletions, and upgrade research.

### Scripts (`scripts/`)

Standalone utilities that import from `analyzer_lib/`.

- **calculate_trueskill.py** — Processes all replays chronologically, computes TrueSkill ratings, generates `player_ratings.json` and a rating evolution plot. Tracks per-game handicap values and computes `avg_handicap_last_30` (average handicap across each player's last 30 rated games).
- **team_balancer.py** — Two modes: (1) **Generation mode** — finds most balanced team splits from a player list using `ts_env.quality()`. (2) **Rebalance mode** (`--team1 ... --team2 ... --weaker N`) — takes existing teams, identifies minimal swaps/moves to help the weaker team, sorted by smallest rating gain first.
- **handicap_recommender.py** — Displays player ratings with average handicap and recommended handicap. Rule: +5% per 300 rating below floor (700), rounded to nearest 5%, applied on top of current average. Imported by `team_balancer.py` for per-player HC display.

### Handicap System

- AoE2 DE handicap: 100–200% in 5% increments, boosts economy and production.
- `player_ratings.json` stores `avg_handicap_last_30` per player (from replay data via forked `mgz` library).
- Recommended HC = current avg HC + bump for players below 700 rating floor, rounded to nearest 5%.
- The `mgz` fork at `github.com/sanduckhan/aoc-mgz` (branch `feat/expose-handicap`) exposes `player.handicap` from replay files.

### Web UI (`web/`)

- **app.py** — Flask routes serving the single-page HTML and JSON API endpoints (`/api/players`, `/api/teams/generate`, `/api/teams/rebalance`).
- **services.py** — Business logic bridge between Flask routes and existing scripts/analyzer_lib. Handles player rating loading, team generation, and rebalance computation.
- **templates/index.html** — Single-page UI with tabs for Ratings, Team Generator, and Game View.
- **static/app.js** — Client-side JavaScript for tab navigation, API calls, and dynamic rendering.
- **static/style.css** — Dark-themed styling for the web interface.

### Key Dependencies

- `mgz` — AoE2 replay file parser (the foundation of all data extraction)
- `trueskill` — Bayesian skill rating system
- `flask` — Web framework for the local UI
- `pandas` / `matplotlib` / `seaborn` — Data analysis and visualization
