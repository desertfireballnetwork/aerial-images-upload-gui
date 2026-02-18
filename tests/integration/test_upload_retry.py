"""
Integration test: Upload failures with retry logic.

Covers:
- Transient server errors (HTTP 500) that succeed after retries
- Permanent failures that exhaust all retry attempts
- Permanent failures (4xx) that skip retries entirely
- Crash recovery of images stuck in 'uploading' status
- Using the "Retry Selected" button in the Failed Uploads tab
"""

import pytest
from pathlib import Path
from aioresponses import aioresponses

from PySide6.QtCore import Qt

from src.state_manager import StateManager

from .conftest import CHECK_URL, UPLOAD_URL, _pre_stage_images, wait_for_thread_done, process_events


pytestmark = pytest.mark.integration


class TestTransientFailures:
    """Server returns errors on first attempts but eventually succeeds."""

    def test_succeeds_after_transient_500_errors(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
        pre_staged_images,
    ):
        """
        Upload returns HTTP 500 on first 2 attempts, then SUCCESS on 3rd.
        Image should end up as "uploaded".

        Uses 1 worker so that per-image retry responses are consumed in
        deterministic FIFO order (concurrency is covered separately).
        """
        window = app_window
        n = len(pre_staged_images)

        # Use 1 worker so responses are consumed per-image in FIFO order
        window.manual_radio.setChecked(True)
        window.worker_spin.setValue(1)

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=500, body="Internal Server Error")
                m.post(UPLOAD_URL, status=500, body="Internal Server Error")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=60_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n
        assert counts["failed"] == 0

    def test_succeeds_after_error_body_then_success(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
        pre_staged_images,
    ):
        """
        Upload returns 200 with error body first, then SUCCESS.

        Uses 1 worker so that per-image retry responses are consumed in
        deterministic FIFO order.
        """
        window = app_window
        n = len(pre_staged_images)

        window.manual_radio.setChecked(True)
        window.worker_spin.setValue(1)

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="ERROR - something went wrong")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=60_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n
        assert counts["failed"] == 0


