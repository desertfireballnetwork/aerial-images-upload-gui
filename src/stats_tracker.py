"""
Statistics tracking for upload rates and progress estimation.
"""

from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from collections import deque
import time
import logging

logger = logging.getLogger(__name__)


class StatsTracker:
    """Track upload statistics and calculate rates."""

    def __init__(self):
        # Instantaneous rate tracking (last 60 seconds)
        self.recent_uploads: deque = deque(maxlen=100)  # (timestamp, bytes)

        # Longer term tracking
        self.hourly_uploads: List[Tuple[float, int]] = []  # (timestamp, bytes)

        # Session totals
        self.total_bytes_uploaded = 0
        self.session_start = time.time()

    def record_upload(self, bytes_uploaded: int):
        """
        Record a successful upload.

        Args:
            bytes_uploaded: Number of bytes uploaded
        """
        now = time.time()
        self.recent_uploads.append((now, bytes_uploaded))
        self.hourly_uploads.append((now, bytes_uploaded))
        self.total_bytes_uploaded += bytes_uploaded

        # Clean old hourly data (keep last 13 hours for 12h average calculation)
        cutoff = now - (13 * 3600)
        self.hourly_uploads = [(ts, size) for ts, size in self.hourly_uploads if ts > cutoff]

    def get_instantaneous_rate(self) -> float:
        """
        Get instantaneous upload rate based on last 60 seconds.

        Returns:
            Upload rate in bytes per second
        """
        if not self.recent_uploads:
            return 0.0

        now = time.time()
        cutoff = now - 60  # Last 60 seconds

        recent = [(ts, size) for ts, size in self.recent_uploads if ts > cutoff]

        if not recent:
            return 0.0

        total_bytes = sum(size for _, size in recent)
        time_span = now - recent[0][0]

        if time_span > 0:
            return total_bytes / time_span
        return 0.0

    def get_average_rate(self, hours: int) -> float:
        """
        Get average upload rate over the last N hours.

        Args:
            hours: Number of hours to calculate average over

        Returns:
            Average upload rate in bytes per second
        """
        if not self.hourly_uploads:
            return 0.0

        now = time.time()
        cutoff = now - (hours * 3600)

        recent = [(ts, size) for ts, size in self.hourly_uploads if ts > cutoff]

        if not recent:
            return 0.0

        total_bytes = sum(size for _, size in recent)
        time_span = now - recent[0][0]

        if time_span > 0:
            return total_bytes / time_span
        return 0.0

    def estimate_time_remaining(self, remaining_bytes: int, use_hours: int = 12) -> Optional[int]:
        """
        Estimate time remaining based on average rate.

        Args:
            remaining_bytes: Number of bytes left to upload
            use_hours: Number of hours to base rate calculation on

        Returns:
            Estimated seconds remaining, or None if cannot estimate
        """
        avg_rate = self.get_average_rate(use_hours)

        if avg_rate <= 0:
            return None

        return int(remaining_bytes / avg_rate)

    def format_rate(self, bytes_per_second: float) -> str:
        """
        Format upload rate for display.

        Args:
            bytes_per_second: Rate in bytes per second

        Returns:
            Formatted string (e.g., "1.5 MB/s")
        """
        if bytes_per_second < 1024:
            return f"{bytes_per_second:.1f} B/s"
        elif bytes_per_second < 1024 * 1024:
            return f"{bytes_per_second / 1024:.1f} KB/s"
        elif bytes_per_second < 1024 * 1024 * 1024:
            return f"{bytes_per_second / (1024 * 1024):.2f} MB/s"
        else:
            return f"{bytes_per_second / (1024 * 1024 * 1024):.2f} GB/s"

    def format_size(self, bytes_size: int) -> str:
        """
        Format file size for display.

        Args:
            bytes_size: Size in bytes

        Returns:
            Formatted string (e.g., "1.5 GB")
        """
        if bytes_size < 1024:
            return f"{bytes_size} B"
        elif bytes_size < 1024 * 1024:
            return f"{bytes_size / 1024:.1f} KB"
        elif bytes_size < 1024 * 1024 * 1024:
            return f"{bytes_size / (1024 * 1024):.1f} MB"
        else:
            return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"

    def format_time(self, seconds: Optional[int]) -> str:
        """
        Format time duration for display.

        Args:
            seconds: Duration in seconds, or None

        Returns:
            Formatted string (e.g., "1h 23m 45s")
        """
        if seconds is None:
            return "Unknown"

        if seconds < 0:
            return "Unknown"

        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    def get_session_duration(self) -> int:
        """Get session duration in seconds."""
        return int(time.time() - self.session_start)

    def reset(self):
        """Reset all statistics."""
        self.recent_uploads.clear()
        self.hourly_uploads.clear()
        self.total_bytes_uploaded = 0
        self.session_start = time.time()
