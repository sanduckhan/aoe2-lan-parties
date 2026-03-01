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

# Display game-by-game results
poetry run python scripts/display_game_results.py

# Parse a single replay to JSON
poetry run python scripts/parse_single_game.py path/to/file.aoe2record

# Migrate legacy JSON files to SQLite (one-time)
poetry run python scripts/migrate_to_sqlite.py

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

Replay files are parsed **once** and cached in a SQLite database (`aoe2_data.db`). On subsequent runs, only new files are parsed (SHA256-based dedup). All stats and ratings are rebuilt from the registry without touching replay files.

```
recorded_games/*.aoe2record
    → sync_registry_from_disk()        # only parses NEW replays
    → aoe2_data.db (games table)       # cached per-game data (teams, winners, action deltas, etc.)
    → run_trueskill_from_registry()    # rebuilds ratings, returns per-game rating deltas
    → accumulate_stats_from_games()    # rebuilds stats from registry
    → merge rating deltas into game_results
    → aoe2_data.db (player_ratings, rating_history, analysis_cache tables)
```

First run: parses all replays (~5-10 min for 500+ files). Subsequent runs with no new replays: ~2 seconds.

### Core Package (`analyzer_lib/`)

- **config.py** — Single source of truth for all configuration: player aliases, TrueSkill parameters, crucial upgrades list, non-military unit filters, directory paths, DB filename, and ranking thresholds. Modify this file to add players, adjust parameters, or change tracked metrics.
- **db.py** — Central database module. Manages the shared SQLite database (`aoe2_data.db`). Provides schema creation, read/write functions for all derived data tables (player_ratings, rating_history, lan_events, analysis_cache). Uses WAL mode for concurrent access.
- **registry_builder.py** — Single source of truth for converting a replay file into a registry entry. Key functions:
  - `replay_to_registry_entry(file_bytes, sha256, ...)` — parse replay bytes → registry entry dict (teams, winner, fingerprint, action deltas, status)
  - `sync_registry_from_disk(registry)` — scan local replay files, hash each, skip those already in registry, parse only new ones
  - `compute_game_fingerprint()` — dedup same game recorded by different players
- **registry_stats.py** — Single source of truth for accumulating stats from registry entries. `accumulate_stats_from_games(games)` returns `(player_stats, game_stats, game_results, head_to_head)`.
- **analyze_games.py** — Action-based stat extraction helpers. `extract_single_game_deltas()` extracts per-game unit/market/wall/tech deltas from replay command streams (used during parsing). `_calculate_losing_streaks()` computes max losing streaks (used during stats accumulation).
- **report_generator.py** — Formats and prints the analysis report: game stats, fun awards (8 categories), player leaderboard, civilization performance. Also provides `compute_all_awards()`, `compute_general_stats()`, `compute_player_profiles()`.

### Database (`aoe2_data.db`)

Single SQLite database (WAL mode) consolidating all project data. Replaces the previous 4 JSON files (`game_registry.json`, `analysis_data.json`, `player_ratings.json`, `rating_history.json`).

**Tables:**
- `games` — source of truth for all parsed game data (primary key: `sha256`). Teams, player_deltas, and game_level_deltas stored as JSON blobs.
- `player_ratings` — TrueSkill ratings per player (proper columns, indexed by name)
- `rating_history` — per-game rating snapshots (indexed by player_name and game_index)
- `lan_events` — detected LAN event date ranges
- `analysis_cache` — key-value store for computed outputs (awards, general_stats, game_results, player_profiles as JSON blobs)
- `metadata` — key-value for registry metadata (e.g., version)

**Schema rationale:** Flat/tabular data uses proper SQL columns with indexes. Deeply nested structures (teams, awards, profiles) stay as JSON blobs since consumers read them as whole objects.

Each game entry contains:
- `sha256` — unique file hash (primary key)
- `fingerprint` — game identity hash (dedup across recorders)
- `status` — `processed`, `no_winner`, `too_short`, `unknown_player`, `parse_error`, `duplicate`
- `teams` — player names, civs, winner flags, handicaps, eAPM
- `player_deltas` — per-player action stats (units created, market transactions, walls, buildings deleted, crucial techs)
- `source_path` — relative path to replay file on disk (for download support)
- `datetime`, `duration_seconds`, `filename`, `winning_team_id`

