"""Unit tests for StagingCopier helper methods (no QThread required)."""

import shutil
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
from src.staging import StagingCopier
from src.state_manager import StateManager


@pytest.fixture()
def copier(tmp_path, mock_state_manager):
    """A StagingCopier instance ready for direct method calls (no thread started)."""
    sd_path = tmp_path / "sd"
    staging = tmp_path / "staging"
    sd_path.mkdir()
    staging.mkdir()
    c = StagingCopier(
        sd_card_path=sd_path,
        staging_dir=staging,
        image_type="survey",
        state_manager=mock_state_manager,
    )
    # Zero out all retry delays so tests are fast
    c.RETRY_DELAYS = [0.0, 0.0, 0.0]
    return c


@pytest.fixture()
def jpeg_with_exif(tmp_path) -> Path:
    """Create a JPEG that contains a DateTimeOriginal EXIF tag."""
    path = tmp_path / "with_exif.jpg"
    img = Image.new("RGB", (10, 10), color=(100, 150, 200))
    exif = img.getexif()
    exif[36867] = "2024:07:15 08:30:00"  # DateTimeOriginal
    img.save(path, format="JPEG", exif=exif.tobytes())
    return path


@pytest.fixture()
def jpeg_no_exif(tmp_path) -> Path:
    """Create a plain JPEG with no EXIF data."""
    path = tmp_path / "no_exif.jpg"
    img = Image.new("RGB", (10, 10), color=(50, 50, 50))
    img.save(path, format="JPEG")
    return path


# ---------------------------------------------------------------------------
# _extract_exif_timestamp
# ---------------------------------------------------------------------------


class TestExtractExifTimestamp:
    def test_reads_exif_datetimeoriginal(self, copier, jpeg_with_exif):
        result = copier._extract_exif_timestamp(jpeg_with_exif)
        assert result is not None
        assert result.startswith("2024-07-15T08:30:00")

    def test_falls_back_to_mtime_when_no_exif(self, copier, jpeg_no_exif):
        mtime = jpeg_no_exif.stat().st_mtime
        result = copier._extract_exif_timestamp(jpeg_no_exif)
        assert result is not None
        # Just verify it's an ISO-like string (has date/time separators)
        assert "T" in result or "-" in result

    def test_falls_back_to_mtime_for_corrupt_file(self, copier, tmp_path):
        bad = tmp_path / "corrupt.jpg"
        bad.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)  # truncated JPEG
        result = copier._extract_exif_timestamp(bad)
        # Should return mtime fallback, not None
        assert result is not None

    def test_returns_none_for_missing_file(self, copier, tmp_path):
        missing = tmp_path / "ghost.jpg"
        result = copier._extract_exif_timestamp(missing)
        # File doesn't exist — can't read mtime either
        assert result is None


# ---------------------------------------------------------------------------
# _copy_file_with_retry
# ---------------------------------------------------------------------------


class TestCopyFileWithRetry:
    def test_successful_copy(self, copier, tmp_path):
        src = tmp_path / "source.jpg"
        src.write_bytes(b"binary content")
        dst = tmp_path / "dest" / "source.jpg"

        result = copier._copy_file_with_retry(src, dst)

        assert result is True
        assert dst.exists()
        assert dst.read_bytes() == b"binary content"

    def test_creates_destination_directory(self, copier, tmp_path):
        src = tmp_path / "img.jpg"
        src.write_bytes(b"data")
        dst = tmp_path / "a" / "b" / "c" / "img.jpg"

        result = copier._copy_file_with_retry(src, dst)

        assert result is True
        assert dst.parent.is_dir()

    def test_returns_false_when_source_missing(self, copier, tmp_path):
        src = tmp_path / "missing.jpg"
        dst = tmp_path / "output.jpg"

        result = copier._copy_file_with_retry(src, dst)

        assert result is False

    def test_retries_on_size_mismatch(self, copier, tmp_path):
        """If shutil.copy2 produces a wrong-size file, it retries and eventually succeeds."""
        src = tmp_path / "real.jpg"
        src.write_bytes(b"REAL DATA")
        dst = tmp_path / "output.jpg"

        call_count = 0
        original_copy2 = shutil.copy2

        def flaky_copy2(s, d):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Write wrong size
                Path(d).write_bytes(b"X")
            else:
                original_copy2(s, d)

        with patch("src.staging.shutil.copy2", side_effect=flaky_copy2):
            result = copier._copy_file_with_retry(src, dst)

        assert result is True
        assert call_count == 2

    def test_all_retries_exhausted_returns_false(self, copier, tmp_path):
        """If every attempt raises an exception, returns False."""
        src = tmp_path / "img.jpg"
        src.write_bytes(b"data")
        dst = tmp_path / "out.jpg"

        with patch("src.staging.shutil.copy2", side_effect=OSError("disk full")):
            result = copier._copy_file_with_retry(src, dst)

        assert result is False
