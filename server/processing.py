"""Server processing pipeline for incremental replay processing.

Contains GameRegistry for managing the games table in SQLite and
IncrementalProcessor for end-to-end replay processing.
"""

import hashlib
import io
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta

# Add project root and scripts to path
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SERVER_DIR)
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))

from analyzer_lib import config, db
from analyzer_lib.registry_builder import (
    compute_game_fingerprint,
    replay_to_registry_entry,
)
from analyzer_lib.registry_stats import accumulate_stats_from_games
from analyzer_lib.report_generator import (
    compute_all_awards,
    compute_general_stats,
    compute_player_profiles,
)
from calculate_trueskill import run_trueskill_from_registry

logger = logging.getLogger(__name__)

# Columns stored as JSON blobs in the games table
_JSON_COLUMNS = ("teams", "player_deltas", "game_level_deltas")

# Column order for INSERT statements
_GAME_COLUMNS = (
    "sha256",
    "fingerprint",
    "status",
    "filename",
    "datetime",
    "duration_seconds",
    "winning_team_id",
    "source_path",
    "uploaded_at",
    "teams",
    "player_deltas",
    "game_level_deltas",
)
_GAME_PLACEHOLDERS = ", ".join("?" for _ in _GAME_COLUMNS)
_GAME_INSERT_SQL = f"INSERT OR IGNORE INTO games ({', '.join(_GAME_COLUMNS)}) VALUES ({_GAME_PLACEHOLDERS})"


def _entry_to_row(entry):
    """Convert a game entry dict to a tuple for INSERT."""
    return (
        entry["sha256"],
        entry.get("fingerprint", ""),
        entry["status"],
        entry.get("filename", ""),
        entry.get("datetime", ""),
        entry.get("duration_seconds", 0),
        entry.get("winning_team_id"),
        entry.get("source_path"),
        entry.get("uploaded_at", ""),
        json.dumps(entry.get("teams", {}), default=str),
        json.dumps(entry.get("player_deltas", {}), default=str),
        json.dumps(entry.get("game_level_deltas", {}), default=str),
    )


def _row_to_dict(row):
    """Convert a sqlite3.Row to a game entry dict with JSON columns parsed."""
    d = dict(row)
    for col in _JSON_COLUMNS:
        val = d.get(col)
        d[col] = json.loads(val) if val else {}
    return d


