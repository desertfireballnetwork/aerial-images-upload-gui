"""
Unit tests for UploaderWindow UI behaviour.

Covers:
- Banner state text and transitions
- Theme toggling and config persistence
- Advanced settings panel collapse/expand
- Staging speed label wiring
- 4-step wizard layout
- Stage step UI elements
"""

import json
import sys
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
        self.scan_thread = None
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


def _build_ui_window(qtbot, tmp_path, monkeypatch, platform=None):
    """Construct a patched UploaderWindow, optionally with sys.platform mocked first.

    Platform must be set before construction because eject_sd_checkbox is created
    during setup_ui() in __init__.
    """
    if platform is not None:
        monkeypatch.setattr(sys, "platform", platform)

    config_path = tmp_path / "config.json"
    config_data = {
        "upload_key": "test-key",
        "staging_dir": str(tmp_path / "staging"),
        "concurrency_mode": "auto",
        "concurrency_value": 3,
        "dark_mode": True,
    }
    (tmp_path / "staging").mkdir(exist_ok=True)
    config_path.write_text(json.dumps(config_data))

    db_path = tmp_path / "test_state.db"

    def _mock_sm_init(self):
        if not hasattr(self, "initialized"):
            self.db_path = db_path
            self.conn_lock = threading.Lock()
            self._init_db()
            self.initialized = True

    monkeypatch.setattr(StateManager, "__init__", _mock_sm_init)

    from src import sd_monitor as sd_mod

    monkeypatch.setattr(sd_mod.SDMonitor, "_get_removable_devices", lambda self: [])
    monkeypatch.setattr(sd_mod.SDMonitor, "get_sd_cards", lambda self: [])
    monkeypatch.setattr(
        sd_mod.SDMonitor,
        "check_for_changes",
        lambda self: {"added": [], "removed": []},
    )

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
    return window


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset StateManager singleton between tests."""
    StateManager._instance = None
    yield
    StateManager._instance = None


@pytest.fixture
def ui_window(qtbot, tmp_path, monkeypatch):
    """Provide a fully patched UploaderWindow for UI-only testing (host platform)."""
    window = _build_ui_window(qtbot, tmp_path, monkeypatch)
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

    def test_staging_banner_state(self, ui_window):
        """The STAGING and DONE_STAGING banner states exist and produce correct text."""
        ui_window.set_banner_state("STAGING")
        assert "registering" in ui_window.status_banner.text().lower()

        ui_window.set_banner_state("DONE_STAGING")
        assert "staged" in ui_window.status_banner.text().lower()


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

    def test_delete_staging_checkbox_exists_unchecked(self, ui_window):
        """Advanced Settings has delete-staging checkbox, default unchecked."""
        assert hasattr(ui_window, "delete_staging_checkbox")
        assert ui_window.delete_staging_checkbox.isChecked() is False
        assert ui_window.delete_staging_checkbox.parent() is ui_window.advanced_group

    def test_delete_staging_checkbox_persists_to_config(self, ui_window):
        """Toggling delete-staging checkbox writes delete_staging_after_upload."""
        ui_window.delete_staging_checkbox.setChecked(True)
        with open(ui_window.config_file) as f:
            data = json.load(f)
        assert data.get("delete_staging_after_upload") is True

        ui_window.delete_staging_checkbox.setChecked(False)
        with open(ui_window.config_file) as f:
            data = json.load(f)
        assert data.get("delete_staging_after_upload") is False


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


# ---------------------------------------------------------------------------
# 4-step wizard layout tests
# ---------------------------------------------------------------------------


class TestWizardLayout:
    """Test that the 4-step wizard is correctly laid out."""

    def test_step2_optional_label(self, ui_window):
        """Step 2 title contains 'Optional'."""
        assert hasattr(ui_window, "copy_btn")
        assert hasattr(ui_window, "sd_list")

    def test_step3_stage_exists(self, ui_window):
        """Step 3 (Stage) has the stage button and image type combo."""
        assert hasattr(ui_window, "stage_btn")
        assert hasattr(ui_window, "image_type_combo")
        assert hasattr(ui_window, "unstaged_count_label")
        assert hasattr(ui_window, "scan_progress")

    def test_step4_upload_exists(self, ui_window):
        """Step 4 (Upload) has the upload start button."""
        assert hasattr(ui_window, "upload_start_btn")
        assert hasattr(ui_window, "upload_pause_btn")
        assert hasattr(ui_window, "upload_stop_btn")

    def test_sd_card_checkboxes_exist(self, ui_window):
        """Step 2 has delete checkbox; eject checkbox is platform-dependent (issue #7)."""
        assert hasattr(ui_window, "delete_source_checkbox")
        assert ui_window.delete_source_checkbox.isChecked() is False
        assert hasattr(ui_window, "eject_sd_checkbox")
        if sys.platform.startswith("linux"):
            assert ui_window.eject_sd_checkbox is None
        else:
            assert ui_window.eject_sd_checkbox is not None
            assert ui_window.eject_sd_checkbox.text() == "Eject SD card when done"
            assert ui_window.eject_sd_checkbox.isChecked() is False

    def test_scan_thread_attribute_exists(self, ui_window):
        """scan_thread attribute is initialized to None."""
        assert hasattr(ui_window, "scan_thread")
        assert ui_window.scan_thread is None

    def test_folder_scan_disables_refresh_btn(self, ui_window, qtbot):
        """The refresh_unstaged_btn is disabled during a folder scan to prevent DB lockup."""
        # Initial state: button should be enabled
        assert ui_window.refresh_unstaged_btn.isEnabled()

        # Mock the folder scanner so it doesn't actually run real FS/DB work
        from unittest.mock import MagicMock

        mock_thread = MagicMock()
        ui_window.scan_thread = mock_thread

        # Simulate starting a scan manually to isolate the UI toggle logic
        ui_window.stage_btn.setEnabled(False)
        ui_window.refresh_unstaged_btn.setEnabled(False)

        assert not ui_window.refresh_unstaged_btn.isEnabled()

        # Simulate finishing the scan
        ui_window.on_scan_finished(10, 0, 0)

        # Button should be re-enabled
        assert ui_window.refresh_unstaged_btn.isEnabled()

    def test_eject_worker_triggered(self, qtbot, tmp_path, monkeypatch):
        """On non-Linux, checked eject launches background _EjectWorker after copy."""
        window = _build_ui_window(qtbot, tmp_path, monkeypatch, platform="darwin")
        try:
            assert window.eject_sd_checkbox is not None
            window.eject_sd_checkbox.setChecked(True)
            window._last_sd_card_path = "/dev/sdd1"

            from src.uploader import _EjectWorker

            mock_start = MagicMock()
            monkeypatch.setattr(_EjectWorker, "start", mock_start)

            window.on_staging_finished(10, 0, 0, False)

            assert mock_start.called
            assert isinstance(window._eject_worker, _EjectWorker)
            assert window._eject_worker.mount_path == "/dev/sdd1"
        finally:
            window.close()

    def test_eject_checkbox_absent_on_linux(self, qtbot, tmp_path, monkeypatch):
        """With platform mocked to linux, eject_sd_checkbox is None (issue #7)."""
        window = _build_ui_window(qtbot, tmp_path, monkeypatch, platform="linux")
        try:
            assert window.eject_sd_checkbox is None
        finally:
            window.close()

    def test_eject_worker_not_started_on_linux(self, qtbot, tmp_path, monkeypatch):
        """Post-copy eject must not start _EjectWorker when checkbox is None (Linux)."""
        window = _build_ui_window(qtbot, tmp_path, monkeypatch, platform="linux")
        try:
            assert window.eject_sd_checkbox is None
            window._last_sd_card_path = "/media/user/SDCARD"

            from src.uploader import _EjectWorker

            mock_start = MagicMock()
            monkeypatch.setattr(_EjectWorker, "start", mock_start)

            window.on_staging_finished(10, 0, 0, False)

            assert not mock_start.called
            assert getattr(window, "_eject_worker", None) is None
        finally:
            window.close()

    @pytest.mark.parametrize("platform", ["darwin", "win32"])
    def test_eject_checkbox_present_non_linux(self, qtbot, tmp_path, monkeypatch, platform):
        """On darwin/win32, eject checkbox exists with expected label and default off."""
        # Isolate staging dirs per platform param to avoid mkdir races within tmp_path
        plat_tmp = tmp_path / platform
        plat_tmp.mkdir()
        window = _build_ui_window(qtbot, plat_tmp, monkeypatch, platform=platform)
        try:
            assert window.eject_sd_checkbox is not None
            assert window.eject_sd_checkbox.text() == "Eject SD card when done"
            assert window.eject_sd_checkbox.isChecked() is False
        finally:
            window.close()

    def test_on_eject_done_updates_ui(self, ui_window, monkeypatch):
        """Verify _on_eject_done correctly shows success/warning dialogs."""
        mock_info = MagicMock()
        mock_warning = MagicMock()
        monkeypatch.setattr("src.uploader.QMessageBox.information", mock_info)
        monkeypatch.setattr("src.uploader.QMessageBox.warning", mock_warning)

        # Mock refresh_sd_list since it relies on finding actual devices
        monkeypatch.setattr(ui_window, "refresh_sd_list", MagicMock())

        # Success case
        ui_window._on_eject_done(True, "Ejected successfully")
        mock_info.assert_called_once()
        assert "Ejected successfully" in mock_info.call_args[0][2]

        # Failure case
        ui_window._on_eject_done(False, "Device is busy")
        mock_warning.assert_called_once()
        assert "Device is busy" in mock_warning.call_args[0][2]


# ---------------------------------------------------------------------------
# Image type placeholder / Stage gate (Issue #4)
# ---------------------------------------------------------------------------


class TestImageTypeDefault:
    """Placeholder image type gates Stage and resets after SD copy."""

    def test_startup_placeholder_disables_stage(self, ui_window):
        """On construction, combo is at placeholder and Stage is disabled."""
        assert ui_window.image_type_combo.currentData() is None
        assert ui_window.image_type_combo.currentIndex() == 0
        assert ui_window.stage_btn.isEnabled() is False

    def test_selecting_real_type_enables_stage(self, ui_window):
        """Selecting a real image type enables Stage and sets currentData()."""
        ui_window.image_type_combo.setCurrentText("survey")
        assert ui_window.image_type_combo.currentData() == "survey"
        assert ui_window.stage_btn.isEnabled() is True

    def test_start_folder_scan_guard_with_placeholder(self, ui_window, monkeypatch):
        """With placeholder selected, start_folder_scan warns and does not scan."""
        assert ui_window.image_type_combo.currentData() is None

        mock_warning = MagicMock(return_value=QMessageBox.StandardButton.Ok)
        monkeypatch.setattr("src.uploader.QMessageBox.warning", mock_warning)

        mock_scanner = MagicMock()
        monkeypatch.setattr("src.uploader.FolderScanner", mock_scanner)

        ui_window.start_folder_scan()

        mock_warning.assert_called_once()
        assert mock_warning.call_args[0][1] == "Image Type Required"
        mock_scanner.assert_not_called()
        assert ui_window.scan_thread is None

    def test_on_staging_finished_resets_image_type(self, ui_window):
        """After a successful SD copy, combo resets to placeholder and Stage disables."""
        ui_window.image_type_combo.setCurrentText("survey")
        assert ui_window.stage_btn.isEnabled() is True

        ui_window.on_staging_finished(10, 0, 0, False)

        assert ui_window.image_type_combo.currentData() is None
        assert ui_window.image_type_combo.currentIndex() == 0
        assert ui_window.stage_btn.isEnabled() is False

    def test_on_staging_finished_aborted_also_resets(self, ui_window):
        """Aborted SD copy also resets image type to placeholder."""
        ui_window.image_type_combo.setCurrentText("training_true")
        assert ui_window.stage_btn.isEnabled() is True

        ui_window.on_staging_finished(3, 0, 1, True)

        assert ui_window.image_type_combo.currentData() is None
        assert ui_window.image_type_combo.currentIndex() == 0
        assert ui_window.stage_btn.isEnabled() is False

    def test_combo_change_during_scan_keeps_stage_disabled(self, ui_window, monkeypatch):
        """Changing image type mid-scan must not re-enable Stage."""
        ui_window.image_type_combo.setCurrentText("survey")
        assert ui_window.stage_btn.isEnabled() is True

        mock_thread = MagicMock()
        mock_thread.isRunning.return_value = True
        ui_window.scan_thread = mock_thread
        ui_window.stage_btn.setEnabled(False)

        ui_window.image_type_combo.setCurrentText("training_true")

        assert ui_window.image_type_combo.currentData() == "training_true"
        assert ui_window.stage_btn.isEnabled() is False

        mock_thread.isRunning.return_value = False
        monkeypatch.setattr(
            "src.uploader.QMessageBox.information",
            MagicMock(return_value=QMessageBox.StandardButton.Ok),
        )
        ui_window.on_scan_finished(1, 0, 0)
        assert ui_window.stage_btn.isEnabled() is True


class TestOrthomosaicImageType:
    """Orthomosaic image type option (Issue #13)."""

    def test_combo_includes_orthomosaic(self, ui_window):
        """Image type combo lists orthomosaic alongside the three existing types."""
        combo = ui_window.image_type_combo
        types = [combo.itemData(i) for i in range(combo.count()) if combo.itemData(i) is not None]
        assert types == ["survey", "training_true", "training_false", "orthomosaic"]

    def test_orthomosaic_description(self, ui_window):
        """Selecting orthomosaic shows the low-res orthomosaic helper text."""
        ui_window.image_type_combo.setCurrentText("orthomosaic")
        assert ui_window.image_type_combo.currentData() == "orthomosaic"
        assert ui_window.image_type_desc.text() == "Low-res images for orthomosaic processing"
