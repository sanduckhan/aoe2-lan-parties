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
from analyzer_lib.analyze_games import (
    _calculate_losing_streaks,
    extract_single_game_deltas,
)
from analyzer_lib.report_generator import (
    compute_all_awards,
    compute_general_stats,
    compute_player_profiles,
)
from calculate_trueskill import run_trueskill_from_registry

logger = logging.getLogger(__name__)


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
    # Build a sorted, canonical representation of all players
    players_canonical = []
    for tid in sorted(teams.keys()):
        for p in sorted(teams[tid], key=lambda x: x["name"]):
            players_canonical.append(f"{tid}:{p['name']}:{p.get('civ', '')}")
    raw = f"{game_datetime}|{'|'.join(players_canonical)}"
    return hashlib.sha256(raw.encode()).hexdigest()


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
    """

    def __init__(self, registry: GameRegistry, storage_module=None):
        self._registry = registry
        self._storage = storage_module
        self._lock = threading.Lock()
        self._data_dir = registry._data_dir

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
        """Internal processing under lock."""
        from mgz.model import parse_match

        now = datetime.utcnow().isoformat()
        entry = {
            "sha256": sha256,
            "filename": "",
            "datetime": "",
            "uploaded_at": now,
            "status": "parse_error",
            "duration_seconds": 0,
            "teams": {},
            "winning_team_id": None,
            "fingerprint": "",
            "player_deltas": {},
            "game_level_deltas": {},
        }

        # --- Parse ---
        try:
            match_obj = parse_match(io.BytesIO(file_bytes))
        except Exception as e:
            logger.error(f"Parse error for {sha256}: {e}")
            entry["status"] = "parse_error"
            entry["message"] = str(e)
            self._registry.add_game(entry)
            return {
                "status": "parse_error",
                "sha256": sha256,
                "message": f"Failed to parse replay: {e}",
            }

        if not match_obj:
            self._registry.add_game(entry)
            return {
                "status": "parse_error",
                "sha256": sha256,
                "message": "Parser returned no data.",
            }

        # --- Extract basic metadata ---
        try:
            entry["filename"] = getattr(match_obj, "filename", "") or ""
            duration_seconds = match_obj.duration.total_seconds()
            entry["duration_seconds"] = duration_seconds

            # Extract datetime from filename or match timestamp
            from analyzer_lib.replay_parser import get_datetime_from_filename

            if entry["filename"]:
                try:
                    dt = get_datetime_from_filename(entry["filename"])
                    entry["datetime"] = dt.isoformat()
                except Exception:
                    pass
            if not entry["datetime"] and hasattr(match_obj, "timestamp"):
                entry["datetime"] = str(match_obj.timestamp)
        except Exception as e:
            logger.error(f"Metadata extraction error for {sha256}: {e}")
            self._registry.add_game(entry)
            return {
                "status": "parse_error",
                "sha256": sha256,
                "message": f"Failed to extract metadata: {e}",
            }

        # --- Validate duration ---
        if duration_seconds < 300:
            entry["status"] = "too_short"
            self._registry.add_game(entry)
            return {
                "status": "too_short",
                "sha256": sha256,
                "filename": entry["filename"],
                "datetime": entry["datetime"],
                "message": f"Game too short ({duration_seconds:.0f}s < 5min).",
            }

        # --- Identify human players and validate ---
        human_players = [
            p
            for p in match_obj.players
            if hasattr(p, "profile_id") and p.profile_id is not None
        ]

        canonical_names = set(config.PLAYER_ALIASES.values())
        for p in human_players:
            aliased = config.PLAYER_ALIASES.get(p.name, p.name)
            if aliased not in canonical_names:
                entry["status"] = "unknown_player"
                self._registry.add_game(entry)
                return {
                    "status": "unknown_player",
                    "sha256": sha256,
                    "filename": entry["filename"],
                    "datetime": entry["datetime"],
                    "message": f"Unknown player: {p.name}",
                }

        # Apply aliases
        for p in human_players:
            p.name = config.PLAYER_ALIASES.get(p.name, p.name)

        # --- Determine teams and winner ---
        teams_data = defaultdict(list)
        for p in human_players:
            team_id = p.team_id
            if isinstance(team_id, list):
                team_id = team_id[0] if team_id else -1
            teams_data[team_id].append(p)

        winning_team_id = None
        for team_id, players_in_team in teams_data.items():
            if any(p.winner for p in players_in_team):
                winning_team_id = team_id
                break

        # Build teams dict for registry
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
        entry["winning_team_id"] = str(winning_team_id) if winning_team_id is not None else None

        # --- Fingerprint dedup (same game recorded by different players) ---
        if entry["datetime"] and teams_dict:
            fingerprint = compute_game_fingerprint(entry["datetime"], teams_dict)
            entry["fingerprint"] = fingerprint
            if self._registry.has_fingerprint(fingerprint):
                return {
                    "status": "duplicate",
                    "sha256": sha256,
                    "filename": entry["filename"],
                    "datetime": entry["datetime"],
                    "message": "This game was already uploaded by another player.",
                }

        # --- Extract per-game deltas ---
        try:
            player_deltas, game_deltas = extract_single_game_deltas(
                match_obj, human_players
            )
            entry["player_deltas"] = player_deltas
            entry["game_level_deltas"] = game_deltas
        except Exception as e:
            logger.warning(f"Delta extraction failed for {sha256}: {e}")
            entry["player_deltas"] = {}
            entry["game_level_deltas"] = {}

        # --- Determine final status ---
        if winning_team_id is None:
            entry["status"] = "no_winner"
        else:
            entry["status"] = "processed"

        # --- Store in bucket (non-critical) ---
        if self._storage:
            try:
                self._storage.upload_replay(file_bytes, sha256)
            except Exception as e:
                logger.warning(f"Bucket upload failed for {sha256} (non-critical): {e}")

        # --- Register in registry ---
        self._registry.add_game(entry)

        # --- Rebuild TrueSkill ---
        try:
            processed_games = self._registry.get_games(status="processed")
            run_trueskill_from_registry(processed_games, data_dir=self._data_dir)
        except Exception as e:
            logger.error(f"TrueSkill rebuild failed: {e}")

        # --- Rebuild analysis data ---
        try:
            rebuild_analysis_from_registry(self._registry, data_dir=self._data_dir)
        except Exception as e:
            logger.error(f"Analysis rebuild failed: {e}")

        # --- Build response ---
        teams_summary = {}
        for tid, players in teams_dict.items():
            teams_summary[tid] = [p["name"] for p in players]

        return {
            "status": entry["status"],
            "sha256": sha256,
            "filename": entry["filename"],
            "datetime": entry["datetime"],
            "teams": teams_summary,
            "message": f"Replay processed successfully (status: {entry['status']}).",
        }

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

                entry = self._parse_replay_to_entry(file_bytes, sha)
                new_games.append(entry)
                counts[entry["status"]] += 1

            # Replace entire registry
            self._registry.replace_all(new_games)

            # Rebuild TrueSkill
            try:
                processed_games = [
                    g for g in new_games if g["status"] == "processed"
                ]
                run_trueskill_from_registry(
                    processed_games, data_dir=self._data_dir
                )
            except Exception as e:
                logger.error(f"TrueSkill rebuild during full rebuild failed: {e}")

            # Rebuild analysis
            try:
                rebuild_analysis_from_registry(
                    self._registry, data_dir=self._data_dir
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

    def _parse_replay_to_entry(self, file_bytes, sha256):
        """Parse a single replay into a registry entry dict (used by full_rebuild)."""
        from mgz.model import parse_match

        now = datetime.utcnow().isoformat()
        entry = {
            "sha256": sha256,
            "filename": "",
            "datetime": "",
            "uploaded_at": now,
            "status": "parse_error",
            "duration_seconds": 0,
            "teams": {},
            "winning_team_id": None,
            "fingerprint": "",
            "player_deltas": {},
            "game_level_deltas": {},
        }

        try:
            match_obj = parse_match(io.BytesIO(file_bytes))
        except Exception as e:
            logger.error(f"Parse error for {sha256}: {e}")
            return entry

        if not match_obj:
            return entry

        try:
            entry["filename"] = getattr(match_obj, "filename", "") or ""
            duration_seconds = match_obj.duration.total_seconds()
            entry["duration_seconds"] = duration_seconds

            from analyzer_lib.replay_parser import get_datetime_from_filename

            if entry["filename"]:
                try:
                    dt = get_datetime_from_filename(entry["filename"])
                    entry["datetime"] = dt.isoformat()
                except Exception:
                    pass
            if not entry["datetime"] and hasattr(match_obj, "timestamp"):
                entry["datetime"] = str(match_obj.timestamp)
        except Exception as e:
            logger.error(f"Metadata error for {sha256}: {e}")
            return entry

        if duration_seconds < 300:
            entry["status"] = "too_short"
            return entry

        human_players = [
            p
            for p in match_obj.players
            if hasattr(p, "profile_id") and p.profile_id is not None
        ]

        canonical_names = set(config.PLAYER_ALIASES.values())
        for p in human_players:
            aliased = config.PLAYER_ALIASES.get(p.name, p.name)
            if aliased not in canonical_names:
                entry["status"] = "unknown_player"
                return entry

        for p in human_players:
            p.name = config.PLAYER_ALIASES.get(p.name, p.name)

        teams_data = defaultdict(list)
        for p in human_players:
            team_id = p.team_id
            if isinstance(team_id, list):
                team_id = team_id[0] if team_id else -1
            teams_data[team_id].append(p)

        winning_team_id = None
        for team_id, players_in_team in teams_data.items():
            if any(p.winner for p in players_in_team):
                winning_team_id = team_id
                break

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

        # Compute fingerprint for index (no dedup check in full_rebuild)
        if entry["datetime"] and teams_dict:
            entry["fingerprint"] = compute_game_fingerprint(
                entry["datetime"], teams_dict
            )

        try:
            player_deltas, game_deltas = extract_single_game_deltas(
                match_obj, human_players
            )
            entry["player_deltas"] = player_deltas
            entry["game_level_deltas"] = game_deltas
        except Exception as e:
            logger.warning(f"Delta extraction failed for {sha256}: {e}")

        if winning_team_id is None:
            entry["status"] = "no_winner"
        else:
            entry["status"] = "processed"

        return entry


def rebuild_analysis_from_registry(registry, data_dir=None):
    """Rebuild analysis_data.json from the game registry.

    Iterates over all "processed" and "no_winner" games, sorted chronologically,
    and reconstructs player_stats, game_stats, game_results, and head_to_head
    from stored deltas and core metadata.

    Args:
        registry: GameRegistry instance.
        data_dir: Output directory. Defaults to config.DATA_DIR.
    """
    output_dir = data_dir or config.DATA_DIR
    all_games = registry.get_all_data()["games"]

    # Filter to games that contribute to analysis
    analysis_games = [
        g for g in all_games if g.get("status") in ("processed", "no_winner")
    ]
    analysis_games.sort(key=lambda g: g.get("datetime", ""))

    # Fresh accumulators (mirrors analyze_games.py module-level globals)
    player_stats = defaultdict(lambda: {
        "games_played": 0,
        "games_for_win_rate": 0,
        "wins": 0,
        "total_playtime_seconds": 0,
        "total_eapm": 0,
        "games_with_eapm": 0,
        "civs_played": defaultdict(int),
        "civ_wins": defaultdict(int),
        "civ_losses": defaultdict(int),
        "civ_games_for_win_rate": defaultdict(int),
        "units_created": defaultdict(int),
        "total_units_created": 0,
        "market_transactions": 0,
        "total_resource_units_traded": 0,
        "wall_segments_built": 0,
        "buildings_deleted": 0,
        "crucial_researched": defaultdict(int),
    })

    game_stats = {
        "total_games": 0,
        "total_duration_seconds": 0,
        "longest_game": {"duration_seconds": 0, "file": ""},
        "overall_civ_picks": defaultdict(int),
        "total_units_created_overall": 0,
        "team_matchups": defaultdict(
            lambda: {"rosters": (), "wins_A": 0, "wins_B": 0}
        ),
        "awards": {
            "favorite_unit_fanatic": defaultdict(
                lambda: {"unit": "N/A", "count": 0}
            ),
            "bitter_salt_baron": {"player": None, "streak": 0},
            "market_mogul": {"player": None, "transactions": 0},
        },
    }

    game_results = []
    head_to_head = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0}))
    player_game_chronology = defaultdict(list)

    for game in analysis_games:
        filename = game.get("filename", "")
        duration = game.get("duration_seconds", 0)
        teams = game.get("teams", {})
        winning_tid = game.get("winning_team_id")
        has_winner = winning_tid is not None

        # --- General game stats ---
        game_stats["total_games"] += 1
        game_stats["total_duration_seconds"] += duration
        if duration > game_stats["longest_game"]["duration_seconds"]:
            game_stats["longest_game"]["duration_seconds"] = duration
            game_stats["longest_game"]["file"] = filename

        # --- Per-player core stats from teams metadata ---
        all_winners = set()
        all_losers = set()

        for tid, players in teams.items():
            for p_info in players:
                name = p_info["name"]
                civ = p_info.get("civ", "Unknown")
                is_winner = p_info.get("winner", False)
                eapm = p_info.get("eapm")

                player_stats[name]["games_played"] += 1
                if has_winner:
                    player_stats[name]["games_for_win_rate"] += 1
                if is_winner:
                    player_stats[name]["wins"] += 1
                    all_winners.add(name)
                elif has_winner:
                    all_losers.add(name)

                player_stats[name]["total_playtime_seconds"] += duration

                if eapm:
                    player_stats[name]["total_eapm"] += eapm
                    player_stats[name]["games_with_eapm"] += 1

                player_stats[name]["civs_played"][civ] += 1
                game_stats["overall_civ_picks"][civ] += 1
                if has_winner:
                    player_stats[name]["civ_games_for_win_rate"][civ] += 1

                if is_winner:
                    player_stats[name]["civ_wins"][civ] += 1
                elif has_winner:
                    player_stats[name]["civ_losses"][civ] += 1

                # Chronology for losing streaks
                player_game_chronology[name].append({
                    "won": is_winner,
                    "has_winner": has_winner,
                    "timestamp": game.get("datetime", ""),
                })

        # --- Action-based stats from player_deltas ---
        player_deltas = game.get("player_deltas", {})
        for name, deltas in player_deltas.items():
            for unit, count in deltas.get("units_created", {}).items():
                player_stats[name]["units_created"][unit] += count
            player_stats[name]["total_units_created"] += deltas.get(
                "total_units_created", 0
            )
            player_stats[name]["market_transactions"] += deltas.get(
                "market_transactions", 0
            )
            player_stats[name]["total_resource_units_traded"] += deltas.get(
                "total_resource_units_traded", 0
            )
            player_stats[name]["wall_segments_built"] += deltas.get(
                "wall_segments_built", 0
            )
            player_stats[name]["buildings_deleted"] += deltas.get(
                "buildings_deleted", 0
            )
            for tech, val in deltas.get("crucial_researched", {}).items():
                player_stats[name]["crucial_researched"][tech] += val

        game_level_deltas = game.get("game_level_deltas", {})
        game_stats["total_units_created_overall"] += game_level_deltas.get(
            "total_units_created_overall", 0
        )

        # --- Game results for web UI ---
        game_result_teams = {}
        for tid, players in teams.items():
            game_result_teams[tid] = [
                {
                    "name": p["name"],
                    "civilization": p.get("civ", "Unknown"),
                    "winner": bool(p.get("winner", False)),
                }
                for p in players
            ]
        game_results.append({
            "filename": filename,
            "datetime": game.get("datetime", ""),
            "duration_seconds": duration,
            "winning_team_id": winning_tid,
            "teams": game_result_teams,
        })

        # --- Head-to-head ---
        if has_winner and all_winners and all_losers:
            for w in all_winners:
                for l in all_losers:
                    head_to_head[w][l]["wins"] += 1
                    head_to_head[l][w]["losses"] += 1

        # --- Team matchup stats ---
        if has_winner and len(teams) == 2:
            team_rosters = []
            for tid in sorted(teams.keys()):
                roster = tuple(sorted(p["name"] for p in teams[tid]))
                team_rosters.append(roster)
            canonical_rosters = tuple(team_rosters)
            matchup_key = str(canonical_rosters)

            # Determine which canonical roster corresponds to team A
            team_a_roster = canonical_rosters[0]
            sorted_tids = sorted(teams.keys())
            team_a_id = sorted_tids[0]

            if not game_stats["team_matchups"][matchup_key]["rosters"]:
                game_stats["team_matchups"][matchup_key]["rosters"] = canonical_rosters

            if winning_tid == team_a_id:
                game_stats["team_matchups"][matchup_key]["wins_A"] += 1
            else:
                game_stats["team_matchups"][matchup_key]["wins_B"] += 1

    # --- Calculate losing streaks ---
    _calculate_losing_streaks(player_game_chronology, player_stats)

    # --- Compute awards, general stats, player profiles ---
    analysis_data = {
        "awards": compute_all_awards(player_stats, game_stats),
        "general_stats": compute_general_stats(game_stats),
        "game_results": game_results,
        "player_profiles": compute_player_profiles(player_stats, head_to_head),
    }

    # --- Write analysis_data.json ---
    output_path = os.path.join(output_dir, "analysis_data.json")
    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(analysis_data, f, indent=2, default=str)
    os.rename(tmp_path, output_path)
    logger.info(f"Analysis data saved to: {output_path}")
