"""
Test fixtures and utilities for DFN uploader tests.
"""
import pytest
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import Mock, MagicMock
from PIL import Image
import io

from src.state_manager import StateManager
from src.stats_tracker import StatsTracker


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_state_manager(monkeypatch, temp_dir):
    """Create a state manager with temporary database."""
    db_path = temp_dir / "test_state.db"

    # Patch the StateManager to use our test database
    original_init = StateManager.__init__

    def mock_init(self):
        if not hasattr(self, "initialized"):
            self.db_path = db_path
            self.conn_lock = __import__("threading").Lock()
            self._init_db()
            self.initialized = True

    monkeypatch.setattr(StateManager, "__init__", mock_init)

    manager = StateManager()
    yield manager

    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def stats_tracker():
    """Create a stats tracker instance."""
    return StatsTracker()


@pytest.fixture
def sample_image(temp_dir):
    """Create a sample JPEG image for testing."""
    img_path = temp_dir / "test_image.jpg"

    # Create a simple test image
    img = Image.new("RGB", (100, 100), color="red")
    img.save(img_path, "JPEG")

    return img_path


@pytest.fixture
def mock_sd_card(temp_dir):
    """Create a mock SD card directory with sample images."""
    sd_path = temp_dir / "sd_card"
    sd_path.mkdir()

    # Create some test images
    for i in range(5):
        img_path = sd_path / f"IMG_{i:04d}.jpg"
        img = Image.new("RGB", (100, 100), color="blue")
        img.save(img_path, "JPEG")

    return sd_path


@pytest.fixture
def staging_dir(temp_dir):
    """Create a staging directory."""
    staging = temp_dir / "staging"
    staging.mkdir()
    return staging


@pytest.fixture
def mock_api_responses():
    """Create mock API responses."""
    return {
        "check_uploaded_new": "0",
        "check_uploaded_exists": "1",
        "upload_success": "SUCCESS",
        "upload_already": "ALREADY_UPLOADED",
        "upload_error": "ERROR: Invalid upload key",
    }


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset StateManager singleton between tests."""
    StateManager._instance = None
    yield
    StateManager._instance = None