### Key Design Decisions

- **SQLite storage**: All data stored in a single `aoe2_data.db` file (WAL mode). Game inserts are O(1) instead of rewriting the entire file. Lookups by SHA256 or fingerprint use indexed queries. No JSON files need to be loaded into memory at startup.
- **Per-game rating deltas**: `run_trueskill_from_registry()` returns `rating_deltas` (`sha256 → {player → delta}`). These are merged into `game_results` in the analysis cache as `rating_changes`, then served via `/api/games` and displayed in Battle Chronicles next to each player name.
- **Debounced rebuilds**: When replays are uploaded via the web UI, stats/ratings rebuilds are debounced with a 60-second timer (`IncrementalProcessor.REBUILD_DELAY`). Every upload resets the timer (including duplicates and errors), so the rebuild only fires once uploads stop for the full delay period. Concurrent rebuilds are prevented: if a rebuild is already running when the timer fires, it re-schedules instead of starting a second one.
- **Registry-first architecture**: Replays are parsed once and all extracted data is cached in the `games` table. Stats and ratings are always rebuilt from the registry, never by re-parsing replays.
- **Player aliasing**: Players with multiple accounts are consolidated via `PLAYER_ALIASES` in config.py. Applied during replay parsing in `replay_to_registry_entry()`.
- **Chronological ordering**: Games are sorted by datetime parsed from replay filenames (regex). This is critical for losing streak calculation and TrueSkill evolution accuracy.
- **Team roster canonicalization**: Team matchups use sorted tuples of player names as dictionary keys to ensure consistent head-to-head tracking regardless of player order.
- **Action-based stats**: Parsed from replay command stream (inputs/commands), not summary data. This includes units created, market transactions, wall segments, building deletions, and upgrade research.
- **Fingerprint dedup**: Same game recorded by different players produces different SHA256s but identical fingerprints (based on datetime + player names + civs + teams). Only one copy is kept.
- **Rating re-centering**: TrueSkill is not zero-sum — average mu drifts downward over time (asymmetric sigma effects, new player entry at 1000). The web API applies a cosmetic offset (`_compute_rating_offset()` in `services.py`) so displayed ratings average to 1000. The offset is applied to all display paths (leaderboard, charts, team generator, profiles) and to `recommended_handicap()` inputs. Raw mu/sigma values in the database and TrueSkill calculations are never modified. Rating deltas (per-game changes) are unaffected since the constant offset cancels out in differences.

### Server (`server/`)

- **processing.py** — `GameRegistry` class (SQLite-backed storage with indexed SHA256/fingerprint lookups, `source_path` backfill via `update_source_path()`), `IncrementalProcessor` (handles web uploads: parse → dedup → store → debounced rebuild). Rebuilds are debounced: a 60-second timer resets on every upload (including duplicates/errors), only firing once uploads stop. Concurrent rebuilds are prevented via `_rebuilding` guard. Full rebuilds (`/api/rebuild`) run in a background thread with progress tracking via `/api/rebuild/status`. Delegates parsing to `registry_builder.replay_to_registry_entry()` and stats to `registry_stats.accumulate_stats_from_games()`. Rating deltas from TrueSkill are passed through to `rebuild_analysis_from_registry()` for embedding in game results.
- **storage.py** — S3-compatible bucket operations for replay file storage (upload/download).
- **migrate.py** — One-time bulk migration: scans replay directory, parses all files via `replay_to_registry_entry()`, builds registry, optionally uploads to bucket.

### Scripts (`scripts/`)

Standalone utilities that import from `analyzer_lib/`.

