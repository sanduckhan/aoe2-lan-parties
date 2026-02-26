# PRD: Server Processing Pipeline

## Introduction

The AoE2 LAN Party Analyzer currently processes all replay files in a batch: replays are collected manually into `recorded_games/`, then `main.py` parses everything from scratch to produce stats, ratings, and awards. This PRD covers the core server-side processing pipeline that enables event-driven, incremental updates: when a replay file is uploaded, the server parses it, stores it in a Railway Bucket, registers it in a game registry, rebuilds TrueSkill ratings from registry metadata, and updates the analysis data.

This is the foundational backend component. The API endpoints that call into this pipeline are covered in PRD 2 (Server API & Cache).

## Goals

- Accept an uploaded `.aoe2record` file and process it end-to-end without re-parsing any previously processed replays
- Store replay files durably in a Railway Bucket (S3-compatible object storage)
- Maintain a `game_registry.json` as the single source of truth for all known games, with two-layer deduplication: SHA256 (exact file bytes) and game fingerprint (metadata-based, catches the same game recorded by different players)
- Store per-game stat deltas (units created, market transactions, wall segments, building deletions, crucial upgrades, handicaps) in the registry so that awards can be recomputed for any subset of games without re-parsing replays
- Rebuild TrueSkill ratings from registry metadata after each new game (full rebuild, ~1-2s for ~500 games)
- Update `analysis_data.json`, `player_ratings.json`, and `rating_history.json` after each upload

## User Stories

### US-001: Store replay in Railway Bucket
**Description:** As a server operator, I want uploaded replay files archived in durable S3-compatible storage so that replays are never lost and can be re-processed if needed.

**Acceptance Criteria:**
- [ ] `server/storage.py` module exists with `upload_replay(file_bytes, sha256)`, `download_replay(sha256)`, and `list_replays()` functions
- [ ] Replays are stored as `replays/{sha256}.aoe2record` in the bucket
- [ ] Bucket credentials are read from env vars: `BUCKET_ENDPOINT`, `BUCKET_ACCESS_KEY_ID`, `BUCKET_SECRET_ACCESS_KEY`, `BUCKET_NAME`
- [ ] `upload_replay` is idempotent (re-uploading the same SHA256 overwrites with identical content, no error)
- [ ] `list_replays` returns a list of dicts with at least `sha256` and `size` keys

### US-002: Register game in registry with deduplication
**Description:** As the processing pipeline, I want to register each game with two-layer dedup so that both exact re-uploads (same SHA256) and same-game-different-recorder uploads (same fingerprint) are rejected without re-processing.

**Acceptance Criteria:**
- [ ] `GameRegistry` class in `server/processing.py` manages `game_registry.json`
- [ ] `has_game(sha256) -> bool` checks for exact file duplicates in O(1) via `_sha256_set`
- [ ] `has_fingerprint(fingerprint) -> bool` checks for same-game duplicates in O(1) via `_fingerprint_set`
- [ ] `compute_game_fingerprint(game_datetime, teams)` computes a canonical SHA256 from game datetime + sorted player names/civs/teams — identical regardless of which player recorded the game
- [ ] `add_game(entry)` appends to the games list and updates both the SHA256 and fingerprint indexes
- [ ] Fingerprint duplicates are silently rejected (not stored in the registry)
- [ ] File writes are atomic (write to `.tmp`, then `os.rename`)
- [ ] All registry operations are thread-safe via `threading.Lock`
- [ ] Registry JSON structure matches the schema defined in Functional Requirements

### US-003: Parse and validate uploaded replay
**Description:** As the processing pipeline, I want to parse an uploaded replay file and validate it (duration, known players) so that only valid games affect ratings and stats.

**Acceptance Criteria:**
- [ ] `IncrementalProcessor.process_new_replay(file_bytes, sha256, uploader_info)` parses the replay using `mgz.parse_match()`
- [ ] Games shorter than 5 minutes are registered with `status: "too_short"` and do not affect ratings/stats
- [ ] Games with unknown players (not in `config.PLAYER_ALIASES`) are registered with `status: "unknown_player"`
- [ ] Games that fail to parse are registered with `status: "parse_error"`
- [ ] Games with no winner are registered with `status: "no_winner"` and do not affect TrueSkill (but are included in general game stats and player profiles)
- [ ] Successfully processed games are registered with `status: "processed"`

