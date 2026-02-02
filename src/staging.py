"""
Image staging from SD cards to local storage with retry logic.
"""
import shutil
import time
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime
from PySide6.QtCore import QThread, Signal
from PIL import Image
import psutil
import logging

logger = logging.getLogger(__name__)


class StagingCopier(QThread):
    """Thread for copying images from SD card to staging directory."""

    # Signals
    progress = Signal(int, int, str)  # current_file, total_files, current_filename
    speed_update = Signal(float)  # bytes per second
    finished = Signal(int, int)  # successful_count, failed_count
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
        sd_card_path: Path,
        staging_dir: Path,
        image_type: str,
        state_manager,
    ):
        super().__init__()
        self.sd_card_path = Path(sd_card_path)
        self.staging_dir = Path(staging_dir)
        self.image_type = image_type
        self.state_manager = state_manager
        self._should_stop = False

    def stop(self):
        """Request the thread to stop."""
        self._should_stop = True

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
            image_extensions = {".jpg", ".JPG", ".jpeg", ".JPEG"}
            images = []
            for ext in image_extensions:
                images.extend(self.sd_card_path.rglob(f"*{ext}"))

            total_files = len(images)
            if total_files == 0:
                logger.info("No images found on SD card")
                self.finished.emit(0, 0)
                return

            successful = 0
            failed = 0
            total_bytes = 0
            start_time = time.time()

            for idx, src_path in enumerate(images):
                if self._should_stop:
                    logger.info("Staging stopped by user")
                    break

                # Check disk space before each file
                if not self._check_disk_space():
                    logger.error("Insufficient disk space, stopping copy")
                    break

                # Emit progress
                self.progress.emit(idx + 1, total_files, src_path.name)

                # Destination path (preserve filename)
                dst_path = self.staging_dir / src_path.name

                # Skip if already exists
                if dst_path.exists():
                    logger.info(f"Skipping {src_path.name}, already staged")
                    successful += 1
                    continue

                # Copy with retry
                if self._copy_file_with_retry(src_path, dst_path):
                    # Extract EXIF timestamp
                    exif_timestamp = self._extract_exif_timestamp(dst_path)

                    # Get file size
                    file_size = dst_path.stat().st_size

                    # Add to database
                    try:
                        self.state_manager.add_image(
                            filename=dst_path.name,
                            staging_path=str(dst_path),
                            image_type=self.image_type,
                            exif_timestamp=exif_timestamp,
                            file_size=file_size,
                        )
                        successful += 1
                        total_bytes += file_size

                        # Calculate and emit speed
                        elapsed = time.time() - start_time
                        if elapsed > 0:
                            speed = total_bytes / elapsed
                            self.speed_update.emit(speed)

                    except Exception as e:
                        logger.error(f"Error adding {dst_path.name} to database: {e}")
                        self.error.emit(dst_path.name, str(e))
                        failed += 1
                        # Clean up the copied file
                        if dst_path.exists():
                            dst_path.unlink()
                else:
                    # All retries failed
                    error_msg = f"Failed to copy after {self.MAX_RETRIES} attempts"
                    logger.error(f"{src_path.name}: {error_msg}")
                    self.error.emit(src_path.name, error_msg)

                    # Record staging failure
                    try:
                        self.state_manager.add_staging_failure(
                            filename=src_path.name,
                            sd_card_path=str(src_path),
                            error_message=error_msg,
                            retry_attempts=self.MAX_RETRIES,
                        )
                    except Exception as e:
                        logger.error(f"Error recording staging failure: {e}")

                    failed += 1

            self.finished.emit(successful, failed)

        except Exception as e:
            logger.error(f"Staging thread error: {e}", exc_info=True)
            self.error.emit("THREAD_ERROR", str(e))
            self.finished.emit(0, 0)
