"""Integration tests for the real staging preflight worker and Stage flow (issue #19).

The UI unit tests and the shared ``app_window`` fixture replace
``_StagingPreflightWorker`` with synchronous stand-ins. These tests instead start
the real QThread so the actual ``run()`` body, ``asyncio.run`` resolver call, and
cross-thread signal emission are exercised. The resolver network call is mocked
with ``aioresponses`` so no live server is contacted.
"""

import json

import aiohttp
import pytest
from aioresponses import aioresponses
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from src.api_client import SurveyLookupError
from src.uploader import UploaderWindow, _StagingPreflightWorker

from .conftest import _make_patched_init, create_test_jpeg, process_events


pytestmark = pytest.mark.integration

RESOLVE_URL = "https://find.gfo.rocks/survey/upload/resolve/"


def _wait_for_scan_done(qtbot, window, timeout=30_000):
    """Wait until the FolderScanner has been created and has finished."""

    def _check():
        t = window.scan_thread
        return t is not None and not t.isRunning()

    qtbot.waitUntil(_check, timeout=timeout)


class TestStagingPreflightWorkerThread:
    """The real _StagingPreflightWorker QThread (run() body + signals)."""

    def test_emits_count_and_survey_name(self, qtbot, staging_dir, integration_state_manager):
        create_test_jpeg(staging_dir / "img1.jpg")
        create_test_jpeg(staging_dir / "img2.jpg")

        results = []
        errors = []
        worker = _StagingPreflightWorker(str(staging_dir), "survey-key", integration_state_manager)
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.error.connect(lambda msg: errors.append(msg))

        with aioresponses() as m:
            m.post(RESOLVE_URL, status=200, payload={"survey_name": "DFN Survey 001"})
            worker.start()
            qtbot.waitUntil(lambda: bool(results) or bool(errors), timeout=15_000)
            worker.wait(5000)

        assert errors == []
        assert len(results) == 1
        count, survey_name, upload_key = results[0]
        assert count == 2
        assert survey_name == "DFN Survey 001"
        assert upload_key == "survey-key"

    def test_counts_only_unstaged_images(self, qtbot, staging_dir, integration_state_manager):
        create_test_jpeg(staging_dir / "staged.jpg")
        integration_state_manager.add_image(
            filename="staged.jpg",
            staging_path=str(staging_dir / "staged.jpg"),
            upload_key="survey-key",
            image_type="survey",
            exif_timestamp="2025-06-15T10:30:00",
            file_size=123,
        )
        create_test_jpeg(staging_dir / "new.jpg")

        results = []
        worker = _StagingPreflightWorker(str(staging_dir), "survey-key", integration_state_manager)
        worker.result_ready.connect(lambda *args: results.append(args))

        with aioresponses() as m:
            m.post(RESOLVE_URL, status=200, payload={"survey_name": "DFN Survey 001"})
            worker.start()
            qtbot.waitUntil(lambda: bool(results), timeout=15_000)
            worker.wait(5000)

        assert results[0][0] == 1

    def test_emits_error_on_invalid_key(self, qtbot, staging_dir, integration_state_manager):
        create_test_jpeg(staging_dir / "img1.jpg")

        results = []
        errors = []
        worker = _StagingPreflightWorker(str(staging_dir), "bad-key", integration_state_manager)
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.error.connect(lambda msg: errors.append(msg))

        with aioresponses() as m:
            m.post(RESOLVE_URL, status=404, payload={"error": "invalid_upload_key"})
            worker.start()
            qtbot.waitUntil(lambda: bool(results) or bool(errors), timeout=15_000)
            worker.wait(5000)

        assert results == []
        assert len(errors) == 1
        assert "not recognised" in errors[0]

    def test_emits_error_on_network_failure(self, qtbot, staging_dir, integration_state_manager):
        create_test_jpeg(staging_dir / "img1.jpg")

        results = []
        errors = []
        worker = _StagingPreflightWorker(str(staging_dir), "survey-key", integration_state_manager)
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.error.connect(lambda msg: errors.append(msg))

        with aioresponses() as m:
            m.post(RESOLVE_URL, exception=aiohttp.ClientConnectionError("network down"))
            worker.start()
            qtbot.waitUntil(lambda: bool(results) or bool(errors), timeout=15_000)
            worker.wait(5000)

        assert results == []
        assert len(errors) == 1
        assert "Could not confirm" in errors[0]


