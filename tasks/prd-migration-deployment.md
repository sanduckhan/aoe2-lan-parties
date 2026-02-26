# PRD: Migration & Deployment

## Introduction

The AoE2 LAN Party Analyzer currently runs locally and deploys via a minimal Dockerfile that copies pre-computed JSON files. This PRD covers two things: (1) a one-time migration script that bootstraps the new server-side data model from the existing `recorded_games/` directory, and (2) a complete rewrite of the Dockerfile and deployment configuration for Railway so the server can parse replays, store them in a bucket, and serve the web UI.

## Goals

- Migrate all existing replay files (~280 games) into the new pipeline: parse each, build `game_registry.json`, upload to Railway Bucket, generate all JSON data files
- Rewrite the Dockerfile to include the `mgz` fork, all server modules, and proper dependencies
- Configure Railway deployment with persistent volume for JSON data files and bucket for replay archival
- Verify that migrated data matches the output of the current `main.py` batch pipeline
- Keep the existing local development workflow (`poetry run python main.py`) working unchanged

## User Stories

### US-001: Migrate existing replays to game registry
**Description:** As the server operator, I want to convert all existing replays into the new registry format so that the server starts with full historical data.

**Acceptance Criteria:**
- [ ] `server/migrate.py` script exists
- [ ] Scans `recorded_games/` directory for all `.aoe2record` files
- [ ] Computes SHA256 for each file
- [ ] Parses each with `mgz.parse_match()`, extracts metadata and per-game stat deltas (using `extract_single_game_deltas` from PRD 1)
- [ ] Builds a complete `game_registry.json` with all games sorted chronologically
- [ ] Counts of processed/skipped games are printed at the end
- [ ] Script can be re-run safely (re-generates registry from scratch)

### US-002: Upload replays to Railway Bucket during migration
**Description:** As the server operator, I want all existing replays archived in the Railway Bucket during migration so that the full rebuild endpoint can re-parse everything from the bucket.

**Acceptance Criteria:**
- [ ] Migration script uploads each replay to the bucket using `server/storage.py` functions
- [ ] Replays are stored as `replays/{sha256}.aoe2record`
- [ ] If bucket env vars are not set (local dev), bucket upload is skipped with a warning
- [ ] Progress is logged: "Uploading to bucket: 42/278..."

### US-003: Generate all data files from registry
**Description:** As the server operator, I want the migration to produce all JSON data files from the registry so that the web UI works immediately after migration.

**Acceptance Criteria:**
- [ ] After building the registry, migration runs `run_trueskill_from_registry()` to generate `player_ratings.json` and `rating_history.json`
- [ ] Migration runs `rebuild_analysis_from_registry()` to generate `analysis_data.json`
- [ ] All output files are written to `config.DATA_DIR`
- [ ] Output can be compared against current `main.py` output to verify correctness

### US-004: Rewrite Dockerfile for full server
**Description:** As the server operator, I want the Docker image to include all dependencies needed for replay parsing and processing so that the server can handle uploads.

**Acceptance Criteria:**
- [ ] Dockerfile installs `mgz` fork from git (`pip install git+https://github.com/sanduckhan/aoc-mgz.git@feat/expose-handicap`)
- [ ] Dockerfile installs all Python dependencies: `flask`, `trueskill`, `gunicorn`, `boto3`, `pandas` (needed by report_generator indirectly)
- [ ] Dockerfile copies all necessary modules: `analyzer_lib/`, `scripts/`, `web/`, `server/`
- [ ] Dockerfile sets `DATA_DIR` env var to `/app/data` (Railway persistent volume mount point)
- [ ] Dockerfile does NOT copy `recorded_games/` or pre-computed JSON files (these live on the persistent volume)
- [ ] CMD runs gunicorn with appropriate timeout for long rebuild requests

### US-005: Configure Railway deployment
**Description:** As the server operator, I want clear deployment instructions for Railway so that the server is properly configured with persistent storage and environment variables.

**Acceptance Criteria:**
- [ ] Documentation (in this PRD) lists all required Railway configuration
- [ ] Persistent volume mounted at `/app/data`
- [ ] Railway Bucket provisioned for replay archival
- [ ] Required env vars documented: `PORT`, `API_KEY`, `DATA_DIR`, bucket credentials
- [ ] Gunicorn configured with 2 workers and 600s timeout

### US-006: Verify migration correctness
**Description:** As the server operator, I want to verify that migrated data matches the current batch pipeline output so that I can trust the new system.

**Acceptance Criteria:**
- [ ] After migration, `player_ratings.json` contains the same player ratings (mu, sigma) as the current file (within rounding tolerance)
- [ ] `analysis_data.json` contains the same number of games, same award winners, same player profiles
- [ ] `rating_history.json` contains the same number of history entries and same LAN events
- [ ] A verification section in this PRD describes the manual comparison steps

## Functional Requirements

- FR-1: Create `server/migrate.py` with a `main()` function that orchestrates the full migration:
  ```python
  def main():
      1. Parse all replays from recorded_games/ (reuse parse_replays_parallel)
      2. For each parsed match:
         a. Compute SHA256 of the original file
         b. Extract metadata (filename, datetime, duration, teams, winner, handicaps, eAPM)
         c. Extract per-game stat deltas via extract_single_game_deltas()
         d. Build registry entry dict
         e. Upload to bucket (if configured)
      3. Sort entries chronologically and save game_registry.json
      4. Run run_trueskill_from_registry() -> player_ratings.json + rating_history.json
      5. Run rebuild_analysis_from_registry() -> analysis_data.json
      6. Print summary
  ```