class GameRegistry:
    """Manages the games table in SQLite as the single source of truth.

    Thread-safe via SQLite WAL mode (concurrent readers, serialized writers).
    """

    def __init__(self, data_dir=None):
        self._data_dir = data_dir or config.DATA_DIR
        os.makedirs(self._data_dir, exist_ok=True)
        self._db_path = db.get_db_path(self._data_dir)
        self._conn = db.get_connection(self._db_path)
        db.init_schema(self._conn)
        count = self._conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        logger.info(f"Game registry opened with {count} games")

    def has_game(self, sha256):
        """Check if a game with this SHA256 already exists. O(1) via PRIMARY KEY."""
        row = self._conn.execute(
            "SELECT 1 FROM games WHERE sha256 = ? LIMIT 1", (sha256,)
        ).fetchone()
        return row is not None

    def get_fingerprint_status(self, fingerprint):
        """Return the status of an existing game by fingerprint, or None if not found."""
        if not fingerprint:
            return None
        row = self._conn.execute(
            "SELECT status FROM games WHERE fingerprint = ? LIMIT 1", (fingerprint,)
        ).fetchone()
        return row[0] if row else None

    def has_fingerprint(self, fingerprint):
        """Check if a game with this fingerprint already exists. O(1) via index."""
        if not fingerprint:
            return False
        row = self._conn.execute(
            "SELECT 1 FROM games WHERE fingerprint = ? LIMIT 1", (fingerprint,)
        ).fetchone()
        return row is not None

    def get_sha256_by_fingerprint(self, fingerprint):
        """Return the SHA256 of an existing game by fingerprint, or None."""
        if not fingerprint:
            return None
        row = self._conn.execute(
            "SELECT sha256 FROM games WHERE fingerprint = ? LIMIT 1", (fingerprint,)
        ).fetchone()
        return row[0] if row else None

    def delete_game(self, sha256):
        """Delete a game entry by SHA256."""
        self._conn.execute("DELETE FROM games WHERE sha256 = ?", (sha256,))
        self._conn.commit()

    def add_game(self, entry):
        """Insert a game entry into the database."""
        self._conn.execute(_GAME_INSERT_SQL, _entry_to_row(entry))
        self._conn.commit()
        if entry.get("status") == "processed":
            self._update_metadata("total_processed", self._get_processed_count())

    def set_winner(self, sha256, winning_team_id):
        """Override winner for a no_winner game, promoting it to processed."""
        row = self._conn.execute(
            "SELECT teams FROM games WHERE sha256 = ?", (sha256,)
        ).fetchone()
        if not row:
            return False
        teams = json.loads(row[0])
        for tid, players in teams.items():
            for p in players:
                p["winner"] = tid == str(winning_team_id)
        self._conn.execute(
            "UPDATE games SET status = 'processed', winning_team_id = ?, teams = ? "
            "WHERE sha256 = ?",
            (str(winning_team_id), json.dumps(teams), sha256),
        )
        self._conn.commit()
        self._update_metadata("total_processed", self._get_processed_count())
        return True

    def update_source_path(self, sha256, source_path):
        """Set source_path on an existing entry (backfill for download support)."""
        cursor = self._conn.execute(
            "UPDATE games SET source_path = ? WHERE sha256 = ? AND (source_path IS NULL OR source_path = '')",
            (source_path, sha256),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def flush(self):
        """No-op — SQLite auto-commits per write."""
        pass

    def get_games(self, status=None):
        """Return games, optionally filtered by status, ordered by datetime.

        Args:
            status: None (all), a single status string, or a list of statuses.
        """
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM games ORDER BY datetime"
            ).fetchall()
        elif isinstance(status, list):
            placeholders = ", ".join("?" for _ in status)
            rows = self._conn.execute(
                f"SELECT * FROM games WHERE status IN ({placeholders}) ORDER BY datetime",
                status,
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM games WHERE status = ? ORDER BY datetime", (status,)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_all_data(self):
        """Return full registry data in legacy dict format for backward compat."""
        games = self.get_games()
        total_processed = self._get_processed_count()
        last_updated = self._get_metadata("last_updated") or ""
        return {
            "games": games,
            "total_processed": total_processed,
            "last_updated": last_updated,
        }

    def replace_all(self, games):
        """Replace the entire registry (used during full rebuild)."""
        with self._conn:
            self._conn.execute("DELETE FROM games")
            self._conn.executemany(_GAME_INSERT_SQL, [_entry_to_row(g) for g in games])
        processed_count = sum(1 for g in games if g.get("status") == "processed")
        self._update_metadata("total_processed", processed_count)
        self._update_metadata("last_updated", datetime.utcnow().isoformat())

    def get_game_by_sha256(self, sha256):
        """O(1) lookup of a single game by SHA256."""
        row = self._conn.execute(
            "SELECT * FROM games WHERE sha256 = ?", (sha256,)
        ).fetchone()
        return _row_to_dict(row) if row else None

    def get_games_in_date_range(self, status_list, date_from, date_to):
        """Return games matching status and date range, ordered by datetime."""
        placeholders = ", ".join("?" for _ in status_list)
        rows = self._conn.execute(
            f"""SELECT * FROM games
                WHERE status IN ({placeholders})
                AND substr(datetime, 1, 10) >= ?
                AND substr(datetime, 1, 10) <= ?
                ORDER BY datetime""",
            (*status_list, date_from, date_to),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    @property
    def path(self):
        return self._db_path

    @property
    def db_path(self):
        return self._db_path

    def _get_processed_count(self):
        row = self._conn.execute(
            "SELECT COUNT(*) FROM games WHERE status = 'processed'"
        ).fetchone()
        return row[0]

    def _get_metadata(self, key):
        row = self._conn.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def _update_metadata(self, key, value):
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
        self._conn.commit()


class IncrementalProcessor:
    """Orchestrates end-to-end processing of uploaded replay files.

    Handles: parse, validate, extract deltas, store in bucket, register
    in registry, rebuild TrueSkill, and update analysis data.

    Processing is serialized via a lock (no concurrent processing).
    Rebuilds are debounced: after each upload, a 60-second timer starts.
    If another upload arrives before the timer fires, it resets.
    The rebuild only runs once uploads stop for 60 seconds.
    Concurrent rebuilds are prevented: if a rebuild is already running
    when the timer fires, it's skipped but re-scheduled.
    """

    REBUILD_DELAY = 60  # seconds of quiet before triggering rebuild

    def __init__(self, registry: GameRegistry, storage_module=None):
        self._registry = registry
        self._storage = storage_module
        self._lock = threading.Lock()
        self._data_dir = registry._data_dir
        self._rebuild_timer = None
        self._rebuild_timer_lock = threading.Lock()
        self._pending_rebuild = False
        self._rebuilding = False

    def process_new_replay(self, file_bytes: bytes, sha256: str, uploader_info=None):
        """Process a new replay file end-to-end.

        Returns a dict with: status, sha256, filename, datetime, teams, message.
        """
        # Quick dedup check (no lock needed — registry has its own lock)
        if self._registry.has_game(sha256):
            self._schedule_rebuild()
            return {
                "status": "duplicate",
                "sha256": sha256,
                "message": "This replay has already been processed.",
            }

        with self._lock:
            # Double-check after acquiring lock
            if self._registry.has_game(sha256):
                self._schedule_rebuild()
                return {
                    "status": "duplicate",
                    "sha256": sha256,
                    "message": "This replay has already been processed.",
                }

            return self._process_locked(file_bytes, sha256, uploader_info)

    def _process_locked(self, file_bytes, sha256, uploader_info):
        """Internal processing under lock.

        Uses replay_to_registry_entry() for parsing, then handles
        dedup, bucket upload, and rebuild triggers.
        """
        entry = replay_to_registry_entry(file_bytes, sha256)

        # For non-success statuses, register and return early
        if entry["status"] in ("parse_error", "too_short", "unknown_player"):
            logger.warning(
                f"Upload not counted [{entry['status']}]: "
                f"{entry.get('filename', sha256[:12])} "
                f"(sha256={sha256[:12]})"
            )
            self._registry.add_game(entry)
            self._schedule_rebuild()
            return {
                "status": entry["status"],
                "sha256": sha256,
                "filename": entry.get("filename", ""),
                "datetime": entry.get("datetime", ""),
                "message": f"Replay status: {entry['status']}",
            }

        # --- Fingerprint dedup (same game recorded by different players) ---
        # A 'processed' entry always wins over a 'no_winner' entry (handles the case
        # where a paused game was uploaded earlier as no_winner, then the completed
        # game is uploaded — the completed version should succeed).
        # A 'no_winner' entry is still blocked by an existing no_winner (normal dedup).
        fingerprint = entry.get("fingerprint")
        if fingerprint:
            existing_fp_status = self._registry.get_fingerprint_status(fingerprint)
            is_duplicate = existing_fp_status is not None and not (
                entry["status"] == "processed" and existing_fp_status == "no_winner"
            )
            if is_duplicate:
                logger.info(
                    f"Upload not counted [duplicate]: "
                    f"{entry.get('filename', sha256[:12])} — "
                    f"already uploaded by another player "
                    f"(sha256={sha256[:12]})"
                )
                self._schedule_rebuild()
                return {
                    "status": "duplicate",
                    "sha256": sha256,
                    "filename": entry["filename"],
                    "datetime": entry["datetime"],
                    "message": "This game was already uploaded by another player.",
                }

        # If a processed entry supersedes an existing no_winner, delete the old one
        # so the DB doesn't accumulate duplicate fingerprints.
        if fingerprint and existing_fp_status == "no_winner" and entry["status"] == "processed":
            old_sha256 = self._registry.get_sha256_by_fingerprint(fingerprint)
            if old_sha256:
                logger.info(f"Superseding no_winner {old_sha256} with processed {sha256}")
                self._registry.delete_game(old_sha256)

        # --- Store in bucket (non-critical) ---
        if self._storage:
            try:
                self._storage.upload_replay(file_bytes, sha256)
            except Exception as e:
                logger.warning(f"Bucket upload failed for {sha256} (non-critical): {e}")

        # --- Register in registry ---
        self._registry.add_game(entry)

        if entry["status"] == "no_winner":
            teams_dict = entry.get("teams", {})
            player_names = [
                p["name"] for players in teams_dict.values() for p in players
            ]
            logger.warning(
                f"Upload not counted [no_winner]: "
                f"{entry.get('filename', sha256[:12])} — "
                f"players: {', '.join(player_names)} "
                f"(sha256={sha256[:12]})"
            )

        # --- Schedule deferred rebuild ---
        self._schedule_rebuild()

        # --- Build response ---
        teams_dict = entry.get("teams", {})
        teams_summary = {}
        for tid, players in teams_dict.items():
            teams_summary[tid] = [p["name"] for p in players]

        return {
            "status": entry["status"],
            "sha256": sha256,
            "filename": entry["filename"],
            "datetime": entry["datetime"],
            "teams": teams_summary,
            "message": f"Replay processed successfully (status: {entry['status']}). Stats rebuild scheduled.",
            "rebuild_pending": True,
        }

    def _schedule_rebuild(self):
        """Schedule a rebuild after REBUILD_DELAY seconds of inactivity.

        Each call resets the timer. The rebuild only fires once uploads
        stop arriving for the full delay period.
        """
        with self._rebuild_timer_lock:
            if self._rebuild_timer is not None:
                self._rebuild_timer.cancel()
            self._pending_rebuild = True
            self._rebuild_timer = threading.Timer(self.REBUILD_DELAY, self._run_rebuild)
            self._rebuild_timer.daemon = True
            self._rebuild_timer.start()
            logger.info(
                f"Rebuild scheduled in {self.REBUILD_DELAY}s "
                f"(resets on next upload)"
            )

    def _run_rebuild(self):
        """Execute the deferred rebuild (called by the timer thread).

        If a rebuild is already running, skip this one but re-schedule
        so the new data is eventually picked up.
        """
        with self._rebuild_timer_lock:
            self._rebuild_timer = None
            if self._rebuilding:
                logger.info("Rebuild already in progress, re-scheduling")
                self._pending_rebuild = True
                self._rebuild_timer = threading.Timer(
                    self.REBUILD_DELAY, self._run_rebuild
                )
                self._rebuild_timer.daemon = True
                self._rebuild_timer.start()
                return
            self._rebuilding = True
            self._pending_rebuild = False

        logger.info("Deferred rebuild starting...")
        start = time.time()

        try:
            rating_deltas = {}
            try:
                ratable_games = self._registry.get_games(status="processed")
                _, _, _, rating_deltas = run_trueskill_from_registry(
                    ratable_games, data_dir=self._data_dir
                )
            except Exception as e:
                logger.error(f"TrueSkill rebuild failed: {e}")

            try:
                rebuild_analysis_from_registry(
                    self._registry,
                    data_dir=self._data_dir,
                    rating_deltas=rating_deltas,
                )
            except Exception as e:
                logger.error(f"Analysis rebuild failed: {e}")

            logger.info(f"Deferred rebuild complete in {time.time() - start:.1f}s")
        finally:
            with self._rebuild_timer_lock:
                self._rebuilding = False

    @property
    def rebuild_pending(self):
        """True if a rebuild is scheduled but hasn't fired yet."""
        with self._rebuild_timer_lock:
            return self._pending_rebuild

    def full_rebuild(self):
        """Kick off a full rebuild in a background thread.

        Returns immediately with status info. Use full_rebuild_status
        to poll progress.
        """
        if not self._storage:
            return {"error": "No storage module configured."}

        with self._rebuild_timer_lock:
            if self._rebuilding:
                return {
                    "status": "already_running",
                    "progress": self._full_rebuild_progress.copy(),
                    "message": "A rebuild is already in progress.",
                }

        self._full_rebuild_progress = {
            "phase": "starting",
            "current": 0,
            "total": 0,
            "counts": {},
        }

        thread = threading.Thread(target=self._full_rebuild_worker, daemon=True)
        thread.start()

        return {
            "status": "started",
            "message": "Full rebuild started in background. Poll /api/rebuild/status for progress.",
        }

    @property
    def full_rebuild_status(self):
        """Return current full rebuild progress."""
        progress = getattr(self, "_full_rebuild_progress", None)
        if progress is None:
            return {"status": "idle", "message": "No rebuild running or completed."}
        with self._rebuild_timer_lock:
            running = self._rebuilding
        return {
            "status": "running" if running else "complete",
            "progress": progress.copy(),
        }

    def _full_rebuild_worker(self):
        """Background worker for full rebuild."""
        with self._rebuild_timer_lock:
            if self._rebuilding:
                logger.warning("Full rebuild skipped — another rebuild is running")
                return
            self._rebuilding = True

        # Cancel any pending deferred rebuild
        with self._rebuild_timer_lock:
            if self._rebuild_timer is not None:
                self._rebuild_timer.cancel()
                self._rebuild_timer = None
            self._pending_rebuild = False

        try:
            self._full_rebuild_inner()
        finally:
            with self._rebuild_timer_lock:
                self._rebuilding = False

    def _full_rebuild_inner(self):
        """Core full rebuild logic (runs in background thread)."""
        start_time = time.time()

        replay_list = self._storage.list_replays()
        total = len(replay_list)
        logger.info(f"Full rebuild: found {total} replays in bucket")

        self._full_rebuild_progress.update({
            "phase": "downloading_and_parsing",
            "total": total,
        })

        new_games = []
        seen_fingerprints = {}  # fp -> index in new_games
        counts = defaultdict(int)

        for i, replay_info in enumerate(replay_list, 1):
            sha = replay_info["sha256"]
            logger.info(f"Processing replay {i}/{total}: {sha}")
            self._full_rebuild_progress["current"] = i

            try:
                file_bytes = self._storage.download_replay(sha)
            except Exception as e:
                logger.error(f"Download failed for {sha}: {e}")
                counts["download_error"] += 1
                self._full_rebuild_progress["counts"] = dict(counts)
                continue

            entry = replay_to_registry_entry(file_bytes, sha)

            # Fingerprint dedup: same game recorded by different players.
            # A 'processed' entry always wins over a 'no_winner' entry
            # (e.g., partial recording from a player who disconnected early).
            fp = entry.get("fingerprint")
            if fp and fp in seen_fingerprints:
                existing_idx = seen_fingerprints[fp]
                existing_entry = new_games[existing_idx]
                if entry["status"] == "processed" and existing_entry["status"] == "no_winner":
                    logger.info(f"Replacing no_winner {existing_entry['sha256'][:12]} with processed {sha[:12]}")
                    new_games[existing_idx] = entry
                    seen_fingerprints[fp] = existing_idx
                    counts["fingerprint_duplicate"] += 1
                else:
                    logger.info(f"Skipping fingerprint duplicate: {sha}")
                    counts["fingerprint_duplicate"] += 1
                self._full_rebuild_progress["counts"] = dict(counts)
                continue
            if fp:
                seen_fingerprints[fp] = len(new_games)

            new_games.append(entry)
            counts[entry["status"]] += 1
            self._full_rebuild_progress["counts"] = dict(counts)

        # Replace entire registry
        self._full_rebuild_progress["phase"] = "replacing_registry"
        logger.info(f"Deduped: {len(new_games)} unique games from {total} replays")
        self._registry.replace_all(new_games)

        # Rebuild TrueSkill
        self._full_rebuild_progress["phase"] = "rebuilding_trueskill"
        rating_deltas = {}
        try:
            ratable_games = [
                g for g in new_games
                if g["status"] in ("processed", "no_winner")
            ]
            _, _, _, rating_deltas = run_trueskill_from_registry(
                ratable_games, data_dir=self._data_dir
            )
        except Exception as e:
            logger.error(f"TrueSkill rebuild during full rebuild failed: {e}")

        # Rebuild analysis
        self._full_rebuild_progress["phase"] = "rebuilding_analysis"
        try:
            rebuild_analysis_from_registry(
                self._registry,
                data_dir=self._data_dir,
                rating_deltas=rating_deltas,
            )
        except Exception as e:
            logger.error(f"Analysis rebuild during full rebuild failed: {e}")

        duration = time.time() - start_time
        self._full_rebuild_progress.update({
            "phase": "done",
            "duration_seconds": round(duration, 1),
        })
        logger.info(f"Full rebuild complete in {duration:.1f}s: {counts}")


def rebuild_analysis_from_registry(registry, data_dir=None, rating_deltas=None):
    """Rebuild analysis data from the game registry and save to SQLite.

    Delegates to accumulate_stats_from_games() for the actual stat
    accumulation, then writes the output to the analysis_cache table.

    Args:
        registry: GameRegistry instance.
        data_dir: Output directory. Defaults to config.DATA_DIR.
        rating_deltas: Optional dict mapping sha256 -> {player_name -> delta}.
            When provided, each game_result entry gets a "rating_changes" field.
    """
    output_dir = data_dir or config.DATA_DIR
    all_games = registry.get_all_data()["games"]

    analysis_games = [
        g for g in all_games if g.get("status") in ("processed", "no_winner")
    ]

    # Fingerprint dedup: if the same game exists as both no_winner and processed
    # (e.g. uploaded by two players), keep only the processed version.
    fp_best = {}
    no_fp_games = []
    for g in analysis_games:
        fp = g.get("fingerprint")
        if not fp:
            no_fp_games.append(g)
            continue
        existing = fp_best.get(fp)
        if existing is None or (
            g["status"] == "processed" and existing["status"] == "no_winner"
        ):
            fp_best[fp] = g
    analysis_games = sorted(
        list(fp_best.values()) + no_fp_games,
        key=lambda g: g.get("datetime", ""),
    )

    player_stats, game_stats, game_results, head_to_head = accumulate_stats_from_games(
        analysis_games
    )

    if rating_deltas:
        for gr in game_results:
            sha = gr.get("sha256")
            if sha and sha in rating_deltas:
                gr["rating_changes"] = rating_deltas[sha]

    analysis_data = {
        "awards": compute_all_awards(player_stats, game_stats),
        "general_stats": compute_general_stats(game_stats),
        "game_results": game_results,
        "player_profiles": compute_player_profiles(player_stats, head_to_head),
    }

    db_path = db.get_db_path(output_dir)
    db.save_analysis_data(db_path, analysis_data)
    logger.info(f"Analysis data saved to database: {db_path}")
