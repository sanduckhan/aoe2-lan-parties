# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AoE2 LAN Party Analyzer — a Python tool that parses Age of Empires II replay files (`.aoe2record`) to generate player statistics, leaderboards, fun awards, and TrueSkill competitive ratings for LAN party events.

## Commands

```bash
# Install dependencies
poetry install

# Run full analysis (registry-first: only parses new replays, rebuilds stats from cache)
poetry run python main.py

# Calculate TrueSkill ratings from registry (no replay parsing)
poetry run python scripts/calculate_trueskill.py

# Suggest balanced teams (generation mode)
poetry run python scripts/team_balancer.py Player1 Player2 Player3 Player4

# Rebalance existing teams (help the weaker team with minimal changes)
poetry run python scripts/team_balancer.py --team1 Player1 Player2 --team2 Player3 Player4 --weaker 2

# Show player ratings and recommended handicaps
poetry run python scripts/handicap_recommender.py
poetry run python scripts/handicap_recommender.py Player1 Player2  # filter to specific players

# Display game-by-game results (reads from analysis_data.json)
poetry run python scripts/display_game_results.py

# Parse a single replay to JSON
poetry run python scripts/parse_single_game.py path/to/file.aoe2record

# Migrate existing replays to game registry (one-time bootstrap)
poetry run python -m server.migrate
poetry run python -m server.migrate --skip-bucket

# Start the web UI (accessible on LAN at http://<your-ip>:5050)
poetry run python run_web.py

# Formatting and linting
poetry run black .
poetry run flake8
```

## Architecture

### Data Flow (Registry-First)

Replay files are parsed **once** and cached in `game_registry.json`. On subsequent runs, only new files are parsed (SHA256-based dedup). All stats and ratings are rebuilt from the registry without touching replay files.

```
recorded_games/*.aoe2record
    → sync_registry_from_disk()        # only parses NEW replays
    → game_registry.json               # cached per-game data (teams, winners, action deltas, etc.)
    → run_trueskill_from_registry()    # rebuilds ratings, returns per-game rating deltas
    → accumulate_stats_from_games()    # rebuilds stats from registry
    → merge rating deltas into game_results
    → analysis_data.json, player_ratings.json, rating_history.json
```

First run: parses all replays (~5-10 min for 500+ files). Subsequent runs with no new replays: ~2 seconds.

### Core Package (`analyzer_lib/`)

- **config.py** — Single source of truth for all configuration: player aliases, TrueSkill parameters, crucial upgrades list, non-military unit filters, directory paths, and ranking thresholds. Modify this file to add players, adjust parameters, or change tracked metrics.
- **registry_builder.py** — Single source of truth for converting a replay file into a `game_registry.json` entry. Key functions:
  - `replay_to_registry_entry(file_bytes, sha256, ...)` — parse replay bytes → registry entry dict (teams, winner, fingerprint, action deltas, status)
  - `sync_registry_from_disk(registry)` — scan local replay files, hash each, skip those already in registry, parse only new ones
  - `compute_game_fingerprint()` — dedup same game recorded by different players
- **registry_stats.py** — Single source of truth for accumulating stats from registry entries. `accumulate_stats_from_games(games)` returns `(player_stats, game_stats, game_results, head_to_head)`.
- **analyze_games.py** — Action-based stat extraction helpers. `extract_single_game_deltas()` extracts per-game unit/market/wall/tech deltas from replay command streams (used during parsing). `_calculate_losing_streaks()` computes max losing streaks (used during stats accumulation).
- **report_generator.py** — Formats and prints the analysis report: game stats, fun awards (8 categories), player leaderboard, civilization performance. Also provides `compute_all_awards()`, `compute_general_stats()`, `compute_player_profiles()`.

### Game Registry (`game_registry.json`)

Central cache storing all extracted data per game. Each entry contains:
- `sha256` — unique file hash (primary key)
- `fingerprint` — game identity hash (dedup across recorders)
- `status` — `processed`, `no_winner`, `too_short`, `unknown_player`, `parse_error`, `duplicate`
- `teams` — player names, civs, winner flags, handicaps, eAPM
- `player_deltas` — per-player action stats (units created, market transactions, walls, buildings deleted, crucial techs)
- `source_path` — relative path to replay file on disk (for download support)
- `datetime`, `duration_seconds`, `filename`, `winning_team_id`

### Key Design Decisions

