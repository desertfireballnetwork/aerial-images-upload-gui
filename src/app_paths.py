"""Application path helpers for logging and bundled assets."""

import os
import sys
from pathlib import Path


def project_root() -> Path:
    """Repo root when running from source; PyInstaller extract dir when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def resolve_icon_path() -> Path | None:
    """Return the best available window icon path, or None if not bundled."""
    base = project_root()
    for name in ("icon.ico", "icon.png"):
        path = base / name
        if path.is_file():
            return path
    return None


def log_file_path() -> Path:
    """File log destination: AppData on Windows, CWD logs/ elsewhere."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        log_dir = Path(appdata) / "DFN" if appdata else Path.home() / "DFN"
    else:
        log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "uploader.log"
