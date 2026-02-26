# PRD: Windows Uploader Client

## Introduction

The AoE2 LAN Party Analyzer needs a way for all players to automatically upload their replay files to the central server. This PRD covers a Windows desktop application packaged as a single `.exe` file that friends download, run once, and forget about. It runs as a system tray daemon that auto-starts with Windows, watches for new `.aoe2record` files, and uploads them to the server. No technical knowledge required — it auto-detects the AoE2 savegame folder and uses a baked-in server URL and API key.

## Goals

- Provide a zero-configuration experience: download .exe, run it, done
- Auto-detect the AoE2 DE savegame folder on Windows
- Run as a background daemon that starts automatically with Windows
- Watch for new replay files and upload them to the server
- Deduplicate locally (don't re-upload files already sent)
- Handle offline scenarios gracefully with retry logic
- Catch up on missed games when the app starts (upload any un-uploaded replays)

## User Stories

### US-001: First run auto-detection
**Description:** As a non-technical friend, I want the app to find my AoE2 replay folder automatically so that I don't have to configure anything.

**Acceptance Criteria:**
- [ ] On first launch, app scans `C:\Users\<user>\Games\Age of Empires 2 DE\` for Steam ID subdirectories containing `savegame\` folders
- [ ] If exactly one savegame folder found: app starts watching immediately with no user interaction needed
- [ ] If multiple Steam ID folders found: app shows a simple picker dialog listing the Steam IDs, user selects one, then watching starts
- [ ] If no savegame folder found: app shows an error dialog with instructions to manually select the folder
- [ ] Selected path is saved to config so auto-detection only happens on first run

### US-002: System tray daemon
**Description:** As a player, I want the app to run silently in the system tray so that it doesn't interfere with my gaming.

**Acceptance Criteria:**
- [ ] After first run, app minimizes to the system tray (notification area)
- [ ] Tray icon shows status: green = watching, yellow = uploading, red = error/offline
- [ ] Right-click tray icon shows context menu: "Show Log", "Pause/Resume", "Settings", "Exit"
- [ ] "Show Log" opens a small window with scrollable upload history
- [ ] "Pause/Resume" toggles watching on/off
- [ ] "Settings" shows a dialog to change savegame folder path
- [ ] "Exit" closes the app entirely (with confirmation if uploads are pending)
- [ ] Double-click tray icon opens the log window

### US-003: Auto-start with Windows
**Description:** As a player, I want the app to start automatically when I log into Windows so that I never have to remember to launch it.

**Acceptance Criteria:**
- [ ] On first run, app creates a shortcut in the Windows Startup folder (`shell:startup`) pointing to itself
- [ ] On subsequent Windows logins, app starts silently (no window, straight to system tray)
- [ ] If the user moves the .exe to a different location, the startup shortcut still works (or gracefully fails)
- [ ] "Settings" dialog has a checkbox to enable/disable auto-start

### US-004: Watch and upload new replays
**Description:** As a player, I want new replay files to be automatically uploaded after each game so that the server always has the latest data.

**Acceptance Criteria:**
- [ ] App polls the savegame directory every 30 seconds for `.aoe2record` files
- [ ] When a new file is detected, app waits for the file size to stabilize (no change for 10 seconds) before processing
- [ ] App computes SHA256 hash of the file
- [ ] App checks hash against local `uploaded_hashes.json` — skips if already uploaded
- [ ] App POSTs file to `{server_url}/api/upload` as multipart with `file` and `sha256` fields, plus `X-API-Key` header
- [ ] On 200 response: hash added to local set, brief tray notification shown ("Game uploaded!")
- [ ] On 409 response (duplicate): hash added to local set silently (someone else uploaded first)
- [ ] On error (network, 5xx, timeout): file added to retry queue

### US-005: Retry failed uploads
**Description:** As a player, I want failed uploads to be retried automatically so that games aren't lost when the server is temporarily unreachable.

**Acceptance Criteria:**
- [ ] Failed uploads are queued in memory with retry counter
- [ ] Retry occurs every 60 seconds
- [ ] Maximum 10 retries per file (then marked as failed in log, stops retrying)
- [ ] Tray icon turns red when there are pending retries
- [ ] When server becomes reachable again, queued files are processed

### US-006: Catch up on startup
**Description:** As a player, I want the app to upload any replays I played while it was off so that no games are missed.

**Acceptance Criteria:**
- [ ] On startup, app scans the savegame folder for all `.aoe2record` files
- [ ] Files whose SHA256 is not in `uploaded_hashes.json` are queued for upload
- [ ] Catch-up uploads happen in chronological order (oldest first)
- [ ] A progress indicator shows during catch-up: "Uploading 3/15 replays..."
- [ ] Catch-up does not block the watching of new files (both can happen in parallel)

### US-007: Persistent state
**Description:** As a player, I want my config and upload history to persist across restarts so that the app doesn't re-upload everything each time.

**Acceptance Criteria:**
- [ ] Config saved to `%APPDATA%\AoE2Uploader\config.json`: `savegame_path`, `auto_start` (bool), `server_url`
- [ ] Upload history saved to `%APPDATA%\AoE2Uploader\uploaded_hashes.json`: set of SHA256 strings
- [ ] Both files are created on first run
- [ ] Corrupt/missing config triggers re-detection (first-run experience)
- [ ] Corrupt/missing hashes file starts fresh (will re-upload, server deduplicates)

### US-008: Build as standalone .exe
**Description:** As the developer, I want to package the app as a single .exe with no dependencies so that distribution is trivial.

**Acceptance Criteria:**
- [ ] `build.bat` script runs PyInstaller to produce `AoE2 Uploader.exe`
- [ ] Server URL and API key are baked into the .exe as constants (friends never configure these)
- [ ] .exe runs on Windows 10/11 without Python installed
- [ ] .exe size is under 25 MB
- [ ] `client/requirements.txt` lists all Python dependencies: `requests`, `pystray`, `Pillow`

## Functional Requirements

- FR-1: Create `client/` directory with `uploader.py`, `build.bat`, `requirements.txt`, and `icon.ico` (placeholder)
- FR-2: `uploader.py` (~300 lines) uses:
  - `pystray` + `Pillow` for system tray icon and menu
  - `tkinter` for dialogs (folder picker, settings, log window) — bundled with Python, no extra deps
  - `requests` for HTTP uploads
  - `hashlib` for SHA256
  - `threading` for background polling
  - `json` for config/state persistence
  - `os` / `pathlib` for filesystem operations
  - `winshell` or `os` calls for startup shortcut creation
- FR-3: Constants baked into the app:
  ```python
  SERVER_URL = "https://your-railway-app.up.railway.app"  # Updated at build time
  API_KEY = "your-api-key-here"  # Updated at build time
  POLL_INTERVAL = 30  # seconds
  STABLE_WAIT = 10  # seconds to wait for file size stabilization
  RETRY_INTERVAL = 60  # seconds between retries
  MAX_RETRIES = 10
  ```
- FR-4: Savegame folder auto-detection scans:
  ```
  C:\Users\{username}\Games\Age of Empires 2 DE\{steam_id}\savegame\
  ```
  Where `{steam_id}` is a numeric directory. Multiple Steam IDs = show picker.
- FR-5: Upload function:
  ```python
  def upload_replay(file_path, sha256):
      with open(file_path, 'rb') as f:
          response = requests.post(
              f"{SERVER_URL}/api/upload",
              files={"file": (os.path.basename(file_path), f)},
              data={"sha256": sha256},
              headers={"X-API-Key": API_KEY},
              timeout=60,
          )
      return response.status_code, response.json()
  ```
- FR-6: Polling loop runs in a background thread. Main thread handles the tray icon event loop.
- FR-7: Log window (opened via "Show Log") is a `tkinter.Toplevel` with a `ScrolledText` widget showing timestamped log entries. Closing the log window hides it (doesn't exit the app).
- FR-8: Startup shortcut created via `os.startfile` + shortcut in `shell:startup`, or using `winshell.shortcut()` if available. Fallback: copy .exe to startup folder.
- FR-9: `build.bat`:
  ```batch
  pip install -r requirements.txt pyinstaller
  pyinstaller --onefile --windowed --icon=icon.ico --name="AoE2 Uploader" uploader.py
  ```
- FR-10: Tray notification on successful upload uses `pystray`'s `notify()` method (Windows toast notification).

## Non-Goals

- No macOS or Linux support (all friends use Windows)
- No auto-update mechanism (new .exe distributed manually if needed)
- No server URL configuration UI (baked into .exe)
- No replay file management (viewing, deleting, organizing)
- No game result display in the client (that's the web UI's job)
- No installer (`.msi` or similar) — single .exe is sufficient
- No admin/elevated privileges required

## Design Considerations

- The app should feel invisible after initial setup. No persistent windows, no popups except brief upload notifications.
- The tray icon should use a small AoE2-themed icon (a simple sword or castle silhouette). For the MVP, a colored circle indicating status is fine.
- The log window should show: timestamp, filename (truncated), status (uploaded / duplicate / error / retrying), and file size.
- Settings dialog should be minimal: savegame folder path (with Browse button), auto-start checkbox, and that's it.

## Technical Considerations

- **File locking during game**: AoE2 DE writes the replay file during the match. The "stable file size" check (10 seconds without change) handles this — the file is complete when its size stops changing.
- **Large backlog on first install**: A player who has been playing for years might have hundreds of replays. The catch-up scan should process them in batches, with a short delay between uploads to avoid overwhelming the server.
- **PyInstaller compatibility**: `pystray` and `tkinter` are known to work with PyInstaller's `--onefile` mode. The `--windowed` flag prevents a console window from appearing.
- **Windows Defender / antivirus**: Unsigned .exe files may trigger antivirus warnings. This is a known issue with PyInstaller. Friends may need to whitelist the app. Consider code signing in the future if this becomes a problem.
- **Thread safety**: The polling thread and the tray icon run on separate threads. Access to `uploaded_hashes` set and the retry queue should be protected with a `threading.Lock`.
- **Graceful shutdown**: When the user clicks "Exit", the polling thread should be stopped cleanly (set a `threading.Event` and join the thread).

## Success Metrics

- A non-technical friend can install and start using the app in under 2 minutes
- After initial setup, the app runs invisibly with no user action required
- New games are uploaded within 60 seconds of match completion
- App successfully catches up on all missed games after being offline
- .exe file size is under 25 MB

## Open Questions

- Should the app show a tray notification with rating changes after upload? This requires the server to return rating deltas in the upload response (see PRD 2 Open Questions). Could be a nice touch but adds complexity.
- Should we support multiple savegame folders (for players with multiple Steam accounts on the same PC)? Probably not worth the complexity for the initial version.
- What icon should we use for the tray? A custom AoE2-themed icon would be ideal. For MVP, we can use a simple colored circle or a generic file upload icon.
