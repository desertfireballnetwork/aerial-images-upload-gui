"""
Integration test: Already-uploaded images — check endpoint returns '1', skip re-upload.

Verifies that when the server says an image already exists:
- The upload endpoint is never called
- The image is marked "uploaded" in the DB
- The local staging file is deleted
"""

import pytest
from pathlib import Path
from aioresponses import aioresponses

from PySide6.QtCore import Qt

from src.state_manager import StateManager

from .conftest import CHECK_URL, UPLOAD_URL, wait_for_thread_done, process_events


pytestmark = pytest.mark.integration


class TestAlreadyUploaded:
    """Tests for images that the server reports as already uploaded."""

    def test_all_images_already_uploaded_skips_upload(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
        pre_staged_images,
    ):
        """
        When check_image_uploaded returns '1' for every image,
        the upload endpoint is never hit, and all images are marked uploaded.
        """
        window = app_window
        n = len(pre_staged_images)

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="1")

            # Do NOT register UPLOAD_URL — if code hits it, aioresponses raises

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

    def test_mix_of_already_uploaded_and_new(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
        pre_staged_images,
    ):
        """
        When some images are already uploaded and some are new,
        only the new ones hit the upload endpoint.
        """
        window = app_window
        n = len(pre_staged_images)
        already_count = 2

        with aioresponses() as m:
            for i in range(n):
                if i < already_count:
                    m.post(CHECK_URL, status=200, body="1")
                else:
                    m.post(CHECK_URL, status=200, body="0")
                    m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n
        assert counts["staged"] == 0
        assert counts["failed"] == 0

    def test_already_uploaded_response_in_upload_endpoint(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
        pre_staged_images,
    ):
        """
        When check returns '0' but upload returns 'ALREADY_UPLOADED',
        the image is still treated as a successful upload.
        """
        window = app_window
        n = len(pre_staged_images)

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="ALREADY_UPLOADED")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n
        assert counts["staged"] == 0
        assert counts["failed"] == 0
