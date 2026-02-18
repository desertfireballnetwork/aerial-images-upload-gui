"""
Shared fixtures for integration tests.

Provides:
- Mock SD card with EXIF-tagged JPEG images
- Temporary staging directory and SQLite state DB
- UploaderWindow wired to temp paths (no real hardware/network)
- aioresponses helpers that mirror the real DFN webapp contract
- Pre-staged image helper for upload-only tests

NOTE: We use qtbot.waitUntil() (polling) rather than qtbot.waitSignal()
for signals emitted from QThread, because PySide6 cross-thread signal
delivery into a nested QEventLoop can cause segfaults.
"""

import json
import uuid
import time
import threading
from pathlib import Path
from typing import List, Dict
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image
from PySide6.QtWidgets import QMessageBox, QApplication
from PySide6.QtCore import Qt

from src.state_manager import StateManager
from src.sd_monitor import SDCardInfo
from src.stats_tracker import StatsTracker
from src.upload_manager import UploadManager


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://find.gfo.rocks"
CHECK_URL = f"{BASE_URL}/survey/upload/check/"
UPLOAD_URL = f"{BASE_URL}/survey/upload/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exif_bytes(datetime_str: str = "2025:06:15 10:30:00") -> bytes:
    """Build minimal EXIF bytes containing DateTimeOriginal."""
    try:
        import piexif

        exif_dict = {"Exif": {piexif.ExifIFD.DateTimeOriginal: datetime_str.encode("ascii")}}
        return piexif.dump(exif_dict)
    except ImportError:
        return b""


def create_test_jpeg(
    path: Path,
    colour: str = "blue",
    exif_datetime: str | None = "2025:06:15 10:30:00",
) -> Path:
    """Create a small valid JPEG with optional EXIF DateTimeOriginal."""
    img = Image.new("RGB", (100, 100), color=colour)
    if exif_datetime:
        exif_bytes = _make_exif_bytes(exif_datetime)
        if exif_bytes:
            img.save(path, "JPEG", exif=exif_bytes)
            return path
    img.save(path, "JPEG")
    return path


def wait_for_thread_done(qtbot, thread_getter, timeout=30_000):
    """
    Poll until the QThread referenced by *thread_getter()* is no longer running.
    Uses qtbot.waitUntil which processes Qt events between polls.
    """

    def _check():
        t = thread_getter()
        assert t is None or not t.isRunning()

    qtbot.waitUntil(_check, timeout=timeout)


def process_events():
    """Process pending Qt events."""
    app = QApplication.instance()
    if app:
        app.processEvents()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def zero_retry_delay(monkeypatch):
    """Zero upload back-off for every integration test so retries are instant."""
    monkeypatch.setattr(UploadManager, "RETRY_BASE_DELAY", 0.0)


@pytest.fixture
def upload_key() -> str:
    """A fixed upload key (UUID) used across all integration tests."""
    return "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


@pytest.fixture
def integration_state_manager(tmp_path, monkeypatch):
    """StateManager backed by a temp SQLite file."""
    StateManager._instance = None
    db_path = tmp_path / "integration_state.db"

    def _mock_init(self):
        if not hasattr(self, "initialized"):
            self.db_path = db_path
            self.conn_lock = threading.Lock()
            self._init_db()
            self.initialized = True

    monkeypatch.setattr(StateManager, "__init__", _mock_init)
    manager = StateManager()
    yield manager
    StateManager._instance = None


@pytest.fixture
def staging_dir(tmp_path) -> Path:
    """Empty staging directory."""
    d = tmp_path / "staging"
    d.mkdir()
    return d


@pytest.fixture
def sd_card(tmp_path) -> Path:
    """Mock SD card with 5 EXIF-tagged JPEGs."""
    sd = tmp_path / "sd_card" / "DCIM"
    sd.mkdir(parents=True)
    for i in range(5):
        ts = f"2025:06:15 10:{30 + i:02d}:00"
        create_test_jpeg(sd / f"IMG_{i:04d}.jpg", exif_datetime=ts)
    return sd.parent


@pytest.fixture
def large_sd_card(tmp_path) -> Path:
    """Mock SD card with 15 images."""
    sd = tmp_path / "sd_card_large" / "DCIM"
    sd.mkdir(parents=True)
    for i in range(15):
        ts = f"2025:06:15 10:{i:02d}:00"
        create_test_jpeg(sd / f"IMG_{i:04d}.jpg", exif_datetime=ts)
    return sd.parent


@pytest.fixture
def mock_sd_card_info(sd_card):
    """SDCardInfo pointing at the mock sd_card."""
    return SDCardInfo(
        path=str(sd_card),
        device="/dev/sdx1",
        total_bytes=32 * 1024**3,
        free_bytes=16 * 1024**3,
    )


