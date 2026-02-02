"""
Tests for state management functionality.
"""
import pytest
from src.state_manager import StateManager


def test_add_image(mock_state_manager):
    """Test adding an image to the database."""
    image_id = mock_state_manager.add_image(
        filename="test.jpg",
        staging_path="/tmp/test.jpg",
        image_type="survey",
        exif_timestamp="2026-01-20T10:30:00",
        file_size=1024000,
    )

    assert image_id > 0

    # Verify it was added
    images = mock_state_manager.get_staged_images()
    assert len(images) == 1
    assert images[0]["filename"] == "test.jpg"
    assert images[0]["image_type"] == "survey"


def test_update_image_status(mock_state_manager):
    """Test updating image status."""
    image_id = mock_state_manager.add_image(
        filename="test.jpg",
        staging_path="/tmp/test.jpg",
        image_type="survey",
    )

    mock_state_manager.update_image_status(image_id, "uploading")

    # Should not appear in staged images anymore
    staged = mock_state_manager.get_staged_images()
    assert len(staged) == 0


def test_get_image_counts(mock_state_manager):
    """Test getting image counts by status."""
    # Add some images
    mock_state_manager.add_image("img1.jpg", "/tmp/img1.jpg", "survey")
    mock_state_manager.add_image("img2.jpg", "/tmp/img2.jpg", "survey")
    id3 = mock_state_manager.add_image("img3.jpg", "/tmp/img3.jpg", "survey")

    # Update one to failed
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

    # Test default value
    result = mock_state_manager.get_config("nonexistent", "default")
    assert result == "default"


def test_timestamp_ordering(mock_state_manager):
    """Test that images are ordered by EXIF timestamp."""
    # Add images with different timestamps
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