- FR-2: Migration must handle the same edge cases as the processing pipeline: skip games < 5 min (already filtered by `parse_replays_parallel`), skip unknown players, handle games with no winner.
- FR-3: Migration reuses the same functions from PRD 1 (`extract_single_game_deltas`, `run_trueskill_from_registry`, `rebuild_analysis_from_registry`) to ensure consistency.
- FR-4: New Dockerfile:
  ```dockerfile
  FROM python:3.12-slim

  WORKDIR /app

  # Install git for mgz fork
  RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

  # Install Python dependencies
  RUN pip install --no-cache-dir \
      flask \
      trueskill \
      gunicorn \
      boto3 \
      pandas \
      git+https://github.com/sanduckhan/aoc-mgz.git@feat/expose-handicap

  # Copy application code
  COPY analyzer_lib/ analyzer_lib/
  COPY scripts/ scripts/
  COPY web/ web/
  COPY server/ server/
  COPY run_web.py ./

  # Data directory (Railway persistent volume mount point)
  ENV DATA_DIR=/app/data

  # Gunicorn with extended timeout for rebuild endpoint
  CMD gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 600 web.app:app
  ```
- FR-5: Add `boto3` to `pyproject.toml` dependencies:
  ```toml
  boto3 = "^1.35"
  ```
- FR-6: Railway configuration:
  | Setting | Value |
  |---|---|
  | Persistent Volume | Mount at `/app/data` |
  | Railway Bucket | Provisioned from dashboard, S3-compatible |
  | `PORT` | Auto-set by Railway |
  | `API_KEY` | Secret, set in Railway dashboard |
  | `DATA_DIR` | `/app/data` |
  | `BUCKET_ENDPOINT` | Auto-injected by Railway when bucket is linked |
  | `BUCKET_ACCESS_KEY_ID` | Auto-injected by Railway |
  | `BUCKET_SECRET_ACCESS_KEY` | Auto-injected by Railway |
  | `BUCKET_NAME` | Auto-injected by Railway |

- FR-7: Migration script supports a `--skip-bucket` flag to skip bucket uploads (for local testing or when bucket is not configured).
- FR-8: Migration script supports a `--data-dir` flag to specify output directory (defaults to `config.DATA_DIR`).

## Non-Goals

- No automated CI/CD pipeline (Railway auto-deploys from git push, which is sufficient)
- No staging environment (one production deployment is fine for this scale)
- No database migration (there is no database — all data is in JSON files)
- No backup automation (Railway Bucket provides durability for replays; JSON files can be regenerated from bucket via rebuild)
- No monitoring or alerting setup (Railway provides basic logs)
- No changes to `main.py` or the local development workflow

## Technical Considerations

- **Migration duration**: Parsing ~280 replays takes ~2-3 minutes with parallel parsing. Bucket upload adds ~1 second per file (~5 minutes total). Full migration should complete in under 10 minutes.
- **SHA256 computation**: Must compute SHA256 from the original file bytes (not from the parsed match object). The migration script reads each file twice: once for SHA256, once for parsing. Alternatively, read once into memory and compute both.
- **Registry consistency with batch pipeline**: The registry-based pipeline extracts stats from `match.inputs` (action stream), same as the batch pipeline. However, minor floating-point differences in duration, or differences in how edge cases are handled, could cause small discrepancies. The verification step should allow for rounding tolerance.
- **First deployment bootstrapping**: On first Railway deployment, the persistent volume will be empty. The operator must either:
  1. Run migration locally, upload JSON files to the volume, or
  2. Run migration on the server via a one-time command (e.g., `railway run python -m server.migrate`)
  Option 2 requires the `recorded_games/` directory to be accessible, which won't be the case on Railway. So the practical approach is: run migration locally, then upload the registry + JSON files to the Railway volume. Bucket uploads can be done separately.
- **mgz fork in Docker**: The Dockerfile installs `mgz` from the git fork directly via pip. This avoids needing poetry in the Docker image.

## Success Metrics

- Migration script completes without errors on the existing ~280 replays
- `game_registry.json` contains the same number of processed games as the current analysis
- Player ratings (mu_scaled) match within 0.5 points of current values
- All 8 award categories produce the same winners as the current batch pipeline
- Docker image builds successfully and the web UI works on Railway
- Upload and rebuild endpoints function correctly on the deployed server

## Verification Steps

After running migration, compare outputs:

1. **Game count**: `jq '.total_processed' game_registry.json` should match the game count from current `analysis_data.json`
2. **Player ratings**: For each player, `mu_scaled` in new `player_ratings.json` should be within 0.5 of current values
3. **Award winners**: `jq '.awards.bitter_salt_baron.player' analysis_data.json` (and other awards) should match current values
4. **Rating history**: `jq '.history | length' rating_history.json` should match current file
5. **LAN events**: `jq '.lan_events | length' rating_history.json` should match current file

## Open Questions

- How should we handle the initial deployment bootstrapping? The simplest approach is to run migration locally and upload the resulting JSON files to Railway's persistent volume via `railway volume`. Should we document this as a step-by-step guide?
- Should the migration script also generate the TrueSkill evolution plot (`trueskill_evolution.png`)? This is currently done by `run_trueskill()` but is only useful locally. The server doesn't serve this plot.
- Should we keep the `recorded_games/` directory in `.gitignore` and not deploy it, or should we provide a way to seed the server from the git repo?