### US-004: Extract per-game stat deltas during parse
**Description:** As the processing pipeline, I want to extract per-game stat increments (units created, market transactions, wall segments, building deletions, crucial upgrades, handicaps) during replay parsing so that these deltas can be stored in the registry and used to recompute awards for any subset of games.

**Acceptance Criteria:**
- [ ] New function `extract_single_game_deltas(match_obj, human_players)` in `analyzer_lib/analyze_games.py`
- [ ] Returns a dict keyed by player name, each containing: `units_created` (dict), `total_units_created` (int), `market_transactions` (int), `total_resource_units_traded` (int), `wall_segments_built` (int), `buildings_deleted` (int), `crucial_researched` (dict of tech_name -> 1)
- [ ] Also returns game-level deltas: `total_units_created_overall` (int)
- [ ] Uses the same parsing logic as `_process_action_based_stats()` but operates on a single game without mutating module-level globals
- [ ] Player aliases are applied to names in the returned dict

### US-005: Rebuild TrueSkill from registry metadata
**Description:** As the processing pipeline, I want to rebuild all TrueSkill ratings from the game registry after each new game so that ratings are always consistent, even when games are uploaded out of chronological order.

**Acceptance Criteria:**
- [ ] New function `run_trueskill_from_registry(registry_games)` in `scripts/calculate_trueskill.py`
- [ ] Takes a list of game entries from the registry (only those with `status: "processed"`)
- [ ] Constructs lightweight `GameData`-compatible objects from registry metadata (teams, winning_team_id, datetime, handicaps) without parsing replay files
- [ ] Sorts games chronologically by datetime, then processes them through `TrueSkillCalculator`
- [ ] Saves `player_ratings.json` and `rating_history.json` (with LAN events) using existing `ReportGenerator.save_ratings_to_json()`
- [ ] Returns the player ratings map, rating history, and LAN events for downstream use
- [ ] Existing `run_trueskill()` function is preserved unchanged for standalone/migration use

### US-006: Update analysis data after new game
**Description:** As the processing pipeline, I want to update `analysis_data.json` after each new game so that the web UI reflects the latest stats without a full batch re-analysis.

**Acceptance Criteria:**
- [ ] New function `rebuild_analysis_from_registry(registry)` in `server/processing.py` (or `analyzer_lib/analyze_games.py`)
- [ ] Iterates over all `"processed"` and `"no_winner"` games in the registry, sorted chronologically
- [ ] Accumulates `player_stats` and `game_stats` from stored deltas + core metadata (wins, playtime, civs, eAPM)
- [ ] Computes `game_results` list and `head_to_head` from registry team/winner data
- [ ] Calls `_calculate_losing_streaks()` on the reconstructed player game chronology
- [ ] Calls `compute_all_awards()`, `compute_general_stats()`, `compute_player_profiles()` from `report_generator.py`
- [ ] Writes the complete `analysis_data.json`
- [ ] The output matches the structure produced by the current `main.py` pipeline

### US-007: End-to-end processing orchestration
**Description:** As the processing pipeline, I want a single entry point that orchestrates the full processing of a new replay: parse, validate, extract deltas, store in bucket, register in registry, rebuild TrueSkill, and update analysis data.

**Acceptance Criteria:**
- [ ] `IncrementalProcessor.process_new_replay()` returns a dict with: `status` (string), `sha256`, `filename`, `datetime`, `teams` summary, and `message` (human-readable)
- [ ] On duplicate SHA256: returns immediately with `status: "duplicate"` without any processing
- [ ] On duplicate fingerprint (same game recorded by a different player): returns `status: "duplicate"` without storing the entry or triggering rebuilds
- [ ] On successful processing: all JSON files (`game_registry.json`, `player_ratings.json`, `rating_history.json`, `analysis_data.json`) are updated before the function returns
- [ ] Processing is serialized via a lock (no concurrent processing of two replays)
- [ ] Errors during bucket upload do not prevent registry update and rating rebuild (bucket is for archival, not critical path)

### US-008: Full rebuild from bucket replays
**Description:** As a server operator, I want to rebuild all data from scratch by re-downloading and re-parsing all replays from the bucket so that I can recover from corrupted data or apply config changes (e.g., new player aliases).

