"""Shared parallel replay file parser for AoE2 recorded games."""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from mgz.model import parse_match

from . import config

MIN_GAME_DURATION_SECONDS = 300


def get_datetime_from_filename(filename):
    """Extract datetime from replay filename for chronological sorting."""
    match = re.search(r'@(\d{4}\.\d{2}\.\d{2} \d{6})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y.%m.%d %H%M%S')
        except ValueError:
            return datetime.min
    return datetime.min


def _parse_single_file(file_path):
    """Parse one replay file. Returns (filename, match_obj) or (filename, None)."""
    filename = os.path.basename(file_path)
    try:
        with open(file_path, 'rb') as f:
            match_obj = parse_match(f)

        if not match_obj:
            return (filename, None)

        if match_obj.duration.total_seconds() < MIN_GAME_DURATION_SECONDS:
            return (filename, None)

        return (filename, match_obj)

    except Exception as e:
        print(f"  -> Skipping {filename}: {e}")
        return (filename, None)


def parse_replays_parallel(replay_dir=None, max_workers=None):
    """Parse all replay files in parallel using a thread pool.

    Returns a chronologically sorted list of (filename, match_obj) tuples
    for games that passed basic validation (parseable, >= 5 min).
    """
    if replay_dir is None:
        replay_dir = config.RECORDED_GAMES_DIR

    if not os.path.isdir(replay_dir):
        print(f"Error: Directory '{replay_dir}' not found.")
        return []

    file_paths = []
    for root, _, files in os.walk(replay_dir):
        for f in files:
            if f.endswith(('.aoe2record', '.mgz', '.mgx')):
                file_paths.append(os.path.join(root, f))

    if not file_paths:
        print("No replay files found.")
        return []

    total = len(file_paths)
    print(f"Parsing {total} replay files...")

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_parse_single_file, fp): fp for fp in file_paths}
        for future in as_completed(futures):
            filename, match_obj = future.result()
            if match_obj is not None:
                results.append((filename, match_obj))

    results.sort(key=lambda r: get_datetime_from_filename(r[0]))
    print(f"Successfully parsed {len(results)}/{total} replay files.")
    return results
