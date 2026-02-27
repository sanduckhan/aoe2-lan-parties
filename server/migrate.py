#!/usr/bin/env python3
"""One-time migration: bootstrap game registry from existing recorded_games/ directory.

Scans all replay files, parses them, builds a complete game_registry.json,
optionally uploads to Railway Bucket, and generates all JSON data files
(player_ratings.json, rating_history.json, analysis_data.json).

Usage:
    python -m server.migrate
    python -m server.migrate --skip-bucket
    python -m server.migrate --data-dir /tmp/test_output
"""

import argparse
import hashlib
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure project root and scripts are importable
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SERVER_DIR)
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))

from analyzer_lib import config
from analyzer_lib.registry_builder import replay_to_registry_entry
from calculate_trueskill import run_trueskill_from_registry

from server.processing import (
    GameRegistry,
    rebuild_analysis_from_registry,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

REPLAY_EXTENSIONS = (".aoe2record", ".mgz", ".mgx")


def _find_replay_files(replay_dir):
    """Walk replay_dir recursively and return list of full file paths."""
    files = []
    for root, _, filenames in os.walk(replay_dir):
        for fn in filenames:
            if any(fn.lower().endswith(ext) for ext in REPLAY_EXTENSIONS):
                files.append(os.path.join(root, fn))
    return files


def _process_single_file(file_path):
    """Read, hash, parse, and build a registry entry for a single replay file.

    Returns (entry_dict, file_bytes) tuple. file_bytes is needed for bucket upload.
    """
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    entry = replay_to_registry_entry(file_bytes, sha256, filename_hint=filename)
    return entry, file_bytes


def main():
    parser = argparse.ArgumentParser(
        description="Migrate existing replays to game registry"
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help=f"Output directory (default: {config.DATA_DIR})",
    )
    parser.add_argument(
        "--replay-dir",
        default=config.RECORDED_GAMES_DIR,
        help=f"Replay directory (default: {config.RECORDED_GAMES_DIR})",
    )
    parser.add_argument(
        "--skip-bucket",
        action="store_true",
        help="Skip bucket uploads even if bucket env vars are set",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: system-managed)",
    )
    args = parser.parse_args()

    data_dir = args.data_dir or config.DATA_DIR
    os.makedirs(data_dir, exist_ok=True)

    # ── Step 1: Find replay files ──────────────────────────────────────
    logger.info(f"Scanning {args.replay_dir} for replay files...")
    file_paths = _find_replay_files(args.replay_dir)
    logger.info(f"Found {len(file_paths)} replay files")

    if not file_paths:
        logger.warning("No replay files found. Nothing to migrate.")
        return

    # ── Step 2: Parse all replays in parallel ──────────────────────────
    logger.info("Parsing replays...")
    entries = []
    file_bytes_map = {}  # sha256 -> file_bytes (for bucket upload)
    counts = {
        "processed": 0,
        "no_winner": 0,
        "too_short": 0,
        "unknown_player": 0,
        "parse_error": 0,
        "duplicate": 0,
    }
    seen_fingerprints = set()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_process_single_file, fp): fp for fp in file_paths}
        for i, future in enumerate(as_completed(futures), 1):
            if i % 50 == 0 or i == len(file_paths):
                logger.info(f"Parsed {i}/{len(file_paths)}...")
            try:
                entry, file_bytes = future.result()

                # Deduplicate by fingerprint (same game recorded by different players)
                fp = entry.get("fingerprint")
                if fp and fp in seen_fingerprints:
                    entry["status"] = "duplicate"
                elif fp:
                    seen_fingerprints.add(fp)

                entries.append(entry)
                counts[entry["status"]] += 1

                # Keep file bytes for bucket upload if game is useful
                if not args.skip_bucket and entry["status"] in (
                    "processed",
                    "no_winner",
                ):
                    file_bytes_map[entry["sha256"]] = file_bytes

            except Exception as e:
                logger.error(f"Failed to process {futures[future]}: {e}")
                counts["parse_error"] += 1

    # ── Step 3: Sort chronologically and save registry ─────────────────
    entries.sort(key=lambda e: e.get("datetime", ""))
    logger.info("Building game registry...")

    registry = GameRegistry(data_dir=data_dir)
    registry.replace_all(entries)
    logger.info(f"Game registry saved: {registry.path}")

    # ── Step 4: Upload to bucket (if configured) ──────────────────────
    if not args.skip_bucket and file_bytes_map:
        try:
            from server import storage

            total = len(file_bytes_map)
            logger.info(f"Uploading {total} replays to bucket...")
            for i, (sha256, fb) in enumerate(file_bytes_map.items(), 1):
                if i % 10 == 0 or i == total:
                    logger.info(f"Uploading to bucket: {i}/{total}...")
                storage.upload_replay(fb, sha256)
            logger.info("Bucket uploads complete")
        except Exception as e:
            logger.warning(f"Bucket upload skipped: {e}")
    elif args.skip_bucket:
        logger.info("Bucket upload skipped (--skip-bucket flag)")

    # Free memory before rebuilds
    file_bytes_map.clear()

    # ── Step 5: Generate TrueSkill ratings ─────────────────────────────
    logger.info("Generating TrueSkill ratings...")
    ratable_games = registry.get_games(status=["processed", "no_winner"])
    run_trueskill_from_registry(ratable_games, data_dir=data_dir)
    logger.info("TrueSkill ratings saved")

    # ── Step 6: Generate analysis data ─────────────────────────────────
    logger.info("Generating analysis data...")
    rebuild_analysis_from_registry(registry, data_dir=data_dir)
    logger.info("Analysis data saved")

    # ── Step 7: Print summary ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"Total replay files found: {len(file_paths)}")
    print(f"  Processed:      {counts['processed']}")
    print(f"  No winner:      {counts['no_winner']}")
    print(f"  Too short:      {counts['too_short']}")
    print(f"  Unknown player: {counts['unknown_player']}")
    print(f"  Parse error:    {counts['parse_error']}")
    print(f"  Duplicate:      {counts['duplicate']}")
    print(f"\nOutput directory: {data_dir}")
    print(f"  game_registry.json")
    print(f"  player_ratings.json")
    print(f"  rating_history.json")
    print(f"  analysis_data.json")


if __name__ == "__main__":
    main()
