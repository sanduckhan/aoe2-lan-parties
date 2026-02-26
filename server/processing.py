"""Server processing pipeline for incremental replay processing.

Contains GameRegistry for managing game_registry.json and
IncrementalProcessor for end-to-end replay processing.
"""

import hashlib
import io
import json
import logging
import os
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

from analyzer_lib import config
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


class GameRegistry:
    """Manages game_registry.json as the single source of truth for all known games.

    Thread-safe via threading.Lock. Uses an in-memory SHA256 set for O(1) dedup.
    File writes are atomic (write to .tmp, then os.rename).
    """

    def __init__(self, data_dir=None):
        self._lock = threading.Lock()
        self._data_dir = data_dir or config.DATA_DIR
        os.makedirs(self._data_dir, exist_ok=True)
        self._path = os.path.join(self._data_dir, "game_registry.json")
        self._data = {"games": [], "total_processed": 0, "last_updated": ""}
        self._sha256_set = set()
        self._fingerprint_set = set()
        self._dirty = False
        self._load()

    def _load(self):
        """Load registry from disk into memory."""
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    self._data = json.load(f)
                self._sha256_set = {g["sha256"] for g in self._data.get("games", [])}
                self._fingerprint_set = {
                    g["fingerprint"]
                    for g in self._data.get("games", [])
                    if g.get("fingerprint")
                }
                logger.info(
                    f"Loaded game registry with {len(self._data['games'])} games"
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to load game registry: {e}. Starting fresh.")
                self._data = {"games": [], "total_processed": 0, "last_updated": ""}
                self._sha256_set = set()
                self._fingerprint_set = set()

    def _save(self):
        """Atomically write registry to disk."""
        self._data["last_updated"] = datetime.utcnow().isoformat()
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(self._data, f, indent=2, default=str)
        os.rename(tmp_path, self._path)

    def has_game(self, sha256: str) -> bool:
        """Check if a game with this SHA256 already exists. O(1)."""
        with self._lock:
            return sha256 in self._sha256_set

    def has_fingerprint(self, fingerprint: str) -> bool:
        """Check if a game with this fingerprint already exists. O(1)."""
        with self._lock:
            return fingerprint in self._fingerprint_set

    def add_game(self, entry: dict) -> None:
        """Append a game entry to the registry and update SHA256 + fingerprint indexes."""
        with self._lock:
            self._data["games"].append(entry)
            self._sha256_set.add(entry["sha256"])
            if entry.get("fingerprint"):
                self._fingerprint_set.add(entry["fingerprint"])
            if entry.get("status") == "processed":
                self._data["total_processed"] += 1
            self._save()

    def update_source_path(self, sha256: str, source_path: str) -> bool:
        """Set source_path on an existing entry (backfill for download support)."""
        with self._lock:
            for g in self._data["games"]:
                if g.get("sha256") == sha256:
                    if not g.get("source_path"):
                        g["source_path"] = source_path
                        self._dirty = True
                        return True
                    return False
            return False

    def flush(self) -> None:
        """Write to disk if there are pending changes."""
        with self._lock:
            if self._dirty:
                self._save()
                self._dirty = False

    def get_games(self, status=None) -> list:
        """Return games, optionally filtered by status."""
        with self._lock:
            if status is None:
                return list(self._data["games"])
            return [g for g in self._data["games"] if g.get("status") == status]

    def get_all_data(self) -> dict:
        """Return a copy of the full registry data."""
        with self._lock:
            return json.loads(json.dumps(self._data, default=str))

    def replace_all(self, games: list) -> None:
        """Replace the entire registry (used during full rebuild)."""
        with self._lock:
            processed_count = sum(
                1 for g in games if g.get("status") == "processed"
            )
            self._data = {
                "games": games,
                "total_processed": processed_count,
                "last_updated": datetime.utcnow().isoformat(),
            }
            self._sha256_set = {g["sha256"] for g in games}
            self._fingerprint_set = {
                g["fingerprint"] for g in games if g.get("fingerprint")
            }
            self._save()

    @property
    def path(self):
        return self._path


class IncrementalProcessor:
    """Orchestrates end-to-end processing of uploaded replay files.

    Handles: parse, validate, extract deltas, store in bucket, register
    in registry, rebuild TrueSkill, and update analysis data.

    Processing is serialized via a lock (no concurrent processing).
    Rebuilds are debounced: after each upload, a 30-second timer starts.
    If another upload arrives before the timer fires, it resets.
    The rebuild only runs once uploads stop for 30 seconds.
    """

    REBUILD_DELAY = 30  # seconds of quiet before triggering rebuild

    def __init__(self, registry: GameRegistry, storage_module=None):
        self._registry = registry
        self._storage = storage_module
        self._lock = threading.Lock()
        self._data_dir = registry._data_dir
        self._rebuild_timer = None
        self._rebuild_timer_lock = threading.Lock()
        self._pending_rebuild = False

    def process_new_replay(self, file_bytes: bytes, sha256: str, uploader_info=None):
        """Process a new replay file end-to-end.

        Returns a dict with: status, sha256, filename, datetime, teams, message.
        """
        # Quick dedup check (no lock needed — registry has its own lock)
        if self._registry.has_game(sha256):
            return {
                "status": "duplicate",
                "sha256": sha256,
                "message": "This replay has already been processed.",
            }

        with self._lock:
            # Double-check after acquiring lock
            if self._registry.has_game(sha256):
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
            # For parse errors with specific messages, store them
            self._registry.add_game(entry)
            return {
                "status": entry["status"],
                "sha256": sha256,
                "filename": entry.get("filename", ""),
                "datetime": entry.get("datetime", ""),
                "message": f"Replay status: {entry['status']}",
            }

        # --- Fingerprint dedup (same game recorded by different players) ---
        fingerprint = entry.get("fingerprint")
        if fingerprint and self._registry.has_fingerprint(fingerprint):
            return {
                "status": "duplicate",
                "sha256": sha256,
                "filename": entry["filename"],
                "datetime": entry["datetime"],
                "message": "This game was already uploaded by another player.",
            }

        # --- Store in bucket (non-critical) ---
        if self._storage:
            try:
                self._storage.upload_replay(file_bytes, sha256)
            except Exception as e:
                logger.warning(f"Bucket upload failed for {sha256} (non-critical): {e}")

        # --- Register in registry ---
        self._registry.add_game(entry)

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
            self._rebuild_timer = threading.Timer(
                self.REBUILD_DELAY, self._run_rebuild
            )
            self._rebuild_timer.daemon = True
            self._rebuild_timer.start()
            logger.info(
                f"Rebuild scheduled in {self.REBUILD_DELAY}s "
                f"(resets on next upload)"
            )

    def _run_rebuild(self):
        """Execute the deferred rebuild (called by the timer thread)."""
        with self._rebuild_timer_lock:
            self._rebuild_timer = None
            self._pending_rebuild = False

        logger.info("Deferred rebuild starting...")
        start = time.time()

        rating_deltas = {}
        try:
            processed_games = self._registry.get_games(status="processed")
            _, _, _, rating_deltas = run_trueskill_from_registry(
                processed_games, data_dir=self._data_dir
            )
        except Exception as e:
            logger.error(f"TrueSkill rebuild failed: {e}")

        try:
            rebuild_analysis_from_registry(
                self._registry, data_dir=self._data_dir,
                rating_deltas=rating_deltas,
            )
        except Exception as e:
            logger.error(f"Analysis rebuild failed: {e}")

        logger.info(f"Deferred rebuild complete in {time.time() - start:.1f}s")

    @property
    def rebuild_pending(self):
        """True if a rebuild is scheduled but hasn't fired yet."""
        with self._rebuild_timer_lock:
            return self._pending_rebuild

    def full_rebuild(self):
        """Rebuild all data from scratch by re-downloading replays from bucket.

        Downloads all replays from bucket, parses each, rebuilds registry,
        then runs TrueSkill and analysis rebuilds.

        Returns a summary dict.
        """
        if not self._storage:
            return {"error": "No storage module configured."}

        with self._lock:
            start_time = time.time()
            replay_list = self._storage.list_replays()
            total = len(replay_list)
            logger.info(f"Full rebuild: found {total} replays in bucket")

            new_games = []
            counts = defaultdict(int)

            for i, replay_info in enumerate(replay_list, 1):
                sha = replay_info["sha256"]
                logger.info(f"Processing replay {i}/{total}: {sha}")

                try:
                    file_bytes = self._storage.download_replay(sha)
                except Exception as e:
                    logger.error(f"Download failed for {sha}: {e}")
                    counts["download_error"] += 1
                    continue

                entry = replay_to_registry_entry(file_bytes, sha)
                new_games.append(entry)
                counts[entry["status"]] += 1

            # Replace entire registry
            self._registry.replace_all(new_games)

            # Rebuild TrueSkill
            rating_deltas = {}
            try:
                processed_games = [
                    g for g in new_games if g["status"] == "processed"
                ]
                _, _, _, rating_deltas = run_trueskill_from_registry(
                    processed_games, data_dir=self._data_dir
                )
            except Exception as e:
                logger.error(f"TrueSkill rebuild during full rebuild failed: {e}")

            # Rebuild analysis
            try:
                rebuild_analysis_from_registry(
                    self._registry, data_dir=self._data_dir,
                    rating_deltas=rating_deltas,
                )
            except Exception as e:
                logger.error(f"Analysis rebuild during full rebuild failed: {e}")

            duration = time.time() - start_time
            summary = {
                "total_replays": total,
                "counts": dict(counts),
                "duration_seconds": round(duration, 1),
            }
            logger.info(f"Full rebuild complete: {summary}")
            return summary


def rebuild_analysis_from_registry(registry, data_dir=None, rating_deltas=None):
    """Rebuild analysis_data.json from the game registry.

    Delegates to accumulate_stats_from_games() for the actual stat
    accumulation, then writes the output file.

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
    analysis_games.sort(key=lambda g: g.get("datetime", ""))

    player_stats, game_stats, game_results, head_to_head = (
        accumulate_stats_from_games(analysis_games)
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

    output_path = os.path.join(output_dir, "analysis_data.json")
    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(analysis_data, f, indent=2, default=str)
    os.rename(tmp_path, output_path)
    logger.info(f"Analysis data saved to: {output_path}")
