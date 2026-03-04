"""Unit tests for StagingCopier and FolderScanner helper methods (no QThread required)."""

import shutil
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
from src.staging import StagingCopier, FolderScanner, _extract_exif_timestamp
from src.state_manager import StateManager


@pytest.fixture()
def copier(tmp_path):
    """A StagingCopier instance ready for direct method calls (no thread started)."""
    sd_path = tmp_path / "sd"
    staging = tmp_path / "staging"
    sd_path.mkdir()
    staging.mkdir()
    c = StagingCopier(
        source_path=sd_path,
        staging_dir=staging,
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

    def test_module_level_function_works(self, jpeg_with_exif):
        """The standalone _extract_exif_timestamp function works."""
        result = _extract_exif_timestamp(jpeg_with_exif)
        assert result is not None
        assert result.startswith("2024-07-15T08:30:00")


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


# ---------------------------------------------------------------------------
# StagingCopier — no DB interaction
# ---------------------------------------------------------------------------


class TestStagingCopierNoDb:
    def test_copier_has_no_state_manager(self, copier):
        """StagingCopier should not have a state_manager attribute."""
        assert not hasattr(copier, "state_manager")

    def test_copier_has_delete_source_flag(self, tmp_path):
        """StagingCopier accepts a delete_source flag."""
        c = StagingCopier(
            source_path=tmp_path / "sd",
            staging_dir=tmp_path / "staging",
            delete_source=True,
        )
        assert c.delete_source is True

    def test_copier_default_no_delete(self, copier):
        """delete_source defaults to False."""
        assert copier.delete_source is False

    def test_run_copies_files_without_db(self, tmp_path):
        """StagingCopier.run() copies files without any DB interaction."""
        sd = tmp_path / "sd"
        staging = tmp_path / "staging"
        sd.mkdir()
        staging.mkdir()

        # Create test images on "SD card"
        for i in range(3):
            img = Image.new("RGB", (10, 10), color="red")
            img.save(sd / f"IMG_{i:04d}.jpg", "JPEG")

        c = StagingCopier(sd, staging)
        c.RETRY_DELAYS = [0.0, 0.0, 0.0]
        c.run()  # Run synchronously

        # Files should be in staging
        copied = list(staging.glob("*.jpg"))
        assert len(copied) == 3

        # Source files should still exist (delete_source=False)
        originals = list(sd.glob("*.jpg"))
        assert len(originals) == 3

    def test_run_deletes_source_when_flag_set(self, tmp_path):
        """StagingCopier.run() with delete_source=True removes originals after copy."""
        sd = tmp_path / "sd"
        staging = tmp_path / "staging"
        sd.mkdir()
        staging.mkdir()

        for i in range(3):
            img = Image.new("RGB", (10, 10), color="blue")
            img.save(sd / f"IMG_{i:04d}.jpg", "JPEG")

        c = StagingCopier(sd, staging, delete_source=True)
        c.RETRY_DELAYS = [0.0, 0.0, 0.0]
        c.run()  # Run synchronously

        # Files should be in staging
        copied = list(staging.glob("*.jpg"))
        assert len(copied) == 3

        # Source files should be DELETED
        originals = list(sd.glob("*.jpg"))
        assert len(originals) == 0

    def test_run_tracks_copied_files_list(self, tmp_path):
        """StagingCopier.copied_files tracks all successfully copied files."""
        sd = tmp_path / "sd"
        staging = tmp_path / "staging"
        sd.mkdir()
        staging.mkdir()

        for i in range(2):
            img = Image.new("RGB", (10, 10), color="green")
            img.save(sd / f"IMG_{i:04d}.jpg", "JPEG")

        c = StagingCopier(sd, staging)
        c.RETRY_DELAYS = [0.0, 0.0, 0.0]
        c.run()

        assert len(c.copied_files) == 2
        assert all(p.parent == staging for p in c.copied_files)

    def test_run_preserves_relative_directory_structure(self, tmp_path):
        """StagingCopier.run() preserves relative directory paths from the source."""
        sd = tmp_path / "sd"
        staging = tmp_path / "staging"
        sd.mkdir()
        staging.mkdir()

        # Create two files with the same name in different subdirectories
        dir1 = sd / "DCIM" / "100"
        dir2 = sd / "DCIM" / "101"
        dir1.mkdir(parents=True)
        dir2.mkdir(parents=True)

        img = Image.new("RGB", (10, 10), color="red")
        img.save(dir1 / "IMG_0000.jpg", "JPEG")
        img.save(dir2 / "IMG_0000.jpg", "JPEG")

        c = StagingCopier(sd, staging)
        c.RETRY_DELAYS = [0.0, 0.0, 0.0]
        c.run()

        assert len(c.copied_files) == 2
        # Verify the structure is preserved
        assert (staging / "DCIM" / "100" / "IMG_0000.jpg").exists()
        assert (staging / "DCIM" / "101" / "IMG_0000.jpg").exists()

    def test_run_skips_files_already_in_staging(self, tmp_path):
        """StagingCopier.run() skips files that already exist in staging dir."""
        sd = tmp_path / "sd"
        staging = tmp_path / "staging"
        sd.mkdir()
        staging.mkdir()

        # Create image on SD and a copy already in staging
        img = Image.new("RGB", (10, 10), color="red")
        img.save(sd / "IMG_0000.jpg", "JPEG")
        img.save(staging / "IMG_0000.jpg", "JPEG")  # Already exists

        c = StagingCopier(sd, staging)
        c.RETRY_DELAYS = [0.0, 0.0, 0.0]
        c.run()

        # Should not be in copied_files since it was skipped
        assert len(c.copied_files) == 0

    def test_run_skips_files_already_in_staging_emits_skipped(self, tmp_path):
        """StagingCopier.finished emits skipped=1 when a destination file exists."""
        sd = tmp_path / "sd"
        staging = tmp_path / "staging"
        sd.mkdir()
        staging.mkdir()

        img = Image.new("RGB", (10, 10), color="red")
        img.save(sd / "IMG_0000.jpg", "JPEG")
        img.save(staging / "IMG_0000.jpg", "JPEG")  # Already exists

        c = StagingCopier(sd, staging)
        c.RETRY_DELAYS = [0.0, 0.0, 0.0]

        mock_finished = MagicMock()
        c.finished.connect(mock_finished)
        c.run()

        # Emit signature: successful, failed, skipped, aborted
        mock_finished.assert_called_once_with(0, 0, 1, False)
        # Source should still exist since delete_source=False by default
        assert (sd / "IMG_0000.jpg").exists()

    def test_run_deletes_skipped_source_on_size_match(self, tmp_path):
        """StagingCopier.run() deletes source for skipped files if sizes match and delete_source is True."""
        sd = tmp_path / "sd"
        staging = tmp_path / "staging"
        sd.mkdir()
        staging.mkdir()

        img_data = b"identical_content"
        src_file = sd / "IMG_0000.jpg"
        dst_file = staging / "IMG_0000.jpg"

        with open(src_file, "wb") as f:
            f.write(img_data)
        with open(dst_file, "wb") as f:
            f.write(img_data)

        c = StagingCopier(sd, staging, delete_source=True)
        c.run()

        # Should be skipped because it exists
        # But since delete_source=True and size matches, source should be deleted
        assert not src_file.exists()
        assert dst_file.exists()

    def test_run_does_not_delete_skipped_source_on_size_mismatch(self, tmp_path):
        """StagingCopier.run() preserves source for skipped files if sizes differ."""
        sd = tmp_path / "sd"
        staging = tmp_path / "staging"
        sd.mkdir()
        staging.mkdir()

        src_file = sd / "IMG_0000.jpg"
        dst_file = staging / "IMG_0000.jpg"

        with open(src_file, "wb") as f:
            f.write(b"content_a")
        with open(dst_file, "wb") as f:
            f.write(b"different_content_b")

        c = StagingCopier(sd, staging, delete_source=True)
        c.run()

        # Should be skipped, and since sizes differ, source must be preserved
        assert src_file.exists()
        assert dst_file.exists()

    def test_run_case_insensitive_deduplication(self, tmp_path):
        """StagingCopier.run() filters by suffix.lower() to prevent duplicates."""
        sd = tmp_path / "sd"
        staging = tmp_path / "staging"
        sd.mkdir()
        staging.mkdir()

        # Save an image with uppercase extension
        img = Image.new("RGB", (10, 10), color="blue")
        img.save(sd / "LOWER.jpg", "JPEG")
        img.save(sd / "UPPER.JPG", "JPEG")
        img.save(sd / "MIXED.JpG", "JPEG")

        c = StagingCopier(sd, staging)
        c.RETRY_DELAYS = [0.0, 0.0, 0.0]

        mock_finished = MagicMock()
        c.finished.connect(mock_finished)
        c.run()

        # Should match all 3, but exactly 3, not 3 per extension variant
        mock_finished.assert_called_once_with(3, 0, 0, False)
        assert len(c.copied_files) == 3


# ---------------------------------------------------------------------------
# FolderScanner
# ---------------------------------------------------------------------------


class TestFolderScanner:
    def test_scans_and_registers_images(self, tmp_path, mock_state_manager):
        """FolderScanner registers un-tracked images in the DB."""
        staging = tmp_path / "staging"
        staging.mkdir()
        for i in range(3):
            img = Image.new("RGB", (10, 10), color="red")
            img.save(staging / f"IMG_{i:04d}.jpg", "JPEG")

        scanner = FolderScanner(staging, "survey", mock_state_manager)
        # Run synchronously (not as a thread)
        scanner.run()

        # All 3 should be registered
        counts = mock_state_manager.get_image_counts()
        assert counts["staged"] == 3

    def test_skips_already_registered(self, tmp_path, mock_state_manager):
        """FolderScanner skips images already in the DB."""
        staging = tmp_path / "staging"
        staging.mkdir()

        # Create and pre-register one image
        img = Image.new("RGB", (10, 10), color="blue")
        img_path = staging / "IMG_0000.jpg"
        img.save(img_path, "JPEG")
        mock_state_manager.add_image(
            filename="IMG_0000.jpg",
            staging_path=str(img_path),
            image_type="survey",
            file_size=img_path.stat().st_size,
        )

        # Create a second un-registered image
        img2 = Image.new("RGB", (10, 10), color="green")
        img2.save(staging / "IMG_0001.jpg", "JPEG")

        scanner = FolderScanner(staging, "survey", mock_state_manager)
        scanner.run()

        # Should have 2 total (1 pre-registered + 1 newly registered)
        counts = mock_state_manager.get_image_counts()
        assert counts["staged"] == 2

    def test_empty_folder(self, tmp_path, mock_state_manager):
        """FolderScanner handles an empty folder."""
        staging = tmp_path / "staging"
        staging.mkdir()

        scanner = FolderScanner(staging, "survey", mock_state_manager)
        scanner.run()

        counts = mock_state_manager.get_image_counts()
        assert counts["staged"] == 0

    def test_uses_correct_image_type(self, tmp_path, mock_state_manager):
        """FolderScanner registers images with the specified image type."""
        staging = tmp_path / "staging"
        staging.mkdir()
        img = Image.new("RGB", (10, 10), color="red")
        img.save(staging / "IMG_0000.jpg", "JPEG")

        scanner = FolderScanner(staging, "training_true", mock_state_manager)
        scanner.run()

        images = mock_state_manager.get_staged_images()
        assert len(images) == 1
        assert images[0]["image_type"] == "training_true"

    def test_emits_failed_when_registration_fails(self, tmp_path, mock_state_manager):
        """FolderScanner emissions failed=1 when add_image raises."""
        staging = tmp_path / "staging"
        staging.mkdir()
        img = Image.new("RGB", (10, 10), color="red")
        img.save(staging / "IMG_0000.jpg", "JPEG")

        scanner = FolderScanner(staging, "survey", mock_state_manager)

        # force registration to fail
        def blow_up(*args, **kwargs):
            raise ValueError("DB down")

        mock_state_manager.add_image = blow_up

        mock_finished = MagicMock()
        scanner.finished.connect(mock_finished)
        scanner.run()

        # registered=0, skipped=0, failed=1
        mock_finished.assert_called_once_with(0, 0, 1)

    def test_folder_scanner_case_insensitive_deduplication(self, tmp_path, mock_state_manager):
        """FolderScanner filters by lowercase suffix to prevent duplicate DB writes."""
        staging = tmp_path / "staging"
        staging.mkdir()

        # Save an image with uppercase extension
        img = Image.new("RGB", (10, 10), color="blue")
        img.save(staging / "LOWER.jpg", "JPEG")
        img.save(staging / "UPPER.JPG", "JPEG")
        img.save(staging / "MIXED.JpG", "JPEG")

        scanner = FolderScanner(staging, "survey", mock_state_manager)

        mock_finished = MagicMock()
        scanner.finished.connect(mock_finished)
        scanner.run()

        # registered=3, skipped=0, failed=0
        mock_finished.assert_called_once_with(3, 0, 0)
