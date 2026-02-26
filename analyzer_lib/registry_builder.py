"""Shared utilities for building and syncing the game registry.

Provides the single source of truth for converting a replay file into a
game_registry entry dict, and for incrementally syncing local replay files
into an existing registry.
"""

import hashlib
import io
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

from . import config
from .analyze_games import extract_single_game_deltas
from .replay_parser import get_datetime_from_filename

logger = logging.getLogger(__name__)

REPLAY_EXTENSIONS = (".aoe2record", ".mgz", ".mgx")
MIN_GAME_DURATION_SECONDS = 300


def compute_game_fingerprint(game_datetime: str, teams: dict) -> str:
    """Compute a fingerprint that uniquely identifies a game regardless of recorder.

    Two replay files of the same game (recorded by different players) will have
    different SHA256s but the same fingerprint, because the game datetime, player
    names, civs, and team assignments are identical.

    Args:
        game_datetime: ISO-format datetime string of the game.
        teams: Teams dict as stored in registry, e.g.
            {"1": [{"name": "Alice", "civ": "Britons", ...}, ...], "2": [...]}

    Returns:
        Hex SHA256 of the canonical representation.
    """
    players_canonical = []
    for tid in sorted(teams.keys()):
        for p in sorted(teams[tid], key=lambda x: x["name"]):
            players_canonical.append(f"{tid}:{p['name']}:{p.get('civ', '')}")
    raw = f"{game_datetime}|{'|'.join(players_canonical)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def replay_to_registry_entry(file_bytes, sha256, filename_hint="", source_path=None):
    """Parse a replay from bytes and produce a game_registry entry dict.

    This is the single source of truth for converting a replay file into
    the registry JSON format. Used by:
      - main.py (local file scanning via sync_registry_from_disk)
      - server/processing.py (web upload)
      - server/migrate.py (bulk migration)

    Args:
        file_bytes: Raw bytes of the replay file.
        sha256: Pre-computed SHA256 hex digest of file_bytes.
        filename_hint: Optional filename for datetime extraction.
        source_path: Optional relative path to the replay file on disk
            (for serving downloads). None for server-uploaded replays.

    Returns:
        A registry entry dict with all fields populated.
    """
    from mgz.model import parse_match

    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "sha256": sha256,
        "filename": filename_hint,
        "datetime": "",
        "uploaded_at": now,
        "status": "parse_error",
        "duration_seconds": 0,
        "teams": {},
        "winning_team_id": None,
        "fingerprint": "",
        "player_deltas": {},
        "game_level_deltas": {},
        "source_path": source_path,
    }

    # --- Parse ---
    try:
        match_obj = parse_match(io.BytesIO(file_bytes))
    except Exception as e:
        logger.warning(f"Parse error for {sha256[:12]}: {e}")
        return entry

    if not match_obj:
        return entry

    # --- Extract metadata ---
    try:
        match_filename = getattr(match_obj, "filename", "") or filename_hint
        entry["filename"] = match_filename
        duration_seconds = match_obj.duration.total_seconds()
        entry["duration_seconds"] = duration_seconds

        if match_filename:
            try:
                dt = get_datetime_from_filename(match_filename)
                entry["datetime"] = dt.isoformat()
            except Exception:
                pass
        if not entry["datetime"] and hasattr(match_obj, "timestamp"):
            entry["datetime"] = str(match_obj.timestamp)
    except Exception as e:
        logger.warning(f"Metadata error for {sha256[:12]}: {e}")
        return entry

    # --- Duration check ---
    if duration_seconds < MIN_GAME_DURATION_SECONDS:
        entry["status"] = "too_short"
        return entry

    # --- Filter human players ---
    human_players = [
        p
        for p in match_obj.players
        if hasattr(p, "profile_id") and p.profile_id is not None
    ]

    # --- Check for unknown players ---
    canonical_names = set(config.PLAYER_ALIASES.values())
    for p in human_players:
        aliased = config.PLAYER_ALIASES.get(p.name, p.name)
        if aliased not in canonical_names:
            entry["status"] = "unknown_player"
            return entry

    # --- Apply aliases ---
    for p in human_players:
        p.name = config.PLAYER_ALIASES.get(p.name, p.name)

    # --- Build teams ---
    teams_data = defaultdict(list)
    for p in human_players:
        team_id = p.team_id
        if isinstance(team_id, list):
            team_id = team_id[0] if team_id else -1
        teams_data[team_id].append(p)

    # --- Determine winner ---
    winning_team_id = None
    for team_id, players_in_team in teams_data.items():
        if any(p.winner for p in players_in_team):
            winning_team_id = team_id
            break

    # --- Build teams dict for registry ---
    teams_dict = {}
    for tid, players in teams_data.items():
        teams_dict[str(tid)] = [
            {
                "name": p.name,
                "civ": getattr(p, "civilization", "Unknown"),
                "winner": bool(p.winner),
                "handicap": getattr(p, "handicap", 100),
                "eapm": getattr(p, "eapm", None),
            }
            for p in players
        ]

    entry["teams"] = teams_dict
    entry["winning_team_id"] = (
        str(winning_team_id) if winning_team_id is not None else None
    )

    # --- Fingerprint ---
    if entry["datetime"] and teams_dict:
        entry["fingerprint"] = compute_game_fingerprint(
            entry["datetime"], teams_dict
        )

    # --- Extract action-based deltas ---
    try:
        player_deltas, game_deltas = extract_single_game_deltas(
            match_obj, human_players
        )
        entry["player_deltas"] = player_deltas
        entry["game_level_deltas"] = game_deltas
    except Exception as e:
        logger.warning(f"Delta extraction failed for {sha256[:12]}: {e}")

    # --- Final status ---
    entry["status"] = "no_winner" if winning_team_id is None else "processed"

    return entry