class TestPermanentFailures:
    """All retry attempts are exhausted — image ends up failed."""

    def test_all_retries_exhausted_marks_failed(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """When all 5 upload attempts return 500, the image is marked 'failed'."""
        images = _pre_stage_images(integration_state_manager, staging_dir, n=1)
        window = app_window

        with aioresponses() as m:
            m.post(CHECK_URL, status=200, body="0")
            for _ in range(5):
                m.post(UPLOAD_URL, status=500, body="Internal Server Error")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=60_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["failed"] == 1
        assert counts["uploaded"] == 0

        fpath = Path(images[0]["staging_path"])
        assert fpath.exists()

        failed = integration_state_manager.get_failed_images()
        assert len(failed) == 1
        assert failed[0]["error_message"] is not None

    def test_mix_of_success_and_failure(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """3 images: first succeeds, second fails permanently, third succeeds."""
        images = _pre_stage_images(integration_state_manager, staging_dir, n=3)
        window = app_window

        with aioresponses() as m:
            # Image 0: success
            m.post(CHECK_URL, status=200, body="0")
            m.post(UPLOAD_URL, status=200, body="SUCCESS")

            # Image 1: 5 failures
            m.post(CHECK_URL, status=200, body="0")
            for _ in range(5):
                m.post(UPLOAD_URL, status=500, body="Server Error")

            # Image 2: success
            m.post(CHECK_URL, status=200, body="0")
            m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=60_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == 2
        assert counts["failed"] == 1


class TestRetryFromGUI:
    """Test the 'Retry Selected' button in the Failed Uploads tab."""

    def test_retry_resets_failed_to_staged(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """
        After an image fails, clicking 'Retry Selected' resets it to 'staged',
        and a subsequent upload run picks it up.
        """
        images = _pre_stage_images(integration_state_manager, staging_dir, n=1)
        window = app_window

        # --- First run: force failure ---
        with aioresponses() as m:
            m.post(CHECK_URL, status=200, body="0")
            for _ in range(5):
                m.post(UPLOAD_URL, status=500, body="Server Error")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=60_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["failed"] == 1

        # Refresh error table and retry
        window.refresh_error_table()
        assert window.error_table.rowCount() == 1

        window.error_table.selectRow(0)
        window.retry_failed()

        counts = integration_state_manager.get_image_counts()
        assert counts["staged"] == 1
        assert counts["failed"] == 0

        # --- Second run: now succeed ---
        with aioresponses() as m:
            m.post(CHECK_URL, status=200, body="0")
            m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == 1
        assert counts["failed"] == 0


class TestPermanentFailureNoRetry:
    """4xx errors should fail immediately without retrying."""

    def test_http_404_fails_immediately_no_retries(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """
        When the server returns HTTP 404 (invalid upload key), the image
        should be marked failed immediately without burning through 5 retries.
        Only 1 upload attempt should be made.
        """
        _pre_stage_images(integration_state_manager, staging_dir, n=1)
        window = app_window

        window.manual_radio.setChecked(True)
        window.worker_spin.setValue(1)

        with aioresponses() as m:
            m.post(CHECK_URL, status=200, body="0")
            # Only register 1 response — if the client retries, it will
            # get a ConnectionError (no more registered responses), which
            # would cause a different failure mode.
            m.post(UPLOAD_URL, status=404, body="Not Found")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["failed"] == 1
        assert counts["uploaded"] == 0

        failed = integration_state_manager.get_failed_images()
        assert len(failed) == 1
        assert "404" in failed[0]["error_message"]

    def test_http_400_fails_immediately_no_retries(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """HTTP 400 (bad request) is permanent — no retries."""
        _pre_stage_images(integration_state_manager, staging_dir, n=1)
        window = app_window

        window.manual_radio.setChecked(True)
        window.worker_spin.setValue(1)

        with aioresponses() as m:
            m.post(CHECK_URL, status=200, body="0")
            m.post(UPLOAD_URL, status=400, body="Bad Request")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["failed"] == 1
        assert counts["uploaded"] == 0

    def test_http_500_still_retries(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """HTTP 500 is transient — should retry and eventually succeed."""
        _pre_stage_images(integration_state_manager, staging_dir, n=1)
        window = app_window

        window.manual_radio.setChecked(True)
        window.worker_spin.setValue(1)

        with aioresponses() as m:
            m.post(CHECK_URL, status=200, body="0")
            m.post(UPLOAD_URL, status=500, body="Internal Server Error")
            m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == 1
        assert counts["failed"] == 0


class TestCrashRecovery:
    """Images stuck in 'uploading' from a previous crash are recovered."""

    def test_stuck_uploading_images_are_recovered_and_uploaded(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """
        Simulate a crash by pre-setting images to 'uploading' status directly
        in the DB. When the upload loop starts, it should reset them to 'staged'
        and then upload them normally.
        """
        # Pre-stage images normally first, then force them to 'uploading'
        images = _pre_stage_images(integration_state_manager, staging_dir, n=2)
        for img in images:
            integration_state_manager.update_image_status(img["id"], "uploading")

        counts = integration_state_manager.get_image_counts()
        assert counts.get("uploading", 0) == 2
        assert counts.get("staged", 0) == 0

        window = app_window

        window.manual_radio.setChecked(True)
        window.worker_spin.setValue(1)

        with aioresponses() as m:
            for _ in range(2):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == 2
        assert counts.get("uploading", 0) == 0
        assert counts.get("staged", 0) == 0

    def test_mix_of_stuck_and_staged_images(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """
        Mix of stuck-uploading and normally-staged images should all be uploaded.
        """
        images = _pre_stage_images(integration_state_manager, staging_dir, n=3)
        # Mark first image as stuck in 'uploading'
        integration_state_manager.update_image_status(images[0]["id"], "uploading")

        counts = integration_state_manager.get_image_counts()
        assert counts.get("uploading", 0) == 1
        assert counts.get("staged", 0) == 2

        window = app_window

        window.manual_radio.setChecked(True)
        window.worker_spin.setValue(1)

        with aioresponses() as m:
            for _ in range(3):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == 3
        assert counts.get("uploading", 0) == 0
