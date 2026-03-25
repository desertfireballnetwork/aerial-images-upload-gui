"""Integration regression test for issue #9: staged images must keep their survey key.

This verifies that changing setup fields after staging does not re-target
already staged images to the wrong survey.
"""

import pytest
from PySide6.QtCore import Qt

from src.api_client import APIClient

from .conftest import wait_for_thread_done, process_events, create_test_jpeg


pytestmark = pytest.mark.integration


class TestMixedSurveyStaging:
    def test_staged_images_upload_with_staged_key(
        self,
        qtbot,
        app_window,
        staging_dir,
        integration_state_manager,
    ):
        """Batch A/B staged under different keys must upload under those same keys."""
        window = app_window

        create_test_jpeg(staging_dir / "A_0001.jpg", exif_datetime="2025:06:15 10:31:00")
        create_test_jpeg(staging_dir / "A_0002.jpg", exif_datetime="2025:06:15 10:32:00")

        # Stage batch A
        window.upload_key_edit.setText("survey-key-A")
        qtbot.mouseClick(window.stage_btn, Qt.MouseButton.LeftButton)
        wait_for_thread_done(qtbot, lambda: window.scan_thread, timeout=15_000)
        process_events()

        # Add batch B files and stage with a different key
        create_test_jpeg(staging_dir / "B_0001.jpg", exif_datetime="2025:06:15 10:33:00")
        create_test_jpeg(staging_dir / "B_0002.jpg", exif_datetime="2025:06:15 10:34:00")
        window.upload_key_edit.setText("survey-key-B")
        qtbot.mouseClick(window.stage_btn, Qt.MouseButton.LeftButton)
        wait_for_thread_done(qtbot, lambda: window.scan_thread, timeout=15_000)
        process_events()

        # Start upload after changing setup key again; upload must still use per-image key
        window.upload_key_edit.setText("wrong-current-ui-key")

        check_calls = []
        upload_calls = []

        async def fake_check(self, upload_key, filename):
            check_calls.append((upload_key, filename))
            return False

        async def fake_upload(self, upload_key, image_type, file_path):
            upload_calls.append((upload_key, image_type, file_path.name))
            return True, "SUCCESS"

        original_check = APIClient.check_image_uploaded
        original_upload = APIClient.upload_image
        APIClient.check_image_uploaded = fake_check
        APIClient.upload_image = fake_upload

        try:
            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()
        finally:
            APIClient.check_image_uploaded = original_check
            APIClient.upload_image = original_upload

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == 4
        assert counts["staged"] == 0
        assert counts["failed"] == 0

        assert len(check_calls) == 4
        assert len(upload_calls) == 4

        key_by_filename = {filename: key for key, _, filename in upload_calls}
        assert key_by_filename["A_0001.jpg"] == "survey-key-A"
        assert key_by_filename["A_0002.jpg"] == "survey-key-A"
        assert key_by_filename["B_0001.jpg"] == "survey-key-B"
        assert key_by_filename["B_0002.jpg"] == "survey-key-B"