def sync_registry_from_disk(registry, replay_dir=None):
    """Scan local replay files and add any new ones to the registry.

    Only files whose SHA256 is not already in the registry are parsed.
    Files with duplicate fingerprints (same game, different recorder) are
    also skipped.

    Args:
        registry: A GameRegistry instance (from server.processing).
        replay_dir: Directory to scan. Defaults to config.RECORDED_GAMES_DIR.

    Returns:
        dict with counts: {"new": N, "skipped_existing": N, ...}
    """
    if replay_dir is None:
        replay_dir = config.RECORDED_GAMES_DIR

    if not os.path.isdir(replay_dir):
        logger.error(f"Replay directory not found: {replay_dir}")
        return {"error": f"Directory not found: {replay_dir}"}

    # Find all replay files
    file_paths = []
    for root, _, files in os.walk(replay_dir):
        for fn in files:
            if any(fn.lower().endswith(ext) for ext in REPLAY_EXTENSIONS):
                file_paths.append(os.path.join(root, fn))

    if not file_paths:
        logger.info("No replay files found.")
        return {"total_files": 0, "new": 0, "skipped_existing": 0}

    logger.info(f"Found {len(file_paths)} replay files, checking for new ones...")

    # Pre-filter: hash files and skip those already in registry
    files_to_parse = []
    skipped_existing = 0

    for fp in file_paths:
        with open(fp, "rb") as f:
            file_bytes = f.read()
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        if registry.has_game(sha256):
            skipped_existing += 1
            # Backfill source_path for entries that predate download support
            registry.update_source_path(sha256, os.path.relpath(fp))
        else:
            files_to_parse.append((fp, sha256, file_bytes))

    logger.info(
        f"Skipped {skipped_existing} already-registered files, "
        f"parsing {len(files_to_parse)} new files..."
    )

    counts = {
        "total_files": len(file_paths),
        "new": 0,
        "skipped_existing": skipped_existing,
        "skipped_duplicate": 0,
    }
    status_counts = defaultdict(int)

    for fp, sha256, file_bytes in files_to_parse:
        filename = os.path.basename(fp)
        # Store relative path from project root for download support
        source_path = os.path.relpath(fp)
        entry = replay_to_registry_entry(
            file_bytes, sha256, filename_hint=filename, source_path=source_path
        )

        # Fingerprint dedup (same game recorded by different players)
        fp_hash = entry.get("fingerprint")
        if fp_hash and registry.has_fingerprint(fp_hash):
            counts["skipped_duplicate"] += 1
            continue

        registry.add_game(entry)
        counts["new"] += 1
        status_counts[entry["status"]] += 1

    counts["status_breakdown"] = dict(status_counts)
    # Flush any backfilled source_path updates
    registry.flush()
    logger.info(f"Sync complete: {counts}")
    return counts
