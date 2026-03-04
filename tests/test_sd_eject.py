"""Unit tests for SD card eject functionality."""

import pytest
from unittest.mock import patch, MagicMock
import subprocess
from src.sd_monitor import eject_device, _device_for_mount


class TestEjectDeviceLinux:
    """Test eject_device on Linux (udisksctl / umount fallback)."""

    @patch("src.sd_monitor.sys")
    @patch("src.sd_monitor._device_for_mount", return_value="/dev/sdb1")
    @patch("src.sd_monitor.subprocess.run")
    def test_eject_linux_udisksctl_success(self, mock_run, mock_dev, mock_sys):
        """udisksctl unmount + power-off succeeds."""
        mock_sys.platform = "linux"
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        success, msg = eject_device("/media/user/SDCARD")

        assert success is True
        assert "safely remove" in msg.lower()
        # Should have been called twice: unmount then power-off
        assert mock_run.call_count == 2

    @patch("src.sd_monitor.sys")
    @patch("src.sd_monitor._device_for_mount", return_value="/dev/sdb1")
    @patch("src.sd_monitor.subprocess.run")
    def test_eject_linux_udisksctl_fails_umount_fallback(self, mock_run, mock_dev, mock_sys):
        """When udisksctl fails, falls back to umount."""
        mock_sys.platform = "linux"
        results = [
            MagicMock(returncode=1, stderr="udisksctl failed"),  # udisksctl fails
            MagicMock(returncode=0, stderr=""),  # umount succeeds
        ]
        mock_run.side_effect = results

        success, msg = eject_device("/media/user/SDCARD")

        assert success is True
        assert "unmounted" in msg.lower()

    @patch("src.sd_monitor.sys")
    @patch("src.sd_monitor._device_for_mount", return_value="/dev/sdb1")
    @patch("src.sd_monitor.subprocess.run")
    def test_eject_linux_both_fail(self, mock_run, mock_dev, mock_sys):
        """When both udisksctl and umount fail, returns error."""
        mock_sys.platform = "linux"
        mock_run.return_value = MagicMock(returncode=1, stderr="device busy")

        success, msg = eject_device("/media/user/SDCARD")

        assert success is False
        assert "device busy" in msg.lower()

    @patch("src.sd_monitor.sys")
    @patch("src.sd_monitor._device_for_mount", return_value="/dev/sdb1")
    @patch("src.sd_monitor.subprocess.run")
    def test_eject_linux_unmount_ok_poweroff_fails(self, mock_run, mock_dev, mock_sys):
        """When unmount succeeds but power-off fails, returns failure with warning."""
        mock_sys.platform = "linux"
        results = [
            MagicMock(returncode=0, stderr=""),  # unmount succeeds
            MagicMock(returncode=1, stderr="Authorization required"),  # power-off fails
        ]
        mock_run.side_effect = results

        success, msg = eject_device("/media/user/SDCARD")

        assert success is False
        assert "unmounted" in msg.lower()
        assert "powering off" in msg.lower()


class TestEjectDeviceMacOS:
    """Test eject_device on macOS."""

    @patch("src.sd_monitor.sys")
    @patch("src.sd_monitor.subprocess.run")
    def test_eject_macos_success(self, mock_run, mock_sys):
        mock_sys.platform = "darwin"
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        success, msg = eject_device("/Volumes/SDCARD")

        assert success is True
        assert "safely remove" in msg.lower()

    @patch("src.sd_monitor.sys")
    @patch("src.sd_monitor.subprocess.run")
    def test_eject_macos_failure(self, mock_run, mock_sys):
        mock_sys.platform = "darwin"
        mock_run.return_value = MagicMock(returncode=1, stderr="disk in use")

        success, msg = eject_device("/Volumes/SDCARD")

        assert success is False
        assert "disk in use" in msg.lower()


class TestEjectDeviceWindows:
    """Test eject_device on Windows."""

    @patch("src.sd_monitor.sys")
    @patch("src.sd_monitor.subprocess.run")
    def test_eject_windows_success(self, mock_run, mock_sys):
        mock_sys.platform = "win32"
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        success, msg = eject_device("E:\\")

        assert success is True
        assert "safely remove" in msg.lower()


class TestEjectDeviceEdgeCases:
    """Test eject_device edge cases."""

    @patch("src.sd_monitor.sys")
    @patch("src.sd_monitor.subprocess.run", side_effect=FileNotFoundError("udisksctl"))
    def test_eject_tool_not_found(self, mock_run, mock_sys):
        mock_sys.platform = "linux"

        success, msg = eject_device("/media/user/SDCARD")

        assert success is False
        assert "not found" in msg.lower()

    @patch("src.sd_monitor.sys")
    @patch("src.sd_monitor.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30))
    def test_eject_timeout(self, mock_run, mock_sys):
        mock_sys.platform = "linux"

        success, msg = eject_device("/media/user/SDCARD")

        assert success is False
        assert "timed out" in msg.lower()

    @patch("src.sd_monitor.sys")
    def test_eject_unsupported_platform(self, mock_sys):
        mock_sys.platform = "freebsd"

        success, msg = eject_device("/mnt/sd")

        assert success is False
        assert "not supported" in msg.lower()


class TestDeviceForMount:
    """Test the _device_for_mount helper."""

    @patch("src.sd_monitor.psutil.disk_partitions")
    def test_finds_device_for_known_mount(self, mock_parts):
        mock_parts.return_value = [
            MagicMock(mountpoint="/media/user/SDCARD", device="/dev/sdb1"),
            MagicMock(mountpoint="/", device="/dev/sda1"),
        ]

        result = _device_for_mount("/media/user/SDCARD")
        assert result == "/dev/sdb1"

    @patch("src.sd_monitor.psutil.disk_partitions")
    def test_returns_mount_if_not_found(self, mock_parts):
        mock_parts.return_value = [
            MagicMock(mountpoint="/", device="/dev/sda1"),
        ]

        result = _device_for_mount("/media/user/UNKNOWN")
        assert result == "/media/user/UNKNOWN"
