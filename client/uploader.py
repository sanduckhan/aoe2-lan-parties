"""AoE2 Uploader — system tray daemon that watches for new replay files and uploads them."""

import hashlib
import json
import logging
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

import requests
from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

# ---------------------------------------------------------------------------
# Constants (baked in at build time)
# ---------------------------------------------------------------------------

SERVER_URL = "https://your-railway-app.up.railway.app"  # Updated at build time
API_KEY = "your-api-key-here"  # Updated at build time
POLL_INTERVAL = 30  # seconds
STABLE_WAIT = 10  # seconds to wait for file size stabilization
RETRY_INTERVAL = 60  # seconds between retries
MAX_RETRIES = 10
CATCH_UP_DELAY = 2  # seconds between catch-up uploads

APP_NAME = "AoE2 Uploader"
APPDATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "AoE2Uploader"
CONFIG_PATH = APPDATA_DIR / "config.json"
HASHES_PATH = APPDATA_DIR / "uploaded_hashes.json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log_lock = threading.Lock()
log_entries: list = []
log_callback = None  # set when log window is open

logger = logging.getLogger(APP_NAME)
logger.setLevel(logging.INFO)


class InMemoryHandler(logging.Handler):
    def emit(self, record):
        entry = self.format(record)
        with log_lock:
            log_entries.append(entry)
            if len(log_entries) > 500:
                log_entries.pop(0)
        if log_callback:
            try:
                log_callback(entry)
            except Exception:
                pass


handler = InMemoryHandler()
handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(handler)

# ---------------------------------------------------------------------------
# Persistent state helpers
# ---------------------------------------------------------------------------