@pytest.fixture
def real_preflight_window(
    qtbot,
    tmp_path,
    upload_key,
    integration_state_manager,
    staging_dir,
    monkeypatch,
):
    """UploaderWindow wired with the REAL _StagingPreflightWorker.

    Unlike the shared ``app_window`` fixture, this does not replace the preflight
    worker with a synchronous stand-in, so the real QThread runs. Resolver network
    calls are mocked per-test with ``aioresponses``.
    """
    from src import sd_monitor as sd_mod

    config_path = tmp_path / "config.json"
    config_data = {
        "upload_key": upload_key,
        "staging_dir": str(staging_dir),
        "concurrency_mode": "auto",
        "concurrency_value": 3,
    }
    config_path.write_text(json.dumps(config_data))

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

    monkeypatch.setattr(UploaderWindow, "__init__", _make_patched_init(config_path, staging_dir))

    window = UploaderWindow()
    qtbot.addWidget(window)
    window.show()
    process_events()

    yield window

    if window.scan_thread and window.scan_thread.isRunning():
        window.scan_thread.stop()
        window.scan_thread.wait(5000)
    preflight = getattr(window, "preflight_thread", None)
    if preflight and preflight.isRunning():
        preflight.requestInterruption()
        preflight.wait(5000)
    window.close()
    process_events()


class TestStageFlowWithRealPreflight:
    """Full Stage flow using the real preflight worker and FolderScanner."""

    def test_proceed_registers_images_with_staged_key(
        self, qtbot, real_preflight_window, staging_dir, integration_state_manager
    ):
        window = real_preflight_window
        create_test_jpeg(staging_dir / "a.jpg")
        create_test_jpeg(staging_dir / "b.jpg")

        window.upload_key_edit.setText("survey-key")
        window.image_type_combo.setCurrentText("survey")

        with aioresponses() as m:
            m.post(RESOLVE_URL, status=200, payload={"survey_name": "DFN Survey 001"})
            qtbot.mouseClick(window.stage_btn, Qt.MouseButton.LeftButton)
            _wait_for_scan_done(qtbot, window, timeout=30_000)
            process_events()

        staged = integration_state_manager.get_staged_images()
        assert len(staged) == 2
        assert all(img["upload_key"] == "survey-key" for img in staged)
        assert all(img["image_type"] == "survey" for img in staged)

    def test_cancel_registers_nothing(
        self, qtbot, real_preflight_window, staging_dir, integration_state_manager, monkeypatch
    ):
        window = real_preflight_window
        create_test_jpeg(staging_dir / "a.jpg")

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.No)

        window.upload_key_edit.setText("survey-key")
        window.image_type_combo.setCurrentText("survey")

        with aioresponses() as m:
            m.post(RESOLVE_URL, status=200, payload={"survey_name": "DFN Survey 001"})
            qtbot.mouseClick(window.stage_btn, Qt.MouseButton.LeftButton)
            qtbot.waitUntil(lambda: window.preflight_thread is None, timeout=15_000)
            process_events()

        assert integration_state_manager.get_staged_images() == []
        assert window.scan_thread is None

    def test_lookup_failure_blocks_registration(
        self, qtbot, real_preflight_window, staging_dir, integration_state_manager, monkeypatch
    ):
        window = real_preflight_window
        create_test_jpeg(staging_dir / "a.jpg")

        warnings = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *args, **kw: warnings.append(args) or QMessageBox.StandardButton.Ok,
        )

        window.upload_key_edit.setText("bad-key")
        window.image_type_combo.setCurrentText("survey")

        with aioresponses() as m:
            m.post(RESOLVE_URL, status=404, payload={"error": "invalid_upload_key"})
            qtbot.mouseClick(window.stage_btn, Qt.MouseButton.LeftButton)
            qtbot.waitUntil(lambda: window.preflight_thread is None, timeout=15_000)
            process_events()

        assert integration_state_manager.get_staged_images() == []
        assert window.scan_thread is None
        assert warnings
        assert "Staging has not started" in warnings[0][2]
