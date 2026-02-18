"""
Integration test: Staging failures — disk space and copy errors.

Covers:
- Low disk space warning (< 10 GB free)
- Critical disk space that aborts staging (< 5 GB free)
- File copy failure (IOError during shutil.copy2)
- Staging failures are recorded in the database
"""

import pytest
from pathlib import Path
from collections import namedtuple
from unittest.mock import patch

from PySide6.QtCore import Qt

from src.state_manager import StateManager
from src.staging import StagingCopier

from .conftest import create_test_jpeg, wait_for_thread_done, process_events


pytestmark = pytest.mark.integration

_DiskUsage = namedtuple("sdiskusage", ["total", "used", "free", "percent"])


@pytest.fixture(autouse=True)
def zero_staging_retry_delays(monkeypatch):
    """Eliminate staging copy back-off so copy-failure tests run instantly."""
    monkeypatch.setattr(StagingCopier, "RETRY_DELAYS", [0.0, 0.0, 0.0])


class TestDiskSpaceWarning:
    """Tests for low disk space handling during staging."""

    def test_warning_emitted_below_10gb(
        self,
        qtbot,
        app_window,
        sd_card,
        mock_sd_card_info,
        staging_dir,
        integration_state_manager,
        monkeypatch,
    ):
        """When free space is 5-10 GB, a warning is emitted but staging continues."""
        window = app_window

        monkeypatch.setattr(window.sd_monitor, "get_sd_cards", lambda: [mock_sd_card_info])
        window.refresh_sd_list()
        window.sd_list.setCurrentRow(0)
        window.image_type_combo.setCurrentText("survey")

        fake_usage = _DiskUsage(
            total=500 * 1024**3,
            used=492 * 1024**3,
            free=8 * 1024**3,
            percent=98.4,
        )
        monkeypatch.setattr("psutil.disk_usage", lambda path: fake_usage)

        warnings_received = []

        qtbot.mouseClick(window.copy_btn, Qt.MouseButton.LeftButton)
        assert window.staging_thread is not None
        window.staging_thread.disk_space_warning.connect(lambda gb: warnings_received.append(gb))

        wait_for_thread_done(qtbot, lambda: window.staging_thread, timeout=15_000)
        process_events()

        assert len(warnings_received) > 0
        assert all(w < 10.0 for w in warnings_received)

        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] > 0

    def test_critical_disk_space_aborts_staging(
        self,
        qtbot,
        app_window,
        sd_card,
        mock_sd_card_info,
        staging_dir,
        integration_state_manager,
        monkeypatch,
    ):
        """When free space is below 5 GB, staging is aborted."""
        window = app_window

        monkeypatch.setattr(window.sd_monitor, "get_sd_cards", lambda: [mock_sd_card_info])
        window.refresh_sd_list()
        window.sd_list.setCurrentRow(0)
        window.image_type_combo.setCurrentText("survey")

        fake_usage = _DiskUsage(
            total=500 * 1024**3,
            used=496 * 1024**3,
            free=4 * 1024**3,
            percent=99.2,
        )
        monkeypatch.setattr("psutil.disk_usage", lambda path: fake_usage)

        critical_received = []

        qtbot.mouseClick(window.copy_btn, Qt.MouseButton.LeftButton)
        assert window.staging_thread is not None
        window.staging_thread.disk_space_critical.connect(lambda gb: critical_received.append(gb))

        wait_for_thread_done(qtbot, lambda: window.staging_thread, timeout=15_000)
        process_events()

        assert len(critical_received) > 0

        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] <= 1


class TestCopyFailures:
    """Tests for file copy errors during staging."""

    def test_copy_failure_records_staging_failure(
        self,
        qtbot,
        app_window,
        sd_card,
        mock_sd_card_info,
        staging_dir,
        integration_state_manager,
        monkeypatch,
    ):
        """When shutil.copy2 raises IOError, the failure is recorded in the DB."""
        window = app_window

        monkeypatch.setattr(window.sd_monitor, "get_sd_cards", lambda: [mock_sd_card_info])
        window.refresh_sd_list()
        window.sd_list.setCurrentRow(0)
        window.image_type_combo.setCurrentText("survey")

        def failing_copy2(src, dst, **kwargs):
            raise IOError("Simulated disk error")

        monkeypatch.setattr("shutil.copy2", failing_copy2)

        errors_received = []

        qtbot.mouseClick(window.copy_btn, Qt.MouseButton.LeftButton)
        assert window.staging_thread is not None
        window.staging_thread.error.connect(lambda fname, err: errors_received.append((fname, err)))

        wait_for_thread_done(qtbot, lambda: window.staging_thread, timeout=15_000)
        process_events()

        assert len(errors_received) == 5

        failures = integration_state_manager.get_staging_failures()
        assert len(failures) == 5

        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] == 0

    def test_partial_copy_failure(
        self,
        qtbot,
        app_window,
        sd_card,
        mock_sd_card_info,
        staging_dir,
        integration_state_manager,
        monkeypatch,
    ):
        """When copy fails for some files but not others, partial staging succeeds."""
        window = app_window

        monkeypatch.setattr(window.sd_monitor, "get_sd_cards", lambda: [mock_sd_card_info])
        window.refresh_sd_list()
        window.sd_list.setCurrentRow(0)
        window.image_type_combo.setCurrentText("survey")

        import shutil

        original_copy2 = shutil.copy2

        def flaky_copy2(src, dst, **kwargs):
            src_name = Path(src).name
            if src_name in ("IMG_0001.jpg", "IMG_0003.jpg"):
                raise IOError(f"Simulated error for {src_name}")
            return original_copy2(src, dst, **kwargs)

        monkeypatch.setattr("shutil.copy2", flaky_copy2)

        qtbot.mouseClick(window.copy_btn, Qt.MouseButton.LeftButton)

        wait_for_thread_done(qtbot, lambda: window.staging_thread, timeout=15_000)
        process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] == 3

        failures = integration_state_manager.get_staging_failures()
        assert len(failures) == 2


class TestStagingDirectly:
    """Test staging thread directly (without GUI) for focused scenarios."""

    def test_staging_thread_with_empty_sd_card(self, qtbot, tmp_path, integration_state_manager):
        """StagingCopier with an empty SD card finishes with (0, 0)."""
        empty_sd = tmp_path / "empty_sd"
        empty_sd.mkdir()
        staging = tmp_path / "staging_empty"
        staging.mkdir()

        copier = StagingCopier(empty_sd, staging, "survey", integration_state_manager)

        copier.start()
        wait_for_thread_done(qtbot, lambda: copier, timeout=10_000)

        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] == 0