@pytest.fixture
def mock_large_sd_card_info(large_sd_card):
    return SDCardInfo(
        path=str(large_sd_card),
        device="/dev/sdx1",
        total_bytes=64 * 1024**3,
        free_bytes=32 * 1024**3,
    )


def _pre_stage_images(
    state_manager: StateManager,
    staging_dir: Path,
    n: int = 5,
    image_type: str = "survey",
) -> List[Dict]:
    """Create N staged images directly in DB + on disk."""
    images = []
    for i in range(n):
        fname = f"IMG_{i:04d}.jpg"
        fpath = staging_dir / fname
        create_test_jpeg(fpath, colour="green", exif_datetime=f"2025:06:15 10:{30 + i:02d}:00")
        file_size = fpath.stat().st_size
        image_id = state_manager.add_image(
            filename=fname,
            staging_path=str(fpath),
            image_type=image_type,
            exif_timestamp=f"2025-06-15T10:{30 + i:02d}:00",
            file_size=file_size,
        )
        images.append(
            {
                "id": image_id,
                "filename": fname,
                "staging_path": str(fpath),
                "image_type": image_type,
                "file_size": file_size,
            }
        )
    return images


@pytest.fixture
def pre_staged_images(integration_state_manager, staging_dir):
    """5 images already staged (DB + disk)."""
    return _pre_stage_images(integration_state_manager, staging_dir, n=5)


@pytest.fixture
def pre_staged_images_15(integration_state_manager, staging_dir):
    """15 images already staged (DB + disk)."""
    return _pre_stage_images(integration_state_manager, staging_dir, n=15)


@pytest.fixture
def app_window(
    qtbot,
    tmp_path,
    upload_key,
    integration_state_manager,
    staging_dir,
    monkeypatch,
):
    """
    Fully wired UploaderWindow using temp paths and mock SDMonitor.
    QMessageBox dialogs are auto-accepted. Timers are disabled.
    """
    config_path = tmp_path / "config.json"
    config_data = {
        "upload_key": upload_key,
        "staging_dir": str(staging_dir),
        "concurrency_mode": "auto",
        "concurrency_value": 3,
    }
    config_path.write_text(json.dumps(config_data))

    # Patch SDMonitor
    from src import sd_monitor as sd_mod

    monkeypatch.setattr(sd_mod.SDMonitor, "_get_removable_devices", lambda self: [])
    monkeypatch.setattr(sd_mod.SDMonitor, "get_sd_cards", lambda self: [])
    monkeypatch.setattr(
        sd_mod.SDMonitor,
        "check_for_changes",
        lambda self: {"added": [], "removed": []},
    )

    # Auto-accept all dialogs
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: QMessageBox.StandardButton.Ok)

    from src.uploader import UploaderWindow

    monkeypatch.setattr(UploaderWindow, "__init__", _make_patched_init(config_path, staging_dir))

    window = UploaderWindow()
    qtbot.addWidget(window)
    window.show()
    process_events()

    yield window

    # --- Cleanup: stop any running threads before Qt destroys the window ---
    if window.staging_thread and window.staging_thread.isRunning():
        window.staging_thread.stop()
        window.staging_thread.wait(5000)

    if window.upload_thread and window.upload_thread.isRunning():
        window.upload_thread.stop()
        window.upload_thread.wait(5000)

    window.close()
    process_events()


def _make_patched_init(config_path: Path, staging_dir: Path):
    """Return a patched __init__ that uses our temp config path."""
    from PySide6.QtWidgets import QMainWindow
    from PySide6.QtCore import QTimer

    def patched_init(self):
        QMainWindow.__init__(self)
        self.setWindowTitle("DFN Image Uploader")
        self.setMinimumSize(860, 620)

        self.state_manager = StateManager()
        from src.sd_monitor import SDMonitor

        self.sd_monitor = SDMonitor()
        self.stats_tracker = StatsTracker()
        self.staging_thread = None
        self.upload_thread = None
        self._dark_mode = True

        self.config_file = config_path
        self.load_config()

        self._dark_mode = self.config.get("dark_mode", True)

        self.setup_ui()

        from src.uploader import apply_stylesheet

        apply_stylesheet(self, self._dark_mode)
        self.set_banner_state("READY")

        # Timers exist but are NOT started (tests trigger updates manually)
        self.sd_check_timer = QTimer()
        self.sd_check_timer.timeout.connect(self.check_sd_cards)

        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_display_stats)

        self.refresh_sd_list()
        self.update_counts()

    return patched_init
