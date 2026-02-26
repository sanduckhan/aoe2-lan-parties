# PRD: Server API & Cache

## Introduction

The AoE2 LAN Party Analyzer web app currently serves a read-only JSON API from pre-computed data files. This PRD adds new API endpoints for uploading replays and triggering rebuilds, introduces API key authentication for write operations, and replaces the permanent in-memory cache with an mtime-based cache that automatically picks up changes when data files are updated by the processing pipeline (PRD 1).

## Goals

- Add `POST /api/upload` endpoint that accepts replay file uploads and triggers the processing pipeline
- Add `POST /api/rebuild` endpoint that triggers a full rebuild from all bucket replays
- Protect write endpoints with API key authentication (`X-API-Key` header)
- Replace the permanent `_analysis_cache` in `web/services.py` with mtime-based caching that auto-reloads when files change on disk
- Apply the same mtime-based caching to `player_ratings.json` and `rating_history.json`
- Ensure CORS headers allow the Windows uploader client to communicate with the server

## User Stories

### US-001: Upload replay via API
**Description:** As the Windows uploader client, I want to POST a replay file to the server so that it gets processed and ratings/stats are updated.

**Acceptance Criteria:**
- [ ] `POST /api/upload` accepts multipart form data with a `file` field (the `.aoe2record` file) and a `sha256` field (hex string)
- [ ] Server verifies the SHA256 of the received file matches the `sha256` field; returns 400 if mismatch
- [ ] On new game: returns 200 with JSON body containing `status`, `filename`, `datetime`, and `message`
- [ ] On duplicate: returns 409 with `{"status": "duplicate", "message": "Game already processed"}`
- [ ] On processing error: returns 200 with `status` set to the error category (`"parse_error"`, `"too_short"`, `"unknown_player"`) and an explanatory `message`
- [ ] Requires valid `X-API-Key` header; returns 401 without it

### US-002: Force full rebuild via API
**Description:** As a server operator, I want to trigger a full rebuild from all bucket replays so that I can apply config changes (new player aliases, parameter tweaks) retroactively.

**Acceptance Criteria:**
- [ ] `POST /api/rebuild` triggers `IncrementalProcessor.full_rebuild()`
- [ ] Returns 200 with a summary JSON: `total_processed`, `skipped_counts`, `duration_seconds`
- [ ] Requires valid `X-API-Key` header; returns 401 without it
- [ ] Long-running: may take several minutes. Returns result when complete (no async/background job needed at this scale).

### US-003: API key authentication
**Description:** As a server operator, I want write endpoints protected by an API key so that only authorized clients (the uploader .exe and admin) can upload replays or trigger rebuilds.

**Acceptance Criteria:**
- [ ] API key is read from `config.API_KEY` (which reads `API_KEY` env var)
- [ ] A `require_api_key` decorator (or `before_request` check) validates `X-API-Key` header on protected routes
- [ ] If `API_KEY` env var is empty/unset, protected endpoints return 503 with `"API key not configured"`
- [ ] Read-only endpoints (`GET /api/players`, `/api/awards`, etc.) require no authentication

### US-004: Mtime-based cache for analysis data
**Description:** As the web app, I want `analysis_data.json` to be automatically reloaded when it changes on disk so that the UI reflects the latest stats after a replay is processed.

**Acceptance Criteria:**
- [ ] Replace `_analysis_cache = None` pattern in `web/services.py` with mtime-based reload
- [ ] On each call to `_load_analysis_data()`: check `os.path.getmtime(ANALYSIS_DATA_PATH)`. If mtime is newer than cached mtime, reload from disk.
- [ ] If the file does not exist, return an empty dict (no crash)
- [ ] First call loads from disk (cold start)

### US-005: Mtime-based cache for player ratings
**Description:** As the web app, I want `player_ratings.json` to be automatically reloaded when it changes so that the ratings leaderboard reflects updates after each game.

**Acceptance Criteria:**
- [ ] `load_ratings()` in `web/services.py` uses mtime-based caching (same pattern as analysis data)
- [ ] Cached ratings are used by `get_players_for_api()`, `_ratings_dict()`, and any other function that calls `load_ratings()`

### US-006: Mtime-based cache for rating history
**Description:** As the web app, I want `rating_history.json` to be automatically reloaded when it changes so that the rating chart and LAN events reflect the latest data.

**Acceptance Criteria:**
- [ ] `get_rating_history_for_api()` in `web/services.py` uses mtime-based caching
- [ ] Both old format (flat list) and new format (dict with `history` + `lan_events`) continue to be supported

### US-007: Wire up service layer to processing pipeline
**Description:** As the web app, I want the upload and rebuild routes to call into the processing pipeline so that everything is connected end-to-end.