def _ensure_appdata():
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    _ensure_appdata()
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(cfg: dict):
    _ensure_appdata()
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def load_hashes() -> set:
    _ensure_appdata()
    if HASHES_PATH.exists():
        try:
            return set(json.loads(HASHES_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def save_hashes(hashes: set):
    _ensure_appdata()
    HASHES_PATH.write_text(json.dumps(sorted(hashes)), encoding="utf-8")


# ---------------------------------------------------------------------------
# Savegame folder auto-detection
# ---------------------------------------------------------------------------

AOE2_BASE = Path.home() / "Games" / "Age of Empires 2 DE"


def detect_savegame_folders() -> list:
    """Return list of savegame folder paths found under the AoE2 DE directory."""
    folders = []
    if not AOE2_BASE.exists():
        return folders
    for entry in AOE2_BASE.iterdir():
        if entry.is_dir() and entry.name.isdigit():
            sg = entry / "savegame"
            if sg.is_dir():
                folders.append(str(sg))
    return folders


def auto_detect_or_pick() -> str | None:
    """Auto-detect the savegame folder. Show a picker if multiple found, or a
    manual browse dialog if none found. Returns the chosen path or None."""
    folders = detect_savegame_folders()
    if len(folders) == 1:
        return folders[0]
    if len(folders) > 1:
        # Simple picker using tkinter
        root = tk.Tk()
        root.title(f"{APP_NAME} — Select savegame folder")
        root.geometry("420x300")
        root.resizable(False, False)
        chosen = [None]

        tk.Label(root, text="Multiple savegame folders found.\nSelect one:").pack(
            pady=10
        )
        lb = tk.Listbox(root, selectmode=tk.SINGLE, width=60)
        for f in folders:
            lb.insert(tk.END, f)
        lb.pack(padx=10, pady=5)

        def on_ok():
            sel = lb.curselection()
            if sel:
                chosen[0] = folders[sel[0]]
            root.destroy()

        tk.Button(root, text="OK", command=on_ok).pack(pady=10)
        root.mainloop()
        return chosen[0]

    # None found — ask user to browse
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(
        APP_NAME,
        "Could not auto-detect your AoE2 DE savegame folder.\n"
        "Please select it manually in the next dialog.",
    )
    path = filedialog.askdirectory(title="Select AoE2 DE savegame folder")
    root.destroy()
    return path or None


# ---------------------------------------------------------------------------
# Upload logic
# ---------------------------------------------------------------------------


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_replay(file_path: str, file_hash: str) -> tuple:
    """Upload a replay file. Returns (status_code, response_json | None)."""
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{SERVER_URL}/api/upload",
            files={"file": (os.path.basename(file_path), f)},
            data={"sha256": file_hash},
            headers={"X-API-Key": API_KEY},
            timeout=60,
        )
    try:
        body = resp.json()
    except Exception:
        body = None
    return resp.status_code, body


def file_is_stable(path: str) -> bool:
    """Wait up to STABLE_WAIT seconds for the file size to stop changing."""
    try:
        prev_size = os.path.getsize(path)
    except OSError:
        return False
    time.sleep(STABLE_WAIT)
    try:
        curr_size = os.path.getsize(path)
    except OSError:
        return False
    return prev_size == curr_size


# ---------------------------------------------------------------------------
# Tray icon helpers
# ---------------------------------------------------------------------------

_STATUS_COLORS = {"ok": "green", "uploading": "gold", "error": "red"}


def _make_icon_image(color: str = "green") -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


# ---------------------------------------------------------------------------
# Core watcher / uploader daemon
# ---------------------------------------------------------------------------


class UploaderDaemon:
    def __init__(self, savegame_path: str):
        self.savegame_path = savegame_path
        self.uploaded: set = load_hashes()
        self.lock = threading.Lock()
        self.retry_queue: list = []  # list of (path, hash, attempts)
        self.paused = False
        self.stop_event = threading.Event()
        self.icon: Icon | None = None
        self._status = "ok"
        self._known_files: set = set()

    # --- status / icon ---

    def _set_status(self, status: str):
        self._status = status
        if self.icon:
            self.icon.icon = _make_icon_image(_STATUS_COLORS.get(status, "green"))

    # --- hash persistence ---

    def _mark_uploaded(self, file_hash: str):
        with self.lock:
            self.uploaded.add(file_hash)
            save_hashes(self.uploaded)

    def _is_uploaded(self, file_hash: str) -> bool:
        with self.lock:
            return file_hash in self.uploaded

    # --- single upload attempt ---

    def _try_upload(self, path: str, file_hash: str) -> bool:
        """Attempt upload. Returns True if done (success or dup), False on failure."""
        name = os.path.basename(path)
        size_kb = os.path.getsize(path) / 1024
        self._set_status("uploading")
        try:
            code, body = upload_replay(path, file_hash)
        except Exception as exc:
            logger.info("FAIL   %s (%.0f KB) — %s", name, size_kb, exc)
            self._set_status("error")
            return False

        if code == 200:
            logger.info("OK     %s (%.0f KB)", name, size_kb)
            self._mark_uploaded(file_hash)
            self._notify(f"Game uploaded: {name}")
            self._set_status("ok")
            return True
        if code == 409:
            logger.info("DUP    %s", name)
            self._mark_uploaded(file_hash)
            self._set_status("ok")
            return True

        msg = body.get("error", "") if body else f"HTTP {code}"
        logger.info("FAIL   %s — %s", name, msg)
        self._set_status("error")
        return False

    def _notify(self, message: str):
        if self.icon:
            try:
                self.icon.notify(message, APP_NAME)
            except Exception:
                pass

    # --- scan & poll ---

    def _scan_folder(self) -> list:
        """Return list of .aoe2record file paths in the savegame folder."""
        try:
            return sorted(str(p) for p in Path(self.savegame_path).glob("*.aoe2record"))
        except OSError:
            return []

    def _process_file(self, path: str) -> bool:
        """Process a single file. Returns True if upload succeeded/dup."""
        file_hash = sha256_file(path)
        if self._is_uploaded(file_hash):
            return True
        return self._try_upload(path, file_hash)

    def _catch_up(self):
        """Upload any un-uploaded replays found at startup."""
        files = self._scan_folder()
        pending = []
        for path in files:
            file_hash = sha256_file(path)
            if not self._is_uploaded(file_hash):
                pending.append((path, file_hash))

        if not pending:
            logger.info("Catch-up: no new files")
            return

        logger.info("Catch-up: %d file(s) to upload", len(pending))
        for i, (path, file_hash) in enumerate(pending, 1):
            if self.stop_event.is_set():
                break
            logger.info("Catch-up %d/%d ...", i, len(pending))
            if not self._try_upload(path, file_hash):
                with self.lock:
                    self.retry_queue.append((path, file_hash, 0))
            time.sleep(CATCH_UP_DELAY)

    def _poll_loop(self):
        """Main polling loop — detect new files and retry failures."""
        # Initial scan to populate known files
        self._known_files = set(self._scan_folder())
        self._catch_up()

        last_retry = time.time()

        while not self.stop_event.is_set():
            self.stop_event.wait(POLL_INTERVAL)
            if self.stop_event.is_set():
                break
            if self.paused:
                continue

            # Check for new files
            current_files = set(self._scan_folder())
            new_files = current_files - self._known_files
            self._known_files = current_files

            for path in sorted(new_files):
                if self.stop_event.is_set():
                    break
                logger.info(
                    "NEW    %s — waiting for write to finish...", os.path.basename(path)
                )
                if not file_is_stable(path):
                    logger.info(
                        "SKIP   %s — file still changing", os.path.basename(path)
                    )
                    self._known_files.discard(path)
                    continue
                if not self._process_file(path):
                    file_hash = sha256_file(path)
                    with self.lock:
                        self.retry_queue.append((path, file_hash, 0))

            # Retry queue
            now = time.time()
            if now - last_retry >= RETRY_INTERVAL:
                last_retry = now
                self._process_retries()

    def _process_retries(self):
        with self.lock:
            queue = list(self.retry_queue)
            self.retry_queue.clear()

        still_pending = []
        for path, file_hash, attempts in queue:
            if self.stop_event.is_set():
                still_pending.append((path, file_hash, attempts))
                continue
            if self._is_uploaded(file_hash):
                continue
            attempts += 1
            if attempts > MAX_RETRIES:
                logger.info(
                    "GIVE UP  %s after %d retries", os.path.basename(path), MAX_RETRIES
                )
                continue
            logger.info(
                "RETRY  %s (attempt %d/%d)",
                os.path.basename(path),
                attempts,
                MAX_RETRIES,
            )
            if not self._try_upload(path, file_hash):
                still_pending.append((path, file_hash, attempts))

        with self.lock:
            self.retry_queue.extend(still_pending)

        if still_pending:
            self._set_status("error")
        elif self._status == "error":
            self._set_status("ok")

    # --- tray menu actions ---

    def toggle_pause(self, icon, item):
        self.paused = not self.paused
        state = "paused" if self.paused else "resumed"
        logger.info("Watcher %s", state)

    def open_log_window(self, icon=None, item=None):
        threading.Thread(target=self._show_log_window, daemon=True).start()

    def _show_log_window(self):
        global log_callback
        win = tk.Tk()
        win.title(f"{APP_NAME} — Log")
        win.geometry("650x400")

        text = scrolledtext.ScrolledText(
            win, state="disabled", wrap=tk.WORD, font=("Consolas", 9)
        )
        text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Populate with existing entries
        with log_lock:
            for entry in log_entries:
                text.configure(state="normal")
                text.insert(tk.END, entry + "\n")
                text.configure(state="disabled")
        text.see(tk.END)

        def on_new_entry(entry):
            try:
                win.after(0, _append, entry)
            except Exception:
                pass

        def _append(entry):
            text.configure(state="normal")
            text.insert(tk.END, entry + "\n")
            text.configure(state="disabled")
            text.see(tk.END)

        log_callback = on_new_entry

        def on_close():
            global log_callback
            log_callback = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        win.mainloop()

    def open_settings(self, icon=None, item=None):
        threading.Thread(target=self._show_settings_window, daemon=True).start()

    def _show_settings_window(self):
        win = tk.Tk()
        win.title(f"{APP_NAME} — Settings")
        win.geometry("500x180")
        win.resizable(False, False)

        cfg = load_config()

        tk.Label(win, text="Savegame folder:").grid(
            row=0, column=0, padx=10, pady=10, sticky="w"
        )
        path_var = tk.StringVar(value=self.savegame_path)
        tk.Entry(win, textvariable=path_var, width=45).grid(
            row=0, column=1, padx=5, pady=10
        )

        def browse():
            p = filedialog.askdirectory(title="Select savegame folder")
            if p:
                path_var.set(p)

        tk.Button(win, text="Browse", command=browse).grid(
            row=0, column=2, padx=5, pady=10
        )

        auto_start_var = tk.BooleanVar(value=cfg.get("auto_start", True))
        tk.Checkbutton(win, text="Start with Windows", variable=auto_start_var).grid(
            row=1, column=0, columnspan=3, padx=10, sticky="w"
        )

        def on_save():
            new_path = path_var.get().strip()
            if new_path and Path(new_path).is_dir():
                self.savegame_path = new_path
                cfg["savegame_path"] = new_path
            cfg["auto_start"] = auto_start_var.get()
            save_config(cfg)
            if auto_start_var.get():
                _create_startup_shortcut()
            else:
                _remove_startup_shortcut()
            logger.info("Settings saved")
            win.destroy()

        tk.Button(win, text="Save", command=on_save).grid(row=2, column=1, pady=15)
        win.mainloop()

    def quit_app(self, icon, item):
        with self.lock:
            pending = len(self.retry_queue)
        if pending:
            # Can't show tk dialog from tray thread reliably, just log and quit
            logger.info("Exiting with %d pending retries", pending)
        self.stop_event.set()
        if self.icon:
            self.icon.stop()

    # --- main entry ---

    def run(self):
        logger.info("Watching: %s", self.savegame_path)
        logger.info("Server:   %s", SERVER_URL)

        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()

        menu = Menu(
            MenuItem("Show Log", self.open_log_window, default=True),
            MenuItem(
                lambda item: "Resume" if self.paused else "Pause",
                self.toggle_pause,
            ),
            MenuItem("Settings", self.open_settings),
            MenuItem("Exit", self.quit_app),
        )

        self.icon = Icon(APP_NAME, _make_icon_image("green"), APP_NAME, menu)
        self.icon.run()

        # Icon stopped — clean up
        self.stop_event.set()
        poll_thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Windows auto-start helpers
# ---------------------------------------------------------------------------

STARTUP_DIR = (
    Path(os.environ.get("APPDATA", ""))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
)


def _get_exe_path() -> str:
    """Return the path to the current executable."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


def _shortcut_path() -> Path:
    return STARTUP_DIR / f"{APP_NAME}.lnk"


def _create_startup_shortcut():
    """Create a Windows startup shortcut. Uses PowerShell as a portable approach."""
    try:
        import subprocess

        target = _get_exe_path()
        link = str(_shortcut_path())
        ps_script = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f'$sc = $ws.CreateShortcut("{link}"); '
            f'$sc.TargetPath = "{target}"; '
            f"$sc.Save()"
        )
        subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            timeout=10,
        )
        logger.info("Auto-start shortcut created")
    except Exception as exc:
        logger.info("Could not create startup shortcut: %s", exc)


def _remove_startup_shortcut():
    """Remove the Windows startup shortcut if it exists."""
    try:
        link = _shortcut_path()
        if link.exists():
            link.unlink()
            logger.info("Auto-start shortcut removed")
    except Exception as exc:
        logger.info("Could not remove startup shortcut: %s", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    cfg = load_config()
    savegame_path = cfg.get("savegame_path")

    if not savegame_path or not Path(savegame_path).is_dir():
        savegame_path = auto_detect_or_pick()
        if not savegame_path:
            # Create a root window for the error dialog
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(APP_NAME, "No savegame folder selected. Exiting.")
            root.destroy()
            sys.exit(1)
        cfg["savegame_path"] = savegame_path
        cfg.setdefault("auto_start", True)
        save_config(cfg)

    # Set up auto-start on first run
    if cfg.get("auto_start", True):
        _create_startup_shortcut()

    daemon = UploaderDaemon(savegame_path)
    daemon.run()


if __name__ == "__main__":
    main()
