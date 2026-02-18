"""
Unit tests for UploaderWindow UI behaviour.

Covers:
- Banner state text and transitions
- Theme toggling and config persistence
- Advanced settings panel collapse/expand
- Staging speed label wiring
"""

import json
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, Qt

from src.state_manager import StateManager
from src.stats_tracker import StatsTracker
from src.uploader import UploaderWindow, _BANNER_TEXT, apply_stylesheet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_patched_init(config_path: Path, staging_dir: Path):
    """Return a patched __init__ that uses temp config / staging paths."""
    from PySide6.QtWidgets import QMainWindow

    def patched_init(self):
        QMainWindow.__init__(self)
        self.setWindowTitle("DFN Image Uploader")
        self.setMinimumSize(1000, 820)

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

        apply_stylesheet(self, self._dark_mode)
        self.set_banner_state("READY")

        # Timers exist but are NOT started
        self.sd_check_timer = QTimer()
        self.sd_check_timer.timeout.connect(self.check_sd_cards)
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_display_stats)

        self.refresh_sd_list()
        self.update_counts()

    return patched_init


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset StateManager singleton between tests."""
    StateManager._instance = None
    yield
    StateManager._instance = None


@pytest.fixture
def ui_window(qtbot, tmp_path, monkeypatch):
    """Provide a fully patched UploaderWindow for UI-only testing."""
    # Temp config
    config_path = tmp_path / "config.json"
    config_data = {
        "upload_key": "test-key",
        "staging_dir": str(tmp_path / "staging"),
        "concurrency_mode": "auto",
        "concurrency_value": 3,
        "dark_mode": True,
    }
    (tmp_path / "staging").mkdir()
    config_path.write_text(json.dumps(config_data))

    # Temp state DB
    db_path = tmp_path / "test_state.db"

    def _mock_sm_init(self):
        if not hasattr(self, "initialized"):
            self.db_path = db_path
            self.conn_lock = threading.Lock()
            self._init_db()
            self.initialized = True

    monkeypatch.setattr(StateManager, "__init__", _mock_sm_init)

    # Patch SD monitor
    from src import sd_monitor as sd_mod

    monkeypatch.setattr(sd_mod.SDMonitor, "_get_removable_devices", lambda self: [])
    monkeypatch.setattr(sd_mod.SDMonitor, "get_sd_cards", lambda self: [])
    monkeypatch.setattr(
        sd_mod.SDMonitor,
        "check_for_changes",
        lambda self: {"added": [], "removed": []},
    )

    # Suppress dialogs
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: QMessageBox.StandardButton.Ok)

    monkeypatch.setattr(
        UploaderWindow,
        "__init__",
        _make_patched_init(config_path, tmp_path / "staging"),
    )

    window = UploaderWindow()
    qtbot.addWidget(window)
    window.show()

    yield window

    window.close()


# ---------------------------------------------------------------------------
# Banner state tests
# ---------------------------------------------------------------------------


class TestBannerState:
    """Test the top status banner."""

    def test_set_banner_state_updates_text(self, ui_window):
        """set_banner_state('UPLOADING') puts the correct text on the banner."""
        ui_window.set_banner_state("UPLOADING")
        assert _BANNER_TEXT["UPLOADING"] in ui_window.status_banner.text()

    @pytest.mark.parametrize("state", list(_BANNER_TEXT.keys()))
    def test_set_banner_state_all_states(self, ui_window, state):
        """Every valid banner state produces a non-empty, expected label."""
        ui_window.set_banner_state(state)
        text = ui_window.status_banner.text()
        assert text, f"Banner text is empty for state {state}"
        assert text == _BANNER_TEXT[state]

    def test_banner_states_are_distinct(self, ui_window):
        """Each state produces a unique banner message."""
        texts = set()
        for state in _BANNER_TEXT:
            ui_window.set_banner_state(state)
            texts.add(ui_window.status_banner.text())
        assert len(texts) == len(_BANNER_TEXT)


# ---------------------------------------------------------------------------
# Theme toggle tests
# ---------------------------------------------------------------------------


class TestThemeToggle:
    """Test dark/light theme switching and persistence."""

    def test_theme_toggle_flips_mode(self, ui_window):
        """toggle_theme() flips _dark_mode back and forth."""
        assert ui_window._dark_mode is True
        ui_window.toggle_theme()
        assert ui_window._dark_mode is False
        ui_window.toggle_theme()
        assert ui_window._dark_mode is True

    def test_theme_toggle_persists_to_config(self, ui_window):
        """Toggling theme writes dark_mode to config.json."""
        ui_window.toggle_theme()  # now light
        with open(ui_window.config_file) as f:
            cfg = json.load(f)
        assert cfg["dark_mode"] is False

        ui_window.toggle_theme()  # back to dark
        with open(ui_window.config_file) as f:
            cfg = json.load(f)
        assert cfg["dark_mode"] is True

    def test_theme_toggle_updates_button_text(self, ui_window):
        """Button text changes to indicate the opposite mode."""
        # Dark mode → button says "Light Mode"
        assert "Light" in ui_window.theme_toggle_btn.text()
        ui_window.toggle_theme()
        assert "Dark" in ui_window.theme_toggle_btn.text()
        ui_window.toggle_theme()
        assert "Light" in ui_window.theme_toggle_btn.text()


# ---------------------------------------------------------------------------
# Advanced panel tests
# ---------------------------------------------------------------------------


class TestAdvancedPanel:
    """Test the collapsible advanced settings panel."""

    def test_advanced_panel_hidden_by_default(self, ui_window):
        """The advanced settings group is not visible on startup."""
        assert ui_window.advanced_group.isVisible() is False

    def test_advanced_panel_toggle(self, qtbot, ui_window):
        """Clicking the toggle button shows/hides the advanced panel."""
        assert not ui_window.advanced_group.isVisible()

        # Show
        qtbot.mouseClick(ui_window.advanced_toggle_btn, Qt.MouseButton.LeftButton)
        assert ui_window.advanced_group.isVisible()
        assert "Hide" in ui_window.advanced_toggle_btn.text()

        # Hide
        qtbot.mouseClick(ui_window.advanced_toggle_btn, Qt.MouseButton.LeftButton)
        assert not ui_window.advanced_group.isVisible()
        assert "Show" in ui_window.advanced_toggle_btn.text()


# ---------------------------------------------------------------------------
# Staging speed label tests
# ---------------------------------------------------------------------------


class TestStagingSpeedLabel:
    """Test that on_staging_speed wires to the visible label."""

    def test_staging_speed_label_wired(self, ui_window):
        """on_staging_speed(bytes) updates the staging_speed_label."""
        ui_window.on_staging_speed(1_048_576)  # 1 MB/s
        text = ui_window.staging_speed_label.text()
        assert text  # non-empty
        # Should contain a rate unit
        assert "B/s" in text

    def test_staging_speed_label_shows_rate(self, ui_window):
        """A large speed value produces a human-readable string."""
        ui_window.on_staging_speed(52_428_800)  # 50 MB/s
        text = ui_window.staging_speed_label.text()
        assert "MB/s" in text