**Acceptance Criteria:**
- [ ] New function `process_upload(file_bytes, sha256)` in `web/services.py` that instantiates/reuses `IncrementalProcessor` and calls `process_new_replay()`
- [ ] New function `trigger_rebuild()` in `web/services.py` that calls `IncrementalProcessor.full_rebuild()`
- [ ] The `IncrementalProcessor` instance is created once at module level in `services.py` (singleton pattern) and reused across requests
- [ ] `GameRegistry` and `IncrementalProcessor` are initialized with paths derived from `config.DATA_DIR`

## Functional Requirements

- FR-1: New route `POST /api/upload` in `web/app.py`. Accepts multipart form: `file` (binary), `sha256` (text). Validates SHA256 match. Calls `services.process_upload()`. Returns appropriate status code (200, 400, 401, 409).
- FR-2: New route `POST /api/rebuild` in `web/app.py`. Calls `services.trigger_rebuild()`. Returns summary JSON.
- FR-3: `require_api_key` decorator in `web/app.py`:
  ```python
  def require_api_key(f):
      @wraps(f)
      def decorated(*args, **kwargs):
          if not config.API_KEY:
              return jsonify({"error": "API key not configured"}), 503
          key = request.headers.get("X-API-Key", "")
          if key != config.API_KEY:
              return jsonify({"error": "Invalid API key"}), 401
          return f(*args, **kwargs)
      return decorated
  ```
- FR-4: Mtime-based cache helper (can be a small class or closures):
  ```python
  class MtimeCache:
      def __init__(self, path):
          self._path = path
          self._data = None
          self._mtime = 0

      def get(self):
          try:
              current_mtime = os.path.getmtime(self._path)
          except FileNotFoundError:
              return None
          if self._data is None or current_mtime > self._mtime:
              with open(self._path, "r") as f:
                  self._data = json.load(f)
              self._mtime = current_mtime
          return self._data
  ```
- FR-5: Replace `_analysis_cache` global with `MtimeCache(ANALYSIS_DATA_PATH)`. Update `_load_analysis_data()` to use it.
- FR-6: Add `MtimeCache(RATINGS_PATH)` for player ratings. Update `load_ratings()` to use it.
- FR-7: Add `MtimeCache(RATING_HISTORY_PATH)` for rating history. Update `get_rating_history_for_api()` to use it.
- FR-8: All JSON file paths in `services.py` should use `config.DATA_DIR`:
  ```python
  RATINGS_PATH = os.path.join(config.DATA_DIR, "player_ratings.json")
  ANALYSIS_DATA_PATH = os.path.join(config.DATA_DIR, "analysis_data.json")
  RATING_HISTORY_PATH = os.path.join(config.DATA_DIR, "rating_history.json")
  ```
- FR-9: The `IncrementalProcessor` singleton in `services.py` is initialized lazily (on first upload request), not at import time, to avoid crashing when bucket env vars are not set (local dev).

## Non-Goals

- No WebSocket/SSE for real-time push updates to the UI (polling or manual refresh is fine)
- No rate limiting on upload endpoint (trusted clients only, protected by API key)
- No file size validation beyond what the processing pipeline handles (corrupt/invalid files are caught during parsing)
- No background job queue (processing is synchronous and fast enough at this scale)
- No HTTPS termination (Railway handles TLS at the proxy level)
- LAN event endpoints are covered in PRD 3, not here

## Technical Considerations

- **Gunicorn workers**: With 2 gunicorn workers (separate processes), each has its own `MtimeCache` and `IncrementalProcessor`. The mtime check ensures both workers see updated data. The processing lock in `IncrementalProcessor` is per-process, but since uploads are infrequent (a few per hour at most), the chance of two workers processing simultaneously is negligible. Atomic file writes from the registry prevent corruption.
- **Request timeout**: `POST /api/rebuild` can take several minutes. Gunicorn's default worker timeout (30s) must be increased, or the rebuild endpoint should be called with a longer timeout. Consider setting `--timeout 600` for gunicorn.
- **File upload size**: AoE2 replay files are typically 1-5 MB. Flask's default max content length should be set to 50 MB to be safe: `app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024`.
- **SHA256 verification**: The server computes SHA256 of the received file bytes and compares against the client-provided `sha256` field. This catches transmission corruption and ensures the client and server agree on file identity.
- **Existing routes unchanged**: All current GET endpoints continue to work exactly as before. The only behavioral change is that their underlying data may update more frequently (after each upload vs. manual batch run).

## Success Metrics

- Upload endpoint processes a valid replay and returns 200 within 10 seconds
- Duplicate upload returns 409 within 100ms (no processing overhead)
- After an upload, a subsequent GET to `/api/players` returns updated ratings without server restart
- Full rebuild endpoint completes for 500 replays and returns a summary
- All existing API endpoints continue to work without modification to their request/response format

## Open Questions

- Should we add a `GET /api/upload/status` endpoint that shows recent upload history (last N uploads with status)? This could help debug issues without checking server logs.
- Should the upload endpoint return the game's rating changes (who gained/lost points) in the response body? This would let the uploader client show a notification like "Game uploaded! Sanduck +15, LiKiD -12".