- **Per-game rating deltas**: `run_trueskill_from_registry()` returns `rating_deltas` (`sha256 → {player → delta}`). These are merged into `game_results` in `analysis_data.json` as `rating_changes`, then served via `/api/games` and displayed in Battle Chronicles next to each player name.
- **Debounced rebuilds**: When replays are uploaded via the web UI, stats/ratings rebuilds are debounced with a 30-second timer (`IncrementalProcessor.REBUILD_DELAY`). Each upload resets the timer. The rebuild only fires once uploads stop for the full delay period, preventing expensive recomputation during bulk uploads.
- **Registry-first architecture**: Replays are parsed once and all extracted data is cached in `game_registry.json`. Stats and ratings are always rebuilt from the registry, never by re-parsing replays.
- **Player aliasing**: Players with multiple accounts are consolidated via `PLAYER_ALIASES` in config.py. Applied during replay parsing in `replay_to_registry_entry()`.
- **Chronological ordering**: Games are sorted by datetime parsed from replay filenames (regex). This is critical for losing streak calculation and TrueSkill evolution accuracy.
- **Team roster canonicalization**: Team matchups use sorted tuples of player names as dictionary keys to ensure consistent head-to-head tracking regardless of player order.
- **Action-based stats**: Parsed from replay command stream (inputs/commands), not summary data. This includes units created, market transactions, wall segments, building deletions, and upgrade research.
- **Fingerprint dedup**: Same game recorded by different players produces different SHA256s but identical fingerprints (based on datetime + player names + civs + teams). Only one copy is kept.

### Server (`server/`)

- **processing.py** — `GameRegistry` class (thread-safe JSON storage with SHA256/fingerprint indexes, `source_path` backfill via `update_source_path()`), `IncrementalProcessor` (handles web uploads: parse → dedup → store → debounced rebuild). Rebuilds are debounced: a 30-second timer resets on each upload, only firing once uploads stop. Delegates parsing to `registry_builder.replay_to_registry_entry()` and stats to `registry_stats.accumulate_stats_from_games()`. Rating deltas from TrueSkill are passed through to `rebuild_analysis_from_registry()` for embedding in game results.
- **storage.py** — S3-compatible bucket operations for replay file storage (upload/download).
- **migrate.py** — One-time bulk migration: scans replay directory, parses all files via `replay_to_registry_entry()`, builds registry, optionally uploads to bucket.

### Scripts (`scripts/`)

Standalone utilities that import from `analyzer_lib/`.

- **calculate_trueskill.py** — Rebuilds TrueSkill ratings from game registry entries. `run_trueskill_from_registry()` is the main entry point (used by `main.py`, `server/processing.py`, and `server/migrate.py`). Returns `(player_ratings, rating_history, lan_events, rating_deltas)` where `rating_deltas` maps `sha256 → {player_name → delta}` for per-game rating impact tracking. Generates `player_ratings.json`, `rating_history.json`, and a rating evolution plot. Tracks per-game handicap values and computes `avg_handicap_last_30`. Also detects LAN events from game clusters.
- **team_balancer.py** — Two modes: (1) **Generation mode** — finds most balanced team splits from a player list using `ts_env.quality()`. (2) **Rebalance mode** (`--team1 ... --team2 ... --weaker N`) — takes existing teams, identifies minimal swaps/moves to help the weaker team, sorted by smallest rating gain first.
- **handicap_recommender.py** — Displays player ratings with average handicap and recommended handicap. Rule: +5% per 300 rating below floor (700), rounded to nearest 5%, applied on top of current average. Imported by `team_balancer.py` for per-player HC display.
- **display_game_results.py** — Reads game results from `analysis_data.json` and prints them (no replay parsing).

### Handicap System

- AoE2 DE handicap: 100–200% in 5% increments, boosts economy and production.
- `player_ratings.json` stores `avg_handicap_last_30` per player (from replay data via forked `mgz` library).
- Recommended HC = current avg HC + bump for players below 700 rating floor, rounded to nearest 5%.
- The `mgz` fork at `github.com/sanduckhan/aoc-mgz` (branch `feat/expose-handicap`) exposes `player.handicap` from replay files.

### Web UI (`web/`)

- **app.py** — Flask routes serving the single-page HTML and JSON API endpoints (`/api/players`, `/api/teams/generate`, `/api/teams/rebalance`, `/api/games`, `/api/games/<sha256>/download`, `/api/awards`, `/api/stats`, `/api/player/<name>`, `/api/rating-history`, `/api/lan-events`, `/api/upload`, `/api/rebuild`).
- **services.py** — Business logic bridge between Flask routes and `analyzer_lib`/scripts. Uses `MtimeCache` for auto-reloading JSON files. Handles player ratings, team generation, rebalance, game history, player profiles, LAN event awards, replay downloads, and upload processing.
- **templates/index.html** — Single-page UI with tabs for Ratings, Awards, Battle Chronicles, Team Generator, Game View, and Uploader.
- **static/app.js** — Client-side JavaScript for tab navigation, API calls, dynamic rendering, rating evolution chart (Chart.js), and sound effects.
- **static/style.css** — Dark medieval-themed styling for the web interface.

### Key Dependencies

- `mgz` — AoE2 replay file parser (the foundation of all data extraction)
- `trueskill` — Bayesian skill rating system
- `flask` — Web framework for the local UI
- `pandas` / `matplotlib` / `seaborn` — Data analysis and visualization (lazy-imported)
