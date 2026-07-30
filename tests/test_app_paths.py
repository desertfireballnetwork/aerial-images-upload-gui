"""Tests for application path helpers and logging setup."""

import logging
import sys
from pathlib import Path
from unittest.mock import patch

from src import main as main_module
from src.app_paths import log_file_path, project_root, resolve_icon_path


class TestLogFilePath:
    def test_non_windows_uses_cwd_logs(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "platform", "linux")

        path = log_file_path()

        assert path.resolve() == (tmp_path / "logs" / "uploader.log").resolve()
        assert path.parent.is_dir()

    def test_windows_uses_appdata(self, monkeypatch, tmp_path):
        appdata = tmp_path / "AppData" / "Roaming"
        appdata.mkdir(parents=True)
        monkeypatch.setenv("APPDATA", str(appdata))
        monkeypatch.setattr(sys, "platform", "win32")

        path = log_file_path()

        assert path == appdata / "DFN" / "uploader.log"
        assert path.parent.is_dir()

    def test_windows_falls_back_to_home_when_appdata_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

        path = log_file_path()

        assert path == tmp_path / "DFN" / "uploader.log"


class TestResolveIconPath:
    def test_prefers_ico_over_png(self, monkeypatch, tmp_path):
        monkeypatch.setattr(main_module.sys, "frozen", False, raising=False)
        root = tmp_path / "repo"
        root.mkdir()
        (root / "icon.png").write_bytes(b"png")
        (root / "icon.ico").write_bytes(b"ico")

        with patch("src.app_paths.project_root", return_value=root):
            assert resolve_icon_path() == root / "icon.ico"

    def test_uses_png_when_ico_missing(self, monkeypatch, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        (root / "icon.png").write_bytes(b"png")

        with patch("src.app_paths.project_root", return_value=root):
            assert resolve_icon_path() == root / "icon.png"

    def test_returns_none_when_no_icon(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()

        with patch("src.app_paths.project_root", return_value=root):
            assert resolve_icon_path() is None

    def test_frozen_uses_meipass(self, monkeypatch, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        (bundle / "icon.ico").write_bytes(b"ico")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

        assert resolve_icon_path() == bundle / "icon.ico"


class TestSetupLogging:
    def test_setup_logging_creates_file_handler(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "platform", "linux")

        main_module.setup_logging()

        root = logging.getLogger()
        file_handlers = [
            handler for handler in root.handlers if isinstance(handler, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].baseFilename.endswith("logs/uploader.log")

        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