- **calculate_trueskill.py** — Rebuilds TrueSkill ratings from game registry entries. `run_trueskill_from_registry()` is the main entry point (used by `main.py`, `server/processing.py`, and `server/migrate.py`). Returns `(player_ratings, rating_history, lan_events, rating_deltas)` where `rating_deltas` maps `sha256 → {player_name → delta}` for per-game rating impact tracking. Writes to `player_ratings` and `rating_history` tables in SQLite, and generates a rating evolution plot. Tracks per-game handicap values and computes `avg_handicap_last_30`. Also detects LAN events from game clusters.
- **team_balancer.py** — Two modes: (1) **Generation mode** — finds most balanced team splits from a player list using `ts_env.quality()`. (2) **Rebalance mode** (`--team1 ... --team2 ... --weaker N`) — takes existing teams, identifies minimal swaps/moves to help the weaker team, sorted by smallest rating gain first.
- **handicap_recommender.py** — Displays player ratings with average handicap and recommended handicap. Rule: +5% per 300 rating below floor (700), rounded to nearest 5%, applied on top of current average. Imported by `team_balancer.py` for per-player HC display.
- **display_game_results.py** — Reads game results from the database and prints them (no replay parsing).
- **migrate_to_sqlite.py** — One-time migration script: reads legacy JSON files and populates `aoe2_data.db`. JSON files are kept as backup.

### Handicap System

- AoE2 DE handicap: 100–200% in 5% increments, boosts economy and production.
- The `player_ratings` table stores `avg_handicap_last_30` per player (from replay data via forked `mgz` library).
- Recommended HC = current avg HC + bump for players below 700 rating floor, rounded to nearest 5%.
- The 700 floor was calibrated for average=1000. The web API passes re-centered ratings (avg=1000) to `recommended_handicap()`, so the floor stays meaningful as "300 below group average" regardless of TrueSkill mu drift.
- The `mgz` fork at `github.com/sanduckhan/aoc-mgz` (branch `feat/expose-handicap`) exposes `player.handicap` from replay files.

### Web UI (`web/`)

- **app.py** — Flask routes serving the single-page HTML and JSON API endpoints (`/api/players`, `/api/teams/generate`, `/api/teams/rebalance`, `/api/games`, `/api/games/<sha256>/download`, `/api/awards`, `/api/stats`, `/api/player/<name>`, `/api/rating-history`, `/api/lan-events`, `/api/upload`, `/api/rebuild`, `/api/rebuild/status`).
- **services.py** — Business logic bridge between Flask routes and `analyzer_lib`/scripts. Reads all data from SQLite via `analyzer_lib.db`. Handles player ratings, team generation, rebalance, game history, player profiles, LAN event awards, replay downloads, and upload processing. Applies cosmetic **rating re-centering** (`_compute_rating_offset()`) so the group average is always displayed as 1000 — TrueSkill's non-zero-sum mu drift is corrected at the display layer only. The offset is also passed to `recommended_handicap()` so the 700 floor stays calibrated relative to the group average.
- **templates/index.html** — Single-page UI with tabs for Ratings, Awards, Battle Chronicles, Team Generator, Game View, and Uploader.
- **static/js/** — Client-side JavaScript, split by feature. No build system; files are loaded as separate `<script>` tags in order. Cross-file globals use `var` declarations in `core.js`.
  - `core.js` — State, routing (hash-based), ratings table, player checkboxes, sound effects
  - `chart.js` — Rating evolution chart (Chart.js) with LAN event annotations and zoom
  - `awards.js` — Award definitions, fetch, and render (lazy-loaded on tab open)
  - `history.js` — Game chronicles, infinite scroll, game detail expand, search filter
  - `player-modal.js` — Player profile modal (opened via hash route `#player/Name`)
  - `teams.js` — Team generation, battle plan cards, game view, rebalance, manual setup
  - `admin.js` — Admin dashboard, health cards, rebuild/sync operations, game management
- **static/css/** — Styling split by feature, loaded as separate `<link>` tags. Dark medieval theme with CSS custom properties in `base.css`.
  - `base.css` — Variables, reset, typography, header/nav, tables, buttons, responsive breakpoints
  - `teams.css` — Team generator, suggestion cards, game view, rebalance, manual setup
  - `chart-awards.css` — Rating chart, chart controls, awards grid, event selector
  - `history.css` — History controls, game chronicle cards, game detail expanded view
  - `modal-uploader.css` — Player profile modal, uploader page
  - `admin.css` — Admin auth, health cards, operations, games table

### Key Dependencies

- `mgz` — AoE2 replay file parser (the foundation of all data extraction)
- `trueskill` — Bayesian skill rating system
- `flask` — Web framework for the local UI
- `pandas` / `matplotlib` / `seaborn` — Data analysis and visualization (lazy-imported)
