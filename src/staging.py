"""
Image staging: file copy from SD cards and folder scanning for DB registration.
"""

import shutil
import time
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from PySide6.QtCore import QThread, Signal
from PIL import Image
import psutil
import logging

logger = logging.getLogger(__name__)

# Common image extensions
IMAGE_EXTENSIONS = {".jpg", ".JPG", ".jpeg", ".JPEG"}


def _extract_exif_timestamp(image_path: Path) -> Optional[str]:
    """
    Extract EXIF DateTimeOriginal from image.

    Args:
        image_path: Path to the image file

    Returns:
        ISO format timestamp string, or None if not available
    """
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            if exif and 36867 in exif:  # DateTimeOriginal tag
                # EXIF datetime format is "YYYY:MM:DD HH:MM:SS"
                exif_time = exif[36867]
                # Convert to ISO format
                dt = datetime.strptime(exif_time, "%Y:%m:%d %H:%M:%S")
                return dt.isoformat()
    except Exception as e:
        logger.warning(f"Could not extract EXIF timestamp from {image_path.name}: {e}")

    # Fallback to file modification time
    try:
        mtime = image_path.stat().st_mtime
        dt = datetime.fromtimestamp(mtime)
        return dt.isoformat()
    except Exception as e:
        logger.warning(f"Could not get file mtime for {image_path.name}: {e}")

    return None


