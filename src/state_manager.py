"""
Thread-safe state management using SQLite for persistent image tracking and configuration.
"""

import sqlite3
import threading
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager


class StateManager:
    """Singleton class for managing application state with thread-safe SQLite access."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"):
            self.db_path = Path("state.db")
            self.conn_lock = threading.Lock()
            self._init_db()
            self.initialized = True

    def _get_connection(self):
        """Get a thread-local database connection."""
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30.0,
            isolation_level="IMMEDIATE",
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transaction(self):
        """Context manager for database transactions with proper locking."""
        with self.conn_lock:
            conn = self._get_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self.transaction() as conn:
            # Images table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    staging_path TEXT NOT NULL,
                    image_type TEXT NOT NULL CHECK(image_type IN ('survey', 'training_true', 'training_false')),
                    status TEXT NOT NULL CHECK(status IN ('pending', 'staging', 'staged', 'uploading', 'uploaded', 'failed')),
                    exif_timestamp TEXT,
                    file_size INTEGER,
                    retry_count INTEGER DEFAULT 0,
                    add_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    upload_timestamp TEXT,
                    error_message TEXT,
                    UNIQUE(staging_path)
                )
                """
            )

            # Staging failures table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS staging_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    sd_card_path TEXT NOT NULL,
                    error_message TEXT,
                    retry_attempts INTEGER DEFAULT 0,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Upload statistics table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS upload_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    bytes_uploaded INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL,
                    active_workers INTEGER NOT NULL
                )
                """
            )

            # Configuration table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_images_status ON images(status)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_images_exif_timestamp ON images(exif_timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_upload_stats_timestamp ON upload_stats(timestamp)"
            )

    def add_image(
        self,
        filename: str,
        staging_path: str,
        image_type: str,
        exif_timestamp: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> int:
        """Add a new image to the database."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO images (filename, staging_path, image_type, status, exif_timestamp, file_size)
                VALUES (?, ?, ?, 'staged', ?, ?)
                """,
                (filename, staging_path, image_type, exif_timestamp, file_size),
            )
            return cursor.lastrowid

    def update_image_status(self, image_id: int, status: str, error_message: Optional[str] = None):
        """Update image status."""
        with self.transaction() as conn:
            if status == "uploaded":
                conn.execute(
                    """
                    UPDATE images
                    SET status = ?, upload_timestamp = CURRENT_TIMESTAMP, error_message = ?
                    WHERE id = ?
                    """,
                    (status, error_message, image_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE images
                    SET status = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (status, error_message, image_id),
                )

    def increment_retry_count(self, image_id: int):
        """Increment retry count for an image."""
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE images
                SET retry_count = retry_count + 1
                WHERE id = ?
                """,
                (image_id,),
            )

    def get_staged_images(self) -> List[Dict[str, Any]]:
        """Get all staged images ordered by EXIF timestamp."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT id, filename, staging_path, image_type, exif_timestamp, file_size, retry_count
                FROM images
                WHERE status = 'staged'
                ORDER BY exif_timestamp ASC NULLS LAST, add_timestamp ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_failed_images(self) -> List[Dict[str, Any]]:
        """Get all failed images."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT id, filename, staging_path, image_type, retry_count, error_message, add_timestamp
                FROM images
                WHERE status = 'failed'
                ORDER BY add_timestamp DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_image_counts(self) -> Dict[str, int]:
        """Get counts of images by status."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM images
                GROUP BY status
                """
            )
            counts = {row["status"]: row["count"] for row in cursor.fetchall()}
            return {
                "staged": counts.get("staged", 0),
                "uploading": counts.get("uploading", 0),
                "uploaded": counts.get("uploaded", 0),
                "failed": counts.get("failed", 0),
            }

    def add_staging_failure(
        self, filename: str, sd_card_path: str, error_message: str, retry_attempts: int
    ):
        """Record a staging failure."""
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO staging_failures (filename, sd_card_path, error_message, retry_attempts)
                VALUES (?, ?, ?, ?)
                """,
                (filename, sd_card_path, error_message, retry_attempts),
            )

    def get_staging_failures(self) -> List[Dict[str, Any]]:
        """Get all staging failures."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT filename, sd_card_path, error_message, retry_attempts, timestamp
                FROM staging_failures
                ORDER BY timestamp DESC
                LIMIT 100
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def add_upload_stat(self, bytes_uploaded: int, duration_seconds: float, active_workers: int):
        """Record upload statistics."""
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO upload_stats (bytes_uploaded, duration_seconds, active_workers)
                VALUES (?, ?, ?)
                """,
                (bytes_uploaded, duration_seconds, active_workers),
            )

    def get_upload_stats(self, hours: int) -> List[Dict[str, Any]]:
        """Get upload statistics for the last N hours."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT timestamp, bytes_uploaded, duration_seconds, active_workers
                FROM upload_stats
                WHERE timestamp >= datetime('now', ? || ' hours')
                ORDER BY timestamp ASC
                """,
                (f"-{hours}",),
            )
            return [dict(row) for row in cursor.fetchall()]

    def set_config(self, key: str, value: Any):
        """Set a configuration value."""
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO config (key, value)
                VALUES (?, ?)
                """,
                (key, json.dumps(value)),
            )

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT value FROM config WHERE key = ?
                """,
                (key,),
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row["value"])
            return default

    def delete_uploaded_image_record(self, image_id: int):
        """Delete an uploaded image record (for cleanup)."""
        with self.transaction() as conn:
            conn.execute(
                """
                DELETE FROM images WHERE id = ? AND status = 'uploaded'
                """,
                (image_id,),
            )
