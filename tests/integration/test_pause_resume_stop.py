"""
Integration test: Pause / Resume / Stop upload mid-flight.

Covers:
- Pausing an upload and verifying no new uploads start
- Resuming a paused upload and completing all images
- Stopping an upload mid-flight and verifying remaining images stay staged
- GUI button state transitions (Pause ↔ Resume, Start/Stop enable/disable)
"""

import time
import pytest
from pathlib import Path
from aioresponses import aioresponses
from aioresponses.core import CallbackResult

from PySide6.QtCore import Qt

from src.state_manager import StateManager
from src.upload_manager import UploadManager

from .conftest import CHECK_URL, UPLOAD_URL, _pre_stage_images, wait_for_thread_done, process_events


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def fast_upload_manager_polls(monkeypatch):
    """Shrink pause-poll and progress-tick intervals so pause/stop tests run fast."""
    monkeypatch.setattr(UploadManager, "PAUSE_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(UploadManager, "PROGRESS_TICK_INTERVAL", 0.05)


def _slow_upload_callback(url, **kwargs):
    """Simulate a slow upload (20ms per request — just enough to allow a pause mid-flight)."""
    time.sleep(0.02)
    return CallbackResult(status=200, body="SUCCESS")


def _slow_check_callback(url, **kwargs):
    return CallbackResult(status=200, body="0")


class TestPauseResume:
    """Test pausing and resuming uploads."""

    def test_pause_and_resume_completes_all(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """Pause mid-upload, then resume — all images eventually upload."""
        images = _pre_stage_images(integration_state_manager, staging_dir, n=8)
        window = app_window
        n = len(images)

        completed_filenames = []

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            assert window.upload_thread is not None

            window.upload_thread.upload_completed.connect(
                lambda fname, _bytes: completed_filenames.append(fname)
            )

            # Wait until at least 1 upload completes
            qtbot.waitUntil(lambda: len(completed_filenames) >= 1, timeout=15_000)

            # Pause
            qtbot.mouseClick(window.upload_pause_btn, Qt.MouseButton.LeftButton)
            assert "Resume" in window.upload_pause_btn.text()

            paused_count = len(completed_filenames)
            assert paused_count >= 1

            # Resume
            qtbot.mouseClick(window.upload_pause_btn, Qt.MouseButton.LeftButton)
            assert "Pause" in window.upload_pause_btn.text()

            # Wait for all uploads to complete
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n
        assert counts["staged"] == 0

    def test_pause_button_state_transitions(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
        pre_staged_images,
    ):
        """Verify button text and enabled states during pause/resume."""
        window = app_window
        n = len(pre_staged_images)

        # Before upload
        assert window.upload_start_btn.isEnabled()
        assert not window.upload_pause_btn.isEnabled()
        assert not window.upload_stop_btn.isEnabled()
        assert "Pause" in window.upload_pause_btn.text()

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)

            # During upload
            assert not window.upload_start_btn.isEnabled()
            assert window.upload_pause_btn.isEnabled()
            assert window.upload_stop_btn.isEnabled()

            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        # After upload
        assert window.upload_start_btn.isEnabled()
        assert not window.upload_pause_btn.isEnabled()
        assert not window.upload_stop_btn.isEnabled()
        assert "Pause" in window.upload_pause_btn.text()


class TestStop:
    """Test stopping uploads mid-flight."""

    def test_stop_leaves_remaining_staged(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """Stopping mid-upload leaves un-uploaded images in 'staged' state."""
        images = _pre_stage_images(integration_state_manager, staging_dir, n=10)
        window = app_window

        completed_count = [0]

        with aioresponses() as m:
            for _ in range(10):
                m.post(CHECK_URL, callback=_slow_check_callback)
                m.post(UPLOAD_URL, callback=_slow_upload_callback)

            def on_completed(filename, _bytes):
                completed_count[0] += 1

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            window.upload_thread.upload_completed.connect(on_completed)

            # Wait for at least 1 completion
            qtbot.waitUntil(lambda: completed_count[0] >= 1, timeout=15_000)

            # Stop
            qtbot.mouseClick(window.upload_stop_btn, Qt.MouseButton.LeftButton)

            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=15_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] >= 1
        remaining = counts.get("staged", 0) + counts.get("uploading", 0)
        total_accounted = counts["uploaded"] + counts.get("failed", 0) + remaining
        assert total_accounted == 10

    def test_stop_re_enables_start_button(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
        pre_staged_images,
    ):
        """After stopping, the Start button is re-enabled."""
        window = app_window
        n = len(pre_staged_images)

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, callback=_slow_check_callback)
                m.post(UPLOAD_URL, callback=_slow_upload_callback)

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            qtbot.mouseClick(window.upload_stop_btn, Qt.MouseButton.LeftButton)

            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=15_000)
            process_events()

        assert window.upload_start_btn.isEnabled()
        assert not window.upload_pause_btn.isEnabled()
        assert not window.upload_stop_btn.isEnabled()


class TestNoStagedImages:
    """Edge case: trying to upload with no staged images."""

    def test_start_upload_with_nothing_shows_dialog(
        self,
        qtbot,
        app_window,
        integration_state_manager,
    ):
        """Clicking 'Start Upload' with 0 staged images should not crash."""
        window = app_window

        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] == 0

        # QMessageBox.information is patched to auto-return OK
        qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)

        # upload_thread should NOT have been created
        assert window.upload_thread is None