class StagingCopier(QThread):
    """Thread for copying images from a source folder to the staging directory.

    This is a pure file copy — no database registration happens here.
    That is handled separately by FolderScanner.
    """

    # Signals
    progress = Signal(int, int, str)  # current_file, total_files, current_filename
    speed_update = Signal(float)  # bytes per second
    finished = Signal(int, int, int, bool)  # successful_count, failed_count, skipped_count, aborted
    error = Signal(str, str)  # filename, error_message
    disk_space_warning = Signal(float)  # GB remaining
    disk_space_critical = Signal(float)  # GB remaining

    # Constants
    DISK_SPACE_WARNING_GB = 10
    DISK_SPACE_CRITICAL_GB = 5
    MAX_RETRIES = 3
    RETRY_DELAYS = [0.5, 1.0, 2.0]  # Exponential backoff in seconds

    def __init__(
        self,
        source_path: Path,
        staging_dir: Path,
        delete_source: bool = False,
    ):
        super().__init__()
        self.source_path = Path(source_path)
        self.staging_dir = Path(staging_dir)
        self.delete_source = delete_source
        self._should_stop = False
        self._copied_files: List[Path] = []

    def stop(self):
        """Request the thread to stop."""
        self._should_stop = True

    @property
    def copied_files(self) -> List[Path]:
        """Files that were successfully copied (available after thread finishes)."""
        return self._copied_files

    def _check_disk_space(self) -> bool:
        """
        Check if there's enough disk space to continue.

        Returns:
            True if sufficient space, False if critically low
        """
        try:
            usage = psutil.disk_usage(str(self.staging_dir))
            free_gb = usage.free / (1024**3)

            if free_gb < self.DISK_SPACE_CRITICAL_GB:
                self.disk_space_critical.emit(free_gb)
                return False
            elif free_gb < self.DISK_SPACE_WARNING_GB:
                self.disk_space_warning.emit(free_gb)

            return True
        except Exception as e:
            logger.error(f"Error checking disk space: {e}")
            return True  # Continue on error

    def _extract_exif_timestamp(self, image_path: Path) -> Optional[str]:
        """Extract EXIF DateTimeOriginal from image (delegates to module-level function)."""
        return _extract_exif_timestamp(image_path)

    def _copy_file_with_retry(self, src: Path, dst: Path) -> bool:
        """
        Copy a file with retry logic.

        Args:
            src: Source file path
            dst: Destination file path

        Returns:
            True if successful, False if all retries failed
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                # Ensure destination directory exists
                dst.parent.mkdir(parents=True, exist_ok=True)

                # Copy the file
                shutil.copy2(src, dst)

                # Verify the copy by comparing sizes
                if src.stat().st_size == dst.stat().st_size:
                    return True
                else:
                    logger.warning(
                        f"Size mismatch after copy for {src.name}, attempt {attempt + 1}"
                    )
                    if dst.exists():
                        dst.unlink()

            except Exception as e:
                logger.warning(f"Copy attempt {attempt + 1} failed for {src.name}: {e}")
                if dst.exists():
                    try:
                        dst.unlink()
                    except:
                        pass

                # Wait before retry (except on last attempt)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAYS[attempt])

        return False

    def run(self):
        """Main thread execution."""
        try:
            # Ensure staging directory exists
            self.staging_dir.mkdir(parents=True, exist_ok=True)

            # Get list of images
            image_paths = []
            for ext in {e.lower() for e in IMAGE_EXTENSIONS}:
                # Generate case=insensitive pattern e.g. .jpg -> .[jJ][pP][gG]
                pattern = (
                    f"*{''.join(f'[{c.lower()}{c.upper()}]' if c.isalpha() else c for c in ext)}"
                )
                image_paths.extend(self.source_path.rglob(pattern))

            # De-duplicate while preserving order, and ensure we only keep files
            images = [p for p in dict.fromkeys(image_paths) if p.is_file()]

            total_files = len(images)
            if total_files == 0:
                logger.info("No images found in source folder")
                self.finished.emit(0, 0, 0, False)
                return

            successful = 0
            failed = 0
            skipped = 0
            total_bytes = 0
            start_time = time.time()

            aborted = False
            for idx, src_path in enumerate(images):
                if self._should_stop:
                    logger.info("Staging stopped by user")
                    aborted = True
                    break

                # Check disk space before each file
                if not self._check_disk_space():
                    logger.error("Insufficient disk space, stopping copy")
                    aborted = True
                    break

                # Emit progress
                self.progress.emit(idx + 1, total_files, src_path.name)

                # Destination path (preserve relative directory structure)
                try:
                    rel_path = src_path.relative_to(self.source_path)
                except ValueError:
                    # Fallback to just filename if relative_to fails
                    rel_path = Path(src_path.name)

                dst_path = self.staging_dir / rel_path

                # Ensure parent directory exists
                dst_path.parent.mkdir(parents=True, exist_ok=True)

                # Skip if already exists
                if dst_path.exists():
                    logger.info(f"Skipping {src_path.name}, already in staging folder")
                    skipped += 1
                    # Delete source if requested and files appear identical (size match)
                    if self.delete_source:
                        try:
                            src_size = src_path.stat().st_size
                            dst_size = dst_path.stat().st_size
                            if src_size == dst_size:
                                try:
                                    src_path.unlink()
                                    logger.info(
                                        f"Deleted source {src_path.name} after skip (size match)"
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"Could not delete source {src_path.name} after skip: {e}"
                                    )
                            else:
                                logger.warning(
                                    f"Not deleting source {src_path.name} after skip: size mismatch "
                                    f"(source={src_size}, dest={dst_size})"
                                )
                        except Exception as e:
                            logger.warning(
                                f"Not deleting source {src_path.name} after skip: could not stat files: {e}"
                            )
                    continue

                # Copy with retry
                if self._copy_file_with_retry(src_path, dst_path):
                    file_size = dst_path.stat().st_size
                    successful += 1
                    total_bytes += file_size
                    self._copied_files.append(dst_path)

                    # Calculate and emit speed
                    elapsed = time.time() - start_time
                    if elapsed > 0:
                        speed = total_bytes / elapsed
                        self.speed_update.emit(speed)

                    # Delete source file if requested
                    if self.delete_source:
                        try:
                            src_path.unlink()
                        except Exception as e:
                            logger.warning(f"Could not delete source {src_path.name}: {e}")
                else:
                    # All retries failed
                    error_msg = f"Failed to copy after {self.MAX_RETRIES} attempts"
                    logger.error(f"{src_path.name}: {error_msg}")
                    self.error.emit(src_path.name, error_msg)
                    failed += 1

            self.finished.emit(successful, failed, skipped, aborted)

        except Exception as e:
            logger.error(f"Staging thread error: {e}", exc_info=True)
            self.error.emit("THREAD_ERROR", str(e))
            self.finished.emit(0, 0, 0, True)


class FolderScanner(QThread):
    """Thread for scanning a staging folder and registering un-tracked images in the database.

    Images already present in the DB (by staging_path) are skipped.
    """

    # Signals
    progress = Signal(int, int, str)  # current_file, total_files, current_filename
    finished = Signal(int, int, int)  # registered_count, skipped_count, failed_count

    def __init__(
        self,
        staging_dir: Path,
        image_type: str,
        state_manager,
    ):
        super().__init__()
        self.staging_dir = Path(staging_dir)
        self.image_type = image_type
        self.state_manager = state_manager
        self._should_stop = False

    def stop(self):
        """Request the thread to stop."""
        self._should_stop = True

    def run(self):
        """Scan staging folder and register new images in the database."""
        try:
            # Collect all images in the staging directory
            image_paths = []
            for ext in {e.lower() for e in IMAGE_EXTENSIONS}:
                pattern = (
                    f"*{''.join(f'[{c.lower()}{c.upper()}]' if c.isalpha() else c for c in ext)}"
                )
                image_paths.extend(self.staging_dir.rglob(pattern))

            # De-duplicate while preserving order, and ensure we only keep files
            images = [p for p in dict.fromkeys(image_paths) if p.is_file()]

            total_files = len(images)
            if total_files == 0:
                logger.info("No images found in staging folder")
                self.finished.emit(0, 0, 0)
                return

            registered = 0
            skipped = 0
            failed = 0

            # Pre-fetch all known staging paths to avoid N+1 DB queries
            existing_paths = self.state_manager.get_all_staging_paths()

            for idx, img_path in enumerate(images):
                if self._should_stop:
                    logger.info("Folder scan stopped by user")
                    break

                self.progress.emit(idx + 1, total_files, img_path.name)

                staging_path_str = str(img_path)

                # Skip if already in DB (O(1) in-memory lookup)
                if staging_path_str in existing_paths:
                    skipped += 1
                    continue

                # Extract EXIF timestamp
                exif_timestamp = _extract_exif_timestamp(img_path)

                # Get file size
                try:
                    file_size = img_path.stat().st_size
                except OSError:
                    file_size = None

                # Register in database
                try:
                    self.state_manager.add_image(
                        filename=img_path.name,
                        staging_path=staging_path_str,
                        image_type=self.image_type,
                        exif_timestamp=exif_timestamp,
                        file_size=file_size,
                    )
                    registered += 1
                except Exception as e:
                    logger.error(f"Error registering {img_path.name} in database: {e}")
                    failed += 1

            self.finished.emit(registered, skipped, failed)

        except Exception as e:
            logger.error(f"Folder scan error: {e}", exc_info=True)
            self.finished.emit(0, 0, 0)