**Acceptance Criteria:**
- [ ] `IncrementalProcessor.full_rebuild()` downloads all replays from the bucket, parses each one, rebuilds the registry, then runs TrueSkill rebuild and analysis rebuild
- [ ] Existing `game_registry.json` is replaced entirely (not merged)
- [ ] Progress is logged (e.g., "Processing replay 42/278...")
- [ ] Returns a summary dict with total games processed, skipped counts by reason, and duration

## Functional Requirements

- FR-1: Create `server/` package with `__init__.py`, `storage.py`, and `processing.py`
- FR-2: `server/storage.py` uses `boto3` to interact with Railway Bucket (S3-compatible). Connection is initialized lazily on first use. Env vars: `BUCKET_ENDPOINT`, `BUCKET_ACCESS_KEY_ID`, `BUCKET_SECRET_ACCESS_KEY`, `BUCKET_NAME`.
- FR-3: `server/processing.py` contains `GameRegistry` class. Registry file path is `{DATA_DIR}/game_registry.json` where `DATA_DIR` comes from `config.DATA_DIR`.
- FR-4: Registry JSON schema:
  ```json
  {
    "games": [
      {
        "sha256": "a1b2c3...",
        "filename": "MP Replay v101.2.x @2023.03.17 204659 (6).aoe2record",
        "datetime": "2023-03-17T20:46:59",
        "uploaded_at": "2026-02-26T14:30:00",
        "status": "processed",
        "duration_seconds": 2894.5,
        "teams": {
          "0": [{"name": "LiKiD", "civ": "Britons", "winner": true, "handicap": 100, "eapm": 45}],
          "1": [{"name": "Sanduck", "civ": "Franks", "winner": false, "handicap": 110, "eapm": 32}]
        },
        "winning_team_id": "0",
        "fingerprint": "d4e5f6...",
        "player_deltas": {
          "LiKiD": {
            "units_created": {"Knight": 12, "Crossbowman": 30},
            "total_units_created": 42,
            "market_transactions": 5,
            "total_resource_units_traded": 1200,
            "wall_segments_built": 15,
            "buildings_deleted": 2,
            "crucial_researched": {"Loom": 1, "Wheelbarrow": 1}
          }
        },
        "game_level_deltas": {
          "total_units_created_overall": 84
        }
      }
    ],
    "total_processed": 278,
    "last_updated": "2026-02-26T14:30:00"
  }
  ```
- FR-5: `GameRegistry` loads the full registry into memory on init. Maintains `_sha256_set: set` for O(1) exact-file dedup and `_fingerprint_set: set` for O(1) same-game dedup. Writes are atomic (`os.rename` from `.tmp` file).
- FR-6: `IncrementalProcessor` is initialized with a `GameRegistry` instance and references to storage functions. It holds a `threading.Lock` for serialized processing.
- FR-7: `extract_single_game_deltas(match_obj, human_players)` in `analyzer_lib/analyze_games.py` reuses the same logic as `_process_action_based_stats()` but writes to local dicts instead of module-level globals. Returns `(player_deltas: dict, game_deltas: dict)`.
- FR-8: `run_trueskill_from_registry(registry_games)` in `scripts/calculate_trueskill.py` creates a minimal `GameData`-like wrapper from each registry entry's `teams`, `winning_team_id`, `datetime`, and handicap data. Passes these through the existing `TrueSkillCalculator` and `ReportGenerator`.
- FR-9: `rebuild_analysis_from_registry(registry)` reconstructs `player_stats`, `game_stats`, `game_results`, and `head_to_head` from registry entries. For each game: accumulates core stats (games_played, wins, playtime, civs, eAPM) from `teams` metadata, and action-based stats from `player_deltas`. Then calls existing `report_generator` functions for awards/profiles.
- FR-10: Add `DATA_DIR` to `analyzer_lib/config.py`: `DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`. All JSON output paths (`player_ratings.json`, `rating_history.json`, `analysis_data.json`, `game_registry.json`) use `DATA_DIR` as their base directory.
- FR-11: Add `API_KEY` to `analyzer_lib/config.py`: `API_KEY = os.environ.get("API_KEY", "")`. Used by the API layer (PRD 2) but defined here as the central config module.
- FR-12: Add `boto3` to project dependencies in `pyproject.toml`.

