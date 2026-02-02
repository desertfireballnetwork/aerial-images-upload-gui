"""
Cross-platform SD card detection and monitoring.
"""
import psutil
from pathlib import Path
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class SDCardInfo:
    """Information about a detected SD card."""

    def __init__(self, path: str, device: str, total_bytes: int, free_bytes: int):
        self.path = Path(path)
        self.device = device
        self.total_bytes = total_bytes
        self.free_bytes = free_bytes
        self.used_bytes = total_bytes - free_bytes

    @property
    def total_gb(self) -> float:
        """Total capacity in GB."""
        return self.total_bytes / (1024**3)

    @property
    def used_gb(self) -> float:
        """Used space in GB."""
        return self.used_bytes / (1024**3)

    @property
    def free_gb(self) -> float:
        """Free space in GB."""
        return self.free_bytes / (1024**3)

    def count_images(self) -> int:
        """Count image files on the SD card."""
        image_extensions = {".jpg", ".JPG", ".jpeg", ".JPEG"}
        count = 0
        try:
            for ext in image_extensions:
                count += len(list(self.path.rglob(f"*{ext}")))
        except (PermissionError, OSError) as e:
            logger.warning(f"Error counting images on {self.path}: {e}")
        return count

    def get_images(self) -> List[Path]:
        """Get list of all image files on the SD card."""
        image_extensions = {".jpg", ".JPG", ".jpeg", ".JPEG"}
        images = []
        try:
            for ext in image_extensions:
                images.extend(self.path.rglob(f"*{ext}"))
        except (PermissionError, OSError) as e:
            logger.warning(f"Error listing images on {self.path}: {e}")
        return images

    def __repr__(self):
        return f"SDCardInfo(path={self.path}, total={self.total_gb:.1f}GB, images={self.count_images()})"


class SDMonitor:
    """Monitor for SD card insertion/removal."""

    def __init__(self):
        self._last_devices = set()
        self._initialize()

    def _initialize(self):
        """Initialize the monitor with current devices."""
        self._last_devices = set(self._get_removable_devices())

    def _get_removable_devices(self) -> List[str]:
        """Get list of currently mounted removable devices."""
        removable = []
        try:
            partitions = psutil.disk_partitions(all=False)
            for partition in partitions:
                # Check if device is removable
                # On Linux, removable devices are typically in /media or /mnt
                # On macOS, they're in /Volumes
                # On Windows, they show up as regular drive letters but have specific opts
                mount_point = partition.mountpoint

                # Platform-specific detection
                is_removable = False

                if partition.opts:
                    # Some systems mark removable with specific mount options
                    if "removable" in partition.opts:
                        is_removable = True

                # Path-based detection
                if "/media/" in mount_point or "/run/media/" in mount_point:  # Linux
                    is_removable = True
                elif mount_point.startswith("/Volumes/") and mount_point != "/":  # macOS
                    is_removable = True
                elif (
                    len(mount_point) == 3 and mount_point[1] == ":" and mount_point[2] == "\\"
                ):  # Windows
                    # On Windows, we need to check if it's a removable drive
                    # This is a simple heuristic - could be improved
                    try:
                        usage = psutil.disk_usage(mount_point)
                        # If we can access it, consider drives that aren't C: as potentially removable
                        if mount_point[0].upper() != "C":
                            is_removable = True
                    except:
                        pass

                if is_removable:
                    removable.append(mount_point)

        except Exception as e:
            logger.error(f"Error detecting removable devices: {e}")

        return removable

    def get_sd_cards(self) -> List[SDCardInfo]:
        """
        Get list of currently connected SD cards.

        Returns:
            List of SDCardInfo objects
        """
        sd_cards = []
        devices = self._get_removable_devices()

        for device in devices:
            try:
                usage = psutil.disk_usage(device)
                partitions = psutil.disk_partitions(all=False)
                device_name = next(
                    (p.device for p in partitions if p.mountpoint == device), device
                )

                sd_cards.append(
                    SDCardInfo(
                        path=device,
                        device=device_name,
                        total_bytes=usage.total,
                        free_bytes=usage.free,
                    )
                )
            except Exception as e:
                logger.warning(f"Error getting info for device {device}: {e}")

        return sd_cards

    def check_for_changes(self) -> Dict[str, List[SDCardInfo]]:
        """
        Check if SD cards have been inserted or removed.

        Returns:
            Dictionary with 'added' and 'removed' lists of SDCardInfo
        """
        current_devices = set(self._get_removable_devices())
        added_paths = current_devices - self._last_devices
        removed_paths = self._last_devices - current_devices

        added = []
        for path in added_paths:
            try:
                usage = psutil.disk_usage(path)
                partitions = psutil.disk_partitions(all=False)
                device_name = next((p.device for p in partitions if p.mountpoint == path), path)

                added.append(
                    SDCardInfo(
                        path=path,
                        device=device_name,
                        total_bytes=usage.total,
                        free_bytes=usage.free,
                    )
                )
            except Exception as e:
                logger.warning(f"Error getting info for new device {path}: {e}")

        # For removed devices, we can't get current info, so just store paths
        removed = [SDCardInfo(path=path, device=path, total_bytes=0, free_bytes=0) for path in removed_paths]

        self._last_devices = current_devices

        return {"added": added, "removed": removed}
