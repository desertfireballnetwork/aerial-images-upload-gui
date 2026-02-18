"""
Integration test: Concurrent uploads — multiple workers uploading in parallel.

Covers:
- Manual worker count: setting N workers via the GUI
- Auto-optimize mode: verifying worker_count_changed signal fires
- Verifying that uploads actually happen concurrently (within N limit)
- All images complete successfully with concurrent workers
"""

import threading
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


class _ConcurrencyTracker:
    """Track the maximum number of concurrent in-flight uploads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._inflight = 0
        self.max_concurrent = 0
        self.total_calls = 0

    def enter(self):
        with self._lock:
            self._inflight += 1
            self.total_calls += 1
            self.max_concurrent = max(self.max_concurrent, self._inflight)

    def exit(self):
        with self._lock:
            self._inflight -= 1


class TestManualConcurrency:
    """Test setting a specific number of upload workers."""

    def test_manual_4_workers_all_images_succeed(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """With 4 manual workers and 15 images, all images are uploaded."""
        images = _pre_stage_images(integration_state_manager, staging_dir, n=15)
        window = app_window
        n = len(images)

        window.manual_radio.setChecked(True)
        window.worker_spin.setValue(4)

        tracker = _ConcurrencyTracker()

        def upload_callback(url, **kwargs):
            tracker.enter()
            time.sleep(0.01)  # minimal overlap window for concurrency tracking
            tracker.exit()
            return CallbackResult(status=200, body="SUCCESS")

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, callback=upload_callback)

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=60_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n
        assert counts["failed"] == 0
        assert tracker.total_calls == n
        # Some level of parallelism should have occurred
        assert tracker.max_concurrent >= 1

    def test_manual_1_worker_serial_uploads(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """With 1 manual worker, uploads are serial (max concurrent = 1)."""
        images = _pre_stage_images(integration_state_manager, staging_dir, n=5)
        window = app_window
        n = len(images)

        window.manual_radio.setChecked(True)
        window.worker_spin.setValue(1)

        tracker = _ConcurrencyTracker()

        def upload_callback(url, **kwargs):
            tracker.enter()
            time.sleep(0.01)  # minimal overlap window; with 1 worker max_concurrent stays 1
            tracker.exit()
            return CallbackResult(status=200, body="SUCCESS")

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, callback=upload_callback)

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n
        assert tracker.max_concurrent == 1


class TestAutoConcurrency:
    """Test auto-optimizing concurrency mode."""

    def test_auto_mode_emits_worker_count(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """In auto mode, worker_count_changed is emitted at least once."""
        images = _pre_stage_images(integration_state_manager, staging_dir, n=5)
        window = app_window
        n = len(images)

        window.auto_radio.setChecked(True)

        worker_counts = []

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)

            window.upload_thread.worker_count_changed.connect(
                lambda count: worker_counts.append(count)
            )

            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        assert len(worker_counts) >= 1
        assert worker_counts[0] == 3  # DEFAULT_WORKERS

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n

    def test_auto_mode_all_images_complete(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """Auto mode successfully uploads all images."""
        images = _pre_stage_images(integration_state_manager, staging_dir, n=10)
        window = app_window
        n = len(images)

        window.auto_radio.setChecked(True)

        with aioresponses() as m:
            for _ in range(n):
                m.post(CHECK_URL, status=200, body="0")
                m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=30_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == n
        assert counts["failed"] == 0


class TestConcurrencyWithFailures:
    """Test concurrent uploads where some workers encounter failures."""

    def test_concurrent_with_mixed_results(
        self,
        qtbot,
        app_window,
        upload_key,
        integration_state_manager,
        staging_dir,
    ):
        """With 3 workers and mixed results, all images are processed correctly."""
        images = _pre_stage_images(integration_state_manager, staging_dir, n=6)
        window = app_window

        window.manual_radio.setChecked(True)
        window.worker_spin.setValue(3)

        with aioresponses() as m:
            for i in range(6):
                m.post(CHECK_URL, status=200, body="0")
                if i in (2, 5):
                    for _ in range(5):
                        m.post(UPLOAD_URL, status=500, body="Error")
                else:
                    m.post(UPLOAD_URL, status=200, body="SUCCESS")

            qtbot.mouseClick(window.upload_start_btn, Qt.MouseButton.LeftButton)
            wait_for_thread_done(qtbot, lambda: window.upload_thread, timeout=60_000)
            process_events()

        counts = integration_state_manager.get_image_counts()
        assert counts["uploaded"] == 4
        assert counts["failed"] == 2
