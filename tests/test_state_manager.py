"""Tests for state management functionality."""

import pytest
from src.state_manager import StateManager


def test_add_image(mock_state_manager):
    """Test adding an image to the database."""
    image_id = mock_state_manager.add_image(
        filename="test_unique_xyz.jpg",
        staging_path="/tmp/test_unique_xyz.jpg",
        image_type="survey",
        exif_timestamp="2026-01-20T10:30:00",
        file_size=1024000,
    )

    assert image_id > 0

    images = mock_state_manager.get_staged_images()
    added = next((i for i in images if i["filename"] == "test_unique_xyz.jpg"), None)
    assert added is not None
    assert added["image_type"] == "survey"


def test_update_image_status(mock_state_manager):
    """Test updating image status."""
    image_id = mock_state_manager.add_image(
        filename="test.jpg",
        staging_path="/tmp/test.jpg",
        image_type="survey",
    )

    mock_state_manager.update_image_status(image_id, "uploading")

    staged = mock_state_manager.get_staged_images()
    assert len(staged) == 0


def test_get_image_counts(mock_state_manager):
    """Test getting image counts by status."""
    mock_state_manager.add_image("img1.jpg", "/tmp/img1.jpg", "survey")
    mock_state_manager.add_image("img2.jpg", "/tmp/img2.jpg", "survey")
    id3 = mock_state_manager.add_image("img3.jpg", "/tmp/img3.jpg", "survey")

    mock_state_manager.update_image_status(id3, "failed", "Test error")

    counts = mock_state_manager.get_image_counts()
    assert counts["staged"] == 2
    assert counts["failed"] == 1
    assert counts["uploaded"] == 0


def test_staging_failures(mock_state_manager):
    """Test recording staging failures."""
    mock_state_manager.add_staging_failure(
        filename="bad.jpg",
        sd_card_path="/media/sd/bad.jpg",
        error_message="Copy failed",
        retry_attempts=3,
    )

    failures = mock_state_manager.get_staging_failures()
    assert len(failures) == 1
    assert failures[0]["filename"] == "bad.jpg"
    assert failures[0]["retry_attempts"] == 3


def test_config_storage(mock_state_manager):
    """Test configuration storage and retrieval."""
    mock_state_manager.set_config("test_key", {"value": 123, "name": "test"})

    result = mock_state_manager.get_config("test_key")
    assert result == {"value": 123, "name": "test"}

    result = mock_state_manager.get_config("nonexistent", "default")
    assert result == "default"


def test_timestamp_ordering(mock_state_manager):
    """Test that images are ordered by EXIF timestamp."""
    mock_state_manager.add_image(
        "img2.jpg", "/tmp/img2.jpg", "survey", exif_timestamp="2026-01-20T12:00:00"
    )
    mock_state_manager.add_image(
        "img1.jpg", "/tmp/img1.jpg", "survey", exif_timestamp="2026-01-20T10:00:00"
    )
    mock_state_manager.add_image(
        "img3.jpg", "/tmp/img3.jpg", "survey", exif_timestamp="2026-01-20T14:00:00"
    )

    images = mock_state_manager.get_staged_images()
    assert len(images) == 3
    assert images[0]["filename"] == "img1.jpg"
    assert images[1]["filename"] == "img2.jpg"
    assert images[2]["filename"] == "img3.jpg"


def test_add_upload_stat_and_get(mock_state_manager):
    """add_upload_stat records a row; get_upload_stats retrieves it."""
    mock_state_manager.add_upload_stat(
        bytes_uploaded=1024 * 1024,
        duration_seconds=2.5,
        active_workers=3,
    )

    stats = mock_state_manager.get_upload_stats(hours=1)
    assert len(stats) == 1
    assert stats[0]["bytes_uploaded"] == 1024 * 1024
    assert stats[0]["duration_seconds"] == pytest.approx(2.5)
    assert stats[0]["active_workers"] == 3


def test_get_upload_stats_multiple_records(mock_state_manager):
    """get_upload_stats returns all records within the time window."""
    mock_state_manager.add_upload_stat(bytes_uploaded=100, duration_seconds=0.5, active_workers=1)
    mock_state_manager.add_upload_stat(bytes_uploaded=200, duration_seconds=1.0, active_workers=2)
    stats = mock_state_manager.get_upload_stats(hours=1)
    assert len(stats) >= 2
    total_bytes = sum(s["bytes_uploaded"] for s in stats)
    assert total_bytes >= 300


def test_delete_uploaded_image_record(mock_state_manager):
    """delete_uploaded_image_record removes only uploaded images."""
    image_id = mock_state_manager.add_image("del.jpg", "/tmp/del.jpg", "survey")
    mock_state_manager.update_image_status(image_id, "uploaded")

    counts_before = mock_state_manager.get_image_counts()
    assert counts_before.get("uploaded", 0) == 1

    mock_state_manager.delete_uploaded_image_record(image_id)

    counts_after = mock_state_manager.get_image_counts()
    assert counts_after.get("uploaded", 0) == 0


def test_delete_non_uploaded_record_is_noop(mock_state_manager):
    """delete_uploaded_image_record on a staged image does nothing."""
    image_id = mock_state_manager.add_image(
        "keep_unique_noop.jpg", "/tmp/keep_unique_noop.jpg", "survey"
    )

    mock_state_manager.delete_uploaded_image_record(image_id)

    staged = mock_state_manager.get_staged_images()
    match = next((i for i in staged if i["filename"] == "keep_unique_noop.jpg"), None)
    assert match is not None


def test_increment_retry_count(mock_state_manager):
    """increment_retry_count bumps the retry counter."""
    image_id = mock_state_manager.add_image(
        "retry_unique_abc.jpg", "/tmp/retry_unique_abc.jpg", "survey"
    )

    mock_state_manager.increment_retry_count(image_id)
    mock_state_manager.increment_retry_count(image_id)

    staged = mock_state_manager.get_staged_images()
    row = next(i for i in staged if i["filename"] == "retry_unique_abc.jpg")
    assert row["retry_count"] == 2
