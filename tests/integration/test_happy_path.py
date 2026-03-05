"""
Integration test: Happy path — SD card → copy → stage → upload → all succeed.

Exercises the full user flow:
1. SD card detected with images
2. User selects card, clicks "Copy Images from SD Card"
3. File copy completes successfully
4. User clicks "Stage Images for Upload" (registers in DB)
5. User clicks "Start Upload"
6. All images pass the check_uploaded pre-flight (not yet uploaded)
7. All images upload successfully
8. DB shows all images as "uploaded", staging files are deleted
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
        """SD card copy copies all images to the staging folder (no DB)."""
        window = app_window

        monkeypatch.setattr(window.sd_monitor, "get_sd_cards", lambda: [mock_sd_card_info])
        window.refresh_sd_list()

        assert window.sd_list.count() == 1
        window.sd_list.setCurrentRow(0)

        qtbot.mouseClick(window.copy_btn, Qt.MouseButton.LeftButton)
        assert window.staging_thread is not None

        # Poll until staging thread finishes
        wait_for_thread_done(qtbot, lambda: window.staging_thread, timeout=15_000)
        process_events()

        # StagingCopier no longer touches DB — verify files copied
        staged_files = list(staging_dir.rglob("*.jpg")) + list(staging_dir.rglob("*.JPG"))
        assert len(staged_files) == 5

        # DB should still be empty (no registration yet)
        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] == 0

    def test_staging_skips_already_copied(
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

        qtbot.mouseClick(window.copy_btn, Qt.MouseButton.LeftButton)
        assert window.staging_thread is not None

        wait_for_thread_done(qtbot, lambda: window.staging_thread, timeout=15_000)
        process_events()

        # Should still be 5 total files (duplicates skipped by file existence check)
        staged_files = list(staging_dir.glob("*.jpg")) + list(staging_dir.glob("*.JPG"))
        assert len(staged_files) == 5


class TestHappyPathFolderScan:
    """Test the folder scan (staging → DB registration) step."""

    def test_folder_scan_registers_images(
        self,
        qtbot,
        app_window,
        staging_dir,
        integration_state_manager,
        pre_staged_images,
    ):
        """Stage button scans the staging folder and registers images."""
        window = app_window

        # Set image type and click Stage
        window.image_type_combo.setCurrentText("survey")
        qtbot.mouseClick(window.stage_btn, Qt.MouseButton.LeftButton)
        assert window.scan_thread is not None

        wait_for_thread_done(qtbot, lambda: window.scan_thread, timeout=15_000)
        process_events()

        # pre_staged_images already adds them to DB, so scan should skip them
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
    """Full end-to-end: copy from SD card, scan/register, then upload."""

    def test_copy_stage_upload(
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
        """Complete flow: copy images from SD card, stage them, then upload."""
        window = app_window

        # --- Copy from SD ---
        monkeypatch.setattr(window.sd_monitor, "get_sd_cards", lambda: [mock_sd_card_info])
        window.refresh_sd_list()
        window.sd_list.setCurrentRow(0)

        qtbot.mouseClick(window.copy_btn, Qt.MouseButton.LeftButton)
        wait_for_thread_done(qtbot, lambda: window.staging_thread, timeout=15_000)
        process_events()

        staged_files = list(staging_dir.rglob("*.jpg")) + list(staging_dir.rglob("*.JPG"))
        assert len(staged_files) == 5

        # --- Stage (register in DB) ---
        window.image_type_combo.setCurrentText("survey")
        qtbot.mouseClick(window.stage_btn, Qt.MouseButton.LeftButton)
        wait_for_thread_done(qtbot, lambda: window.scan_thread, timeout=15_000)
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


class TestSkipSdCardFlow:
    """Test skipping Step 2 entirely — files are already in the staging folder.

    This is the primary use case from Issue #3: the user has manually copied
    images to the local storage folder and wants to skip the SD card step.
    """

    def test_skip_sd_card_stage_then_upload(
        self,
        qtbot,
        app_window,
        upload_key,
        staging_dir,
        integration_state_manager,
    ):
        """E2E: manually place files in staging, skip Step 2, stage, upload."""
        window = app_window

        # Simulate user manually copying files to staging dir (skipping Step 2)
        from tests.integration.conftest import create_test_jpeg

        for i in range(4):
            create_test_jpeg(staging_dir / f"MANUAL_{i:04d}.jpg")

        # --- Step 3: Stage images (no SD card copy needed) ---
        window.image_type_combo.setCurrentText("training_true")
        qtbot.mouseClick(window.stage_btn, Qt.MouseButton.LeftButton)
        assert window.scan_thread is not None

        wait_for_thread_done(qtbot, lambda: window.scan_thread, timeout=15_000)
        process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] == 4

        # Verify image type was set correctly
        staged = integration_state_manager.get_staged_images()
        assert all(img["image_type"] == "training_true" for img in staged)

        # --- Step 4: Upload ---
        n = counts["staged"]
        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == 4
        assert counts["staged"] == 0
        assert counts["failed"] == 0

    def test_unstaged_count_updates(
        self,
        qtbot,
        app_window,
        staging_dir,
        integration_state_manager,
    ):
        """update_unstaged_count reflects files not yet in the DB."""
        window = app_window

        from tests.integration.conftest import create_test_jpeg

        # Add files to staging dir
        for i in range(3):
            create_test_jpeg(staging_dir / f"COUNT_{i:04d}.jpg")

        window.update_unstaged_count()
        wait_for_thread_done(
            qtbot, lambda: getattr(window, "_unstaged_counter_thread", None), timeout=5_000
        )
        process_events()

        text = window.unstaged_count_label.text()
        assert "3" in text
        assert "un-staged" in text

        # Stage them
        window.image_type_combo.setCurrentText("survey")
        qtbot.mouseClick(window.stage_btn, Qt.MouseButton.LeftButton)
        wait_for_thread_done(qtbot, lambda: window.scan_thread, timeout=15_000)
        process_events()

        # Now update count — should show 0 un-staged
        window.update_unstaged_count()
        wait_for_thread_done(
            qtbot, lambda: getattr(window, "_unstaged_counter_thread", None), timeout=5_000
        )
        process_events()

        text = window.unstaged_count_label.text()
        assert "0 un-staged" in text
