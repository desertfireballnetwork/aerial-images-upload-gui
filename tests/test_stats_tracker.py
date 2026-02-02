"""
Tests for statistics tracking functionality.
"""
import pytest
import time
from src.stats_tracker import StatsTracker


def test_record_upload(stats_tracker):
    """Test recording upload statistics."""
    stats_tracker.record_upload(1024000)  # 1 MB
    stats_tracker.record_upload(2048000)  # 2 MB

    assert stats_tracker.total_bytes_uploaded == 3072000


def test_instantaneous_rate(stats_tracker):
    """Test instantaneous rate calculation."""
    # Record some uploads
    stats_tracker.record_upload(1024000)
    time.sleep(0.1)
    stats_tracker.record_upload(1024000)

    rate = stats_tracker.get_instantaneous_rate()
    assert rate > 0


def test_average_rate(stats_tracker):
    """Test average rate calculation."""
    # Record uploads
    for _ in range(5):
        stats_tracker.record_upload(1024000)
        time.sleep(0.05)

    avg_rate = stats_tracker.get_average_rate(1)
    assert avg_rate > 0


def test_estimate_time_remaining(stats_tracker):
    """Test time remaining estimation."""
    # Record some uploads to establish a rate
    for i in range(5):
        stats_tracker.record_upload(1024000)
        time.sleep(0.1)  # Increased sleep time to ensure measurable rate

    remaining_bytes = 10 * 1024000  # 10 MB remaining
    eta = stats_tracker.estimate_time_remaining(remaining_bytes, 1)

    assert eta is not None
    assert eta >= 0  # Can be 0 if rate is very high


def test_format_rate(stats_tracker):
    """Test rate formatting."""
    assert "B/s" in stats_tracker.format_rate(500)
    assert "KB/s" in stats_tracker.format_rate(5000)
    assert "MB/s" in stats_tracker.format_rate(5000000)
    assert "GB/s" in stats_tracker.format_rate(5000000000)


def test_format_size(stats_tracker):
    """Test size formatting."""
    assert "B" in stats_tracker.format_size(500)
    assert "KB" in stats_tracker.format_size(5000)
    assert "MB" in stats_tracker.format_size(5000000)
    assert "GB" in stats_tracker.format_size(5000000000)


def test_format_time(stats_tracker):
    """Test time formatting."""
    assert stats_tracker.format_time(45) == "45s"
    assert stats_tracker.format_time(125) == "2m 5s"
    assert stats_tracker.format_time(3725) == "1h 2m 5s"
    assert stats_tracker.format_time(None) == "Unknown"


def test_reset(stats_tracker):
    """Test resetting statistics."""
    stats_tracker.record_upload(1024000)
    stats_tracker.record_upload(2048000)

    assert stats_tracker.total_bytes_uploaded > 0

    stats_tracker.reset()

    assert stats_tracker.total_bytes_uploaded == 0
    assert len(stats_tracker.recent_uploads) == 0
    assert len(stats_tracker.hourly_uploads) == 0
