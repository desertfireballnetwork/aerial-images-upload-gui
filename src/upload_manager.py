"""
Upload manager with auto-optimizing parallel uploads.
"""

import asyncio
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from PySide6.QtCore import QThread, Signal
import logging

from .api_client import APIClient
from .stats_tracker import StatsTracker

logger = logging.getLogger(__name__)


class UploadManager(QThread):
    """Manager for parallel image uploads with adaptive concurrency."""

    # Signals
    upload_started = Signal(str)  # filename
    upload_completed = Signal(str, int)  # filename, bytes
    upload_failed = Signal(str, str)  # filename, error
    progress_update = Signal(int, int)  # uploaded_count, total_count
    stats_update = Signal(dict)  # statistics dictionary
    worker_count_changed = Signal(int)  # current worker count
    finished = Signal()

    # Constants
    MIN_WORKERS = 1
    MAX_WORKERS = 10
    DEFAULT_WORKERS = 3
    MEASUREMENT_INTERVAL = 30  # seconds
    IMPROVEMENT_THRESHOLD = 0.10  # 10% improvement to increase workers
    MAX_RETRIES = 5
    RETRY_BASE_DELAY = 1.0  # seconds
    PAUSE_POLL_INTERVAL = 0.5  # seconds between pause-state checks in _worker
    PROGRESS_TICK_INTERVAL = 1.0  # seconds between progress-update ticks in _upload_loop

    def __init__(
        self,
        upload_key: str,
        state_manager,
        stats_tracker: StatsTracker,
        base_url: str = "https://find.gfo.rocks",
    ):
        super().__init__()
        self.upload_key = upload_key
        self.state_manager = state_manager
        self.stats_tracker = stats_tracker
        self.base_url = base_url

        self._should_stop = False
        self._paused = False

        # Concurrency control
        self.auto_optimize = True
        self.current_workers = self.DEFAULT_WORKERS
        self.manual_workers = self.DEFAULT_WORKERS

        # Auto-optimization state
        self.last_measurement_time = 0
        self.last_measurement_bytes = 0
        self.last_throughput = 0

    def set_manual_workers(self, count: int):
        """Set manual worker count and disable auto-optimization."""
        self.auto_optimize = False
        self.manual_workers = max(self.MIN_WORKERS, min(count, self.MAX_WORKERS))
        self.current_workers = self.manual_workers

    def set_auto_optimize(self, enabled: bool):
        """Enable or disable auto-optimization."""
        self.auto_optimize = enabled
        if enabled:
            self.current_workers = self.DEFAULT_WORKERS
        else:
            self.current_workers = self.manual_workers

    def pause(self):
        """Pause uploading."""
        self._paused = True

    def resume(self):
        """Resume uploading."""
        self._paused = False

    def stop(self):
        """Stop uploading."""
        self._should_stop = True

    def _adjust_worker_count(self):
        """Adjust worker count based on throughput measurements."""
        if not self.auto_optimize:
            return

        current_time = time.time()
        current_bytes = self.stats_tracker.total_bytes_uploaded

        # Check if enough time has passed for measurement
        if current_time - self.last_measurement_time < self.MEASUREMENT_INTERVAL:
            return

        # Calculate throughput
        time_delta = current_time - self.last_measurement_time
        bytes_delta = current_bytes - self.last_measurement_bytes
        current_throughput = bytes_delta / time_delta if time_delta > 0 else 0

        if self.last_throughput > 0:
            # Calculate improvement
            improvement = (current_throughput - self.last_throughput) / self.last_throughput

            if improvement > self.IMPROVEMENT_THRESHOLD:
                # Throughput improved, try increasing workers
                if self.current_workers < self.MAX_WORKERS:
                    self.current_workers += 1
                    self.worker_count_changed.emit(self.current_workers)
                    logger.info(
                        f"Increasing workers to {self.current_workers} "
                        f"(throughput improved by {improvement*100:.1f}%)"
                    )
            elif improvement < -self.IMPROVEMENT_THRESHOLD:
                # Throughput degraded, decrease workers
                if self.current_workers > self.MIN_WORKERS:
                    self.current_workers -= 1
                    self.worker_count_changed.emit(self.current_workers)
                    logger.info(
                        f"Decreasing workers to {self.current_workers} "
                        f"(throughput degraded by {improvement*100:.1f}%)"
                    )

        # Update measurements
        self.last_measurement_time = current_time
        self.last_measurement_bytes = current_bytes
        self.last_throughput = current_throughput

    async def _upload_single_image(self, client: APIClient, image_data: Dict[str, Any]) -> bool:
        """
        Upload a single image with retry logic.

        Args:
            client: API client
            image_data: Dictionary with image metadata from database

        Returns:
            True if successful, False otherwise
        """
        image_id = image_data["id"]
        file_path = Path(image_data["staging_path"])
        filename = image_data["filename"]
        image_type = image_data["image_type"]

        # Update status to uploading
        self.state_manager.update_image_status(image_id, "uploading")
        self.upload_started.emit(filename)

        # Check if already uploaded
        try:
            already_uploaded = await client.check_image_uploaded(self.upload_key, filename)
            if already_uploaded:
                logger.info(f"{filename} already uploaded, marking as complete")
                self.state_manager.update_image_status(image_id, "uploaded")

                # Remove the file
                if file_path.exists():
                    try:
                        file_path.unlink()
                    except Exception as e:
                        logger.warning(f"Could not delete {file_path}: {e}")

                self.upload_completed.emit(filename, 0)
                return True
        except Exception as e:
            logger.warning(f"Error checking if {filename} uploaded: {e}")
            # Continue with upload attempt

        # Retry loop
        for attempt in range(self.MAX_RETRIES):
            try:
                # Upload the image
                success, message = await client.upload_image(self.upload_key, image_type, file_path)

                if success:
                    # Record success
                    file_size = image_data.get("file_size", 0)
                    self.stats_tracker.record_upload(file_size)
                    self.state_manager.update_image_status(image_id, "uploaded")

                    # Remove the file
                    if file_path.exists():
                        try:
                            file_path.unlink()
                        except Exception as e:
                            logger.warning(f"Could not delete {file_path}: {e}")

                    self.upload_completed.emit(filename, file_size)
                    return True
                else:
                    # Upload failed
                    logger.warning(f"Upload attempt {attempt + 1} failed for {filename}: {message}")

                    # Don't retry permanent failures (4xx responses)
                    if self._is_permanent_failure(message):
                        logger.warning(f"Permanent failure for {filename}, not retrying: {message}")
                        self.state_manager.increment_retry_count(image_id)
                        self.state_manager.update_image_status(
                            image_id, "failed", f"Upload failed: {message}"
                        )
                        self.upload_failed.emit(filename, message)
                        return False

                    if attempt < self.MAX_RETRIES - 1:
                        # Wait before retry with exponential backoff
                        delay = self.RETRY_BASE_DELAY * (2**attempt)
                        await asyncio.sleep(delay)
                    else:
                        # All retries exhausted
                        self.state_manager.increment_retry_count(image_id)
                        self.state_manager.update_image_status(
                            image_id, "failed", f"Upload failed: {message}"
                        )
                        self.upload_failed.emit(filename, message)
                        return False

            except Exception as e:
                logger.error(f"Exception during upload attempt {attempt + 1} for {filename}: {e}")

                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BASE_DELAY * (2**attempt)
                    await asyncio.sleep(delay)
                else:
                    error_msg = str(e)
                    self.state_manager.increment_retry_count(image_id)
                    self.state_manager.update_image_status(image_id, "failed", error_msg)
                    self.upload_failed.emit(filename, error_msg)
                    return False

        return False

    async def _worker(self, client: APIClient, queue: asyncio.Queue, semaphore: asyncio.Semaphore):
        """Worker coroutine that processes images from the queue."""
        while True:
            image_data = await queue.get()
            if image_data is None:  # Sentinel value
                queue.task_done()
                break

            async with semaphore:
                if self._should_stop:
                    queue.task_done()
                    break

                # Wait while paused
                while self._paused and not self._should_stop:
                    await asyncio.sleep(self.PAUSE_POLL_INTERVAL)

                if not self._should_stop:
                    await self._upload_single_image(client, image_data)

            queue.task_done()

    @staticmethod
    def _is_permanent_failure(message: str) -> bool:
        """Check if an upload failure is permanent and should not be retried.

        Permanent failures include HTTP 4xx responses (bad request, not found,
        forbidden, etc.) which indicate client-side errors that won't resolve
        on retry.
        """
        return message.startswith("HTTP 4")

    async def _upload_loop(self):
        """Main upload loop."""
        # Crash recovery: reset any images stuck in 'uploading' from a
        # previous run that crashed or was killed mid-flight.
        reset_count = self.state_manager.reset_stuck_uploading()
        if reset_count > 0:
            logger.info(
                f"Reset {reset_count} images from 'uploading' back to 'staged' (crash recovery)"
            )

        async with APIClient(self.base_url) as client:
            while not self._should_stop:
                # Get staged images
                images = self.state_manager.get_staged_images()

                if not images:
                    logger.info("No staged images to upload")
                    await asyncio.sleep(5)
                    continue

                total_images = len(images)
                logger.info(f"Starting upload of {total_images} images")

                # Create queue and add images
                queue = asyncio.Queue()
                for image in images:
                    await queue.put(image)

                # Create semaphore for current worker count
                semaphore = asyncio.Semaphore(self.current_workers)
                self.worker_count_changed.emit(self.current_workers)

                # Create worker tasks
                workers = [
                    asyncio.create_task(self._worker(client, queue, semaphore))
                    for _ in range(self.current_workers)
                ]

                # Monitor progress and adjust workers
                uploaded_count = 0
                last_update_time = time.time()

                while not queue.empty() and not self._should_stop:
                    await asyncio.sleep(self.PROGRESS_TICK_INTERVAL)

                    # Update progress
                    current_time = time.time()
                    if current_time - last_update_time >= self.PROGRESS_TICK_INTERVAL:
                        counts = self.state_manager.get_image_counts()
                        uploaded_count = counts.get("uploaded", 0)
                        self.progress_update.emit(uploaded_count, total_images)

                        # Emit stats
                        stats = {
                            "instant_rate": self.stats_tracker.get_instantaneous_rate(),
                            "avg_1h": self.stats_tracker.get_average_rate(1),
                            "avg_12h": self.stats_tracker.get_average_rate(12),
                            "total_bytes": self.stats_tracker.total_bytes_uploaded,
                        }
                        self.stats_update.emit(stats)

                        last_update_time = current_time

                    # Adjust worker count periodically
                    self._adjust_worker_count()

                # When stopping, drain remaining queue items so join() doesn't hang
                if self._should_stop:
                    while not queue.empty():
                        try:
                            queue.get_nowait()
                            queue.task_done()
                        except asyncio.QueueEmpty:
                            break

                # Wait for all tasks to complete
                await queue.join()

                # Send sentinel values to stop workers
                for _ in range(self.current_workers):
                    await queue.put(None)

                # Wait for workers to finish
                await asyncio.gather(*workers)

                logger.info("Upload batch completed")

                if self._should_stop:
                    break

                # Check if there are more images (added during upload)
                remaining = self.state_manager.get_staged_images()
                if not remaining:
                    break

        self.finished.emit()

    def run(self):
        """Thread entry point."""
        try:
            # Reset measurements
            self.last_measurement_time = time.time()
            self.last_measurement_bytes = self.stats_tracker.total_bytes_uploaded

            # Run the async event loop
            asyncio.run(self._upload_loop())

        except Exception as e:
            logger.error(f"Upload manager error: {e}", exc_info=True)
            self.finished.emit()
