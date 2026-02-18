"""
Integration test: Happy path — SD card → copy → upload → all succeed.

Exercises the full user flow:
1. SD card detected with images
2. User selects card, chooses image type, clicks "Copy Images from SD Card"
3. Staging completes successfully
4. User clicks "Start Upload"
5. All images pass the check_uploaded pre-flight (not yet uploaded)
6. All images upload successfully
7. DB shows all images as "uploaded", staging files are deleted
"""

import pytest
from pathlib import Path
from aioresponses import aioresponses

from PySide6.QtCore import Qt

from src.state_manager import StateManager

from .conftest import CHECK_URL, UPLOAD_URL, wait_for_thread_done, process_events


pytestmark = pytest.mark.integration


class TestHappyPathStaging:
    """Test the staging (SD card → local disk) portion of the happy path."""

    def test_staging_copies_all_images(
        self,
        qtbot,
        app_window,
        sd_card,
        mock_sd_card_info,
        staging_dir,
        integration_state_manager,
        monkeypatch,
    ):
        """SD card copy stages all images and records them in the DB."""
        window = app_window

        monkeypatch.setattr(window.sd_monitor, "get_sd_cards", lambda: [mock_sd_card_info])
        window.refresh_sd_list()

        assert window.sd_list.count() == 1
        window.sd_list.setCurrentRow(0)
        window.image_type_combo.setCurrentText("survey")

        qtbot.mouseClick(window.copy_btn, Qt.MouseButton.LeftButton)
        assert window.staging_thread is not None

        # Poll until staging thread finishes
        wait_for_thread_done(qtbot, lambda: window.staging_thread, timeout=15_000)
        process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] == 5

        staged_files = list(staging_dir.glob("*.jpg")) + list(staging_dir.glob("*.JPG"))
        assert len(staged_files) == 5

    def test_staging_skips_already_staged(
        self,
        qtbot,
        app_window,
        sd_card,
        mock_sd_card_info,
        staging_dir,
        integration_state_manager,
        monkeypatch,
        pre_staged_images,
    ):
        """If images are already in staging dir, they are skipped."""
        window = app_window

        monkeypatch.setattr(window.sd_monitor, "get_sd_cards", lambda: [mock_sd_card_info])
        window.refresh_sd_list()
        window.sd_list.setCurrentRow(0)
        window.image_type_combo.setCurrentText("survey")

        qtbot.mouseClick(window.copy_btn, Qt.MouseButton.LeftButton)
        assert window.staging_thread is not None

        wait_for_thread_done(qtbot, lambda: window.staging_thread, timeout=15_000)
        process_events()

        # Should still be 5 total (duplicates skipped)
        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] == 5


class TestHappyPathUpload:
    """Test the upload portion of the happy path (staging already done)."""

    def test_upload_all_images_succeed(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
        pre_staged_images,
    ):
        """All staged images upload successfully."""
        window = app_window
        n = len(pre_staged_images)

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            assert window.upload_thread is not None

            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n
        assert counts["staged"] == 0
        assert counts["failed"] == 0

        remaining = list(staging_dir.glob("*.jpg"))
        assert len(remaining) == 0

    def test_upload_updates_gui_on_completion(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
        pre_staged_images,
    ):
        """After upload completes, the GUI labels reflect the final state."""
        window = app_window
        n = len(pre_staged_images)

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        window.update_counts()

        assert "0" in window.pending_label.text()
        assert str(n) in window.uploaded_label.text()
        assert window.upload_start_btn.isEnabled()
        assert not window.upload_pause_btn.isEnabled()
        assert not window.upload_stop_btn.isEnabled()


class TestHappyPathEndToEnd:
    """Full end-to-end: stage from SD card, then upload everything."""

    def test_stage_then_upload(
        self,
        qtbot,
        app_window,
        sd_card,
        mock_sd_card_info,
        upload_key,
        staging_dir,
        integration_state_manager,
        monkeypatch,
    ):
        """Complete flow: copy images from SD card, then upload them all."""
        window = app_window

        # --- Stage ---
        monkeypatch.setattr(window.sd_monitor, "get_sd_cards", lambda: [mock_sd_card_info])
        window.refresh_sd_list()
        window.sd_list.setCurrentRow(0)
        window.image_type_combo.setCurrentText("survey")

        qtbot.mouseClick(window.copy_btn, Qt.MouseButton.LeftButton)
        wait_for_thread_done(qtbot, lambda: window.staging_thread, timeout=15_000)
        process_events()

        n = integration_state_manager.get_image_counts()["staged"]
        assert n == 5

        # --- Upload ---
        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n
        assert counts["staged"] == 0
        assert counts["failed"] == 0