## Non-Goals

- This PRD does NOT cover the HTTP API endpoints (`/api/upload`, `/api/rebuild`, etc.) — see PRD 2
- This PRD does NOT cover cache invalidation in `web/services.py` — see PRD 2
- This PRD does NOT cover per-LAN-event award computation — see PRD 3
- This PRD does NOT cover the Windows uploader client — see PRD 4
- This PRD does NOT cover the one-time migration script from `recorded_games/` or Dockerfile changes — see PRD 5
- No UI changes
- No changes to the existing `main.py` batch pipeline (it continues to work as-is for local use)
- No plot generation during server-side processing (TrueSkill plot is a local-only feature)

## Technical Considerations

- **mgz dependency**: The replay parser (`mgz.model.parse_match`) requires the forked version at `github.com/sanduckhan/aoc-mgz` (branch `feat/expose-handicap`). The server Docker image must install this fork.
- **Thread safety**: `GameRegistry` uses `threading.Lock` for all reads/writes. `IncrementalProcessor` uses a separate lock to serialize the entire processing pipeline. With gunicorn (2 workers), each worker gets its own process, so in-process locks are sufficient. If workers share files, atomic writes prevent corruption.
- **Performance at scale**: Full TrueSkill rebuild from ~500 registry entries takes ~1-2 seconds (no file I/O, just computation). Analysis rebuild iterates the registry once and calls `report_generator` functions. Total processing time per upload should be under 5 seconds.
- **Existing code reuse**: `TrueSkillCalculator`, `ReportGenerator`, `detect_lan_events()` from `calculate_trueskill.py` are reused as-is. `compute_all_awards()`, `compute_general_stats()`, `compute_player_profiles()` from `report_generator.py` are reused as-is. Only `analyze_games.py` needs a new function (`extract_single_game_deltas`).
- **`GameData` compatibility**: `run_trueskill_from_registry` needs to feed data into `TrueSkillCalculator.update_ratings_for_game()`, which expects a `GameData` object. The cleanest approach is to add a `GameData.from_registry_entry(entry)` classmethod that constructs a `GameData` from a registry dict, creating lightweight player stub objects with `name`, `team_id`, `winner`, and `handicap` attributes.
- **Module-level globals in `analyze_games.py`**: The current `player_stats` and `game_stats` are module-level defaultdicts (lines 11-43). `extract_single_game_deltas` must NOT use these globals — it creates fresh local dicts. The `rebuild_analysis_from_registry` function similarly creates fresh dicts, never touching the globals.
- **Losing streaks**: Recomputed from the full chronological game list during `rebuild_analysis_from_registry`. Each registry entry with a winner contributes a `won: bool` entry to `player_game_chronology`, sorted by datetime. Then `_calculate_losing_streaks()` from `analyze_games.py` is called on the reconstructed chronology.

## Success Metrics

- A single replay upload triggers processing and updates all 4 JSON files within 5 seconds
- Uploading a duplicate SHA256 returns immediately without any file writes
- Uploading the same game recorded by a different player (different SHA256, same fingerprint) returns duplicate without storing the entry
- After processing N games via the pipeline, the output JSON files (`player_ratings.json`, `analysis_data.json`) match the output of running `main.py` on the same set of replays (verified during migration — PRD 5)
- Full rebuild from bucket (re-download + re-parse + rebuild) completes in under 10 minutes for 500 replays

## Open Questions

- Should we add a `game_index` field to registry entries (for TrueSkill history compatibility), or let it be computed dynamically during rebuild based on chronological sort order? Using dynamic computation is simpler and avoids index gaps.
- Should `rebuild_analysis_from_registry` live in `server/processing.py` or `analyzer_lib/analyze_games.py`? Since it imports from both `analyze_games` and `report_generator`, and is only used server-side, `server/processing.py` seems more appropriate.
- How should we handle the case where a config change (e.g., new player alias) retroactively makes previously `"unknown_player"` games valid? The `/api/rebuild` endpoint (PRD 2) will handle this by re-parsing all replays from the bucket, but should we also store the original player names in the registry for debugging?
