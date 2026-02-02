"""
Main GUI application for DFN image uploader.
"""
import sys
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QListWidget,
    QSpinBox,
    QRadioButton,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextEdit,
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
import psutil
import logging

from .state_manager import StateManager
from .sd_monitor import SDMonitor
from .staging import StagingCopier
from .upload_manager import UploadManager
from .stats_tracker import StatsTracker

logger = logging.getLogger(__name__)


class UploaderWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DFN Image Uploader")
        self.setMinimumSize(900, 700)

        # Initialize components
        self.state_manager = StateManager()
        self.sd_monitor = SDMonitor()
        self.stats_tracker = StatsTracker()
        self.staging_thread = None
        self.upload_thread = None

        # Load config
        self.config_file = Path("config.json")
        self.load_config()

        # Setup UI
        self.setup_ui()

        # Setup timers
        self.sd_check_timer = QTimer()
        self.sd_check_timer.timeout.connect(self.check_sd_cards)
        self.sd_check_timer.start(2000)  # Check every 2 seconds

        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_display_stats)
        self.stats_timer.start(1000)  # Update every second

        # Initial updates
        self.refresh_sd_list()
        self.update_counts()

    def setup_ui(self):
        """Setup the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Configuration section
        config_group = self.create_config_section()
        main_layout.addWidget(config_group)

        # SD Card section
        sd_group = self.create_sd_section()
        main_layout.addWidget(sd_group)

        # Upload control section
        upload_group = self.create_upload_section()
        main_layout.addWidget(upload_group)

        # Statistics section
        stats_group = self.create_stats_section()
        main_layout.addWidget(stats_group)

        # Tabs for errors and logs
        tabs = QTabWidget()
        tabs.addTab(self.create_error_tab(), "Failed Uploads")
        tabs.addTab(self.create_log_tab(), "Activity Log")
        main_layout.addWidget(tabs)

    def create_config_section(self):
        """Create configuration section."""
        group = QGroupBox("Configuration")
        layout = QVBoxLayout()

        # Upload key
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel("Upload Key:"))
        self.upload_key_edit = QLineEdit()
        self.upload_key_edit.setText(self.config.get("upload_key", ""))
        self.upload_key_edit.textChanged.connect(self.save_config)
        key_layout.addWidget(self.upload_key_edit)
        layout.addLayout(key_layout)

        # Staging directory
        staging_layout = QHBoxLayout()
        staging_layout.addWidget(QLabel("Staging Directory:"))
        self.staging_dir_edit = QLineEdit()
        self.staging_dir_edit.setText(self.config.get("staging_dir", str(Path.home() / "staging")))
        self.staging_dir_edit.setReadOnly(True)
        staging_layout.addWidget(self.staging_dir_edit)
        staging_btn = QPushButton("Browse...")
        staging_btn.clicked.connect(self.browse_staging_dir)
        staging_layout.addWidget(staging_btn)
        self.staging_space_label = QLabel()
        staging_layout.addWidget(self.staging_space_label)
        layout.addLayout(staging_layout)
        self.update_staging_space()

        # Concurrency mode
        concurrency_layout = QHBoxLayout()
        concurrency_layout.addWidget(QLabel("Upload Concurrency:"))

        self.auto_radio = QRadioButton("Auto-optimize")
        self.manual_radio = QRadioButton("Manual")
        self.concurrency_group = QButtonGroup()
        self.concurrency_group.addButton(self.auto_radio)
        self.concurrency_group.addButton(self.manual_radio)

        concurrency_mode = self.config.get("concurrency_mode", "auto")
        if concurrency_mode == "auto":
            self.auto_radio.setChecked(True)
        else:
            self.manual_radio.setChecked(True)

        self.auto_radio.toggled.connect(self.save_config)
        concurrency_layout.addWidget(self.auto_radio)
        concurrency_layout.addWidget(self.manual_radio)

        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 10)
        self.worker_spin.setValue(self.config.get("concurrency_value", 3))
        self.worker_spin.setEnabled(self.manual_radio.isChecked())
        self.worker_spin.valueChanged.connect(self.save_config)
        self.manual_radio.toggled.connect(lambda: self.worker_spin.setEnabled(self.manual_radio.isChecked()))
        concurrency_layout.addWidget(self.worker_spin)
        concurrency_layout.addWidget(QLabel("workers"))
        concurrency_layout.addStretch()
        layout.addLayout(concurrency_layout)

        group.setLayout(layout)
        return group

    def create_sd_section(self):
        """Create SD card section."""
        group = QGroupBox("SD Card Staging")
        layout = QVBoxLayout()

        # SD card list
        list_layout = QHBoxLayout()
        list_layout.addWidget(QLabel("Detected SD Cards:"))
        self.sd_list = QListWidget()
        self.sd_list.setMaximumHeight(80)
        list_layout.addWidget(self.sd_list)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_sd_list)
        list_layout.addWidget(refresh_btn)
        layout.addLayout(list_layout)

        # Image type and copy button
        action_layout = QHBoxLayout()
        action_layout.addWidget(QLabel("Image Type:"))
        self.image_type_combo = QComboBox()
        self.image_type_combo.addItems(["survey", "training_true", "training_false"])
        action_layout.addWidget(self.image_type_combo)

        self.copy_btn = QPushButton("Copy Images from SD Card")
        self.copy_btn.clicked.connect(self.start_sd_copy)
        action_layout.addWidget(self.copy_btn)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        # Progress
        progress_layout = QHBoxLayout()
        self.staging_progress = QProgressBar()
        progress_layout.addWidget(self.staging_progress)
        self.staging_status_label = QLabel()
        progress_layout.addWidget(self.staging_status_label)
        layout.addLayout(progress_layout)

        group.setLayout(layout)
        return group

    def create_upload_section(self):
        """Create upload control section."""
        group = QGroupBox("Upload Control")
        layout = QVBoxLayout()

        # Control buttons
        btn_layout = QHBoxLayout()
        self.upload_start_btn = QPushButton("Start Upload")
        self.upload_start_btn.clicked.connect(self.start_upload)
        btn_layout.addWidget(self.upload_start_btn)

        self.upload_pause_btn = QPushButton("Pause")
        self.upload_pause_btn.clicked.connect(self.pause_upload)
        self.upload_pause_btn.setEnabled(False)
        btn_layout.addWidget(self.upload_pause_btn)

        self.upload_stop_btn = QPushButton("Stop")
        self.upload_stop_btn.clicked.connect(self.stop_upload)
        self.upload_stop_btn.setEnabled(False)
        btn_layout.addWidget(self.upload_stop_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Current status
        status_layout = QHBoxLayout()
        self.current_file_label = QLabel("Ready")
        status_layout.addWidget(self.current_file_label)
        self.workers_label = QLabel("")
        status_layout.addWidget(self.workers_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        # Progress bar
        self.upload_progress = QProgressBar()
        layout.addWidget(self.upload_progress)

        # Counts
        counts_layout = QHBoxLayout()
        self.uploaded_label = QLabel("Uploaded: 0")
        counts_layout.addWidget(self.uploaded_label)
        self.pending_label = QLabel("Pending: 0")
        counts_layout.addWidget(self.pending_label)
        self.failed_label = QLabel("Failed: 0")
        counts_layout.addWidget(self.failed_label)
        counts_layout.addStretch()
        layout.addLayout(counts_layout)

        group.setLayout(layout)
        return group

    def create_stats_section(self):
        """Create statistics section."""
        group = QGroupBox("Upload Statistics")
        layout = QHBoxLayout()

        # Create labels with larger font
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)

        self.instant_rate_label = QLabel("--")
        self.instant_rate_label.setFont(font)
        rate_layout = QVBoxLayout()
        rate_layout.addWidget(QLabel("Instantaneous"))
        rate_layout.addWidget(self.instant_rate_label)
        layout.addLayout(rate_layout)

        self.avg_1h_label = QLabel("--")
        self.avg_1h_label.setFont(font)
        avg1_layout = QVBoxLayout()
        avg1_layout.addWidget(QLabel("1 Hour Avg"))
        avg1_layout.addWidget(self.avg_1h_label)
        layout.addLayout(avg1_layout)

        self.avg_12h_label = QLabel("--")
        self.avg_12h_label.setFont(font)
        avg12_layout = QVBoxLayout()
        avg12_layout.addWidget(QLabel("12 Hour Avg"))
        avg12_layout.addWidget(self.avg_12h_label)
        layout.addLayout(avg12_layout)

        self.eta_label = QLabel("--")
        self.eta_label.setFont(font)
        eta_layout = QVBoxLayout()
        eta_layout.addWidget(QLabel("ETA"))
        eta_layout.addWidget(self.eta_label)
        layout.addLayout(eta_layout)

        self.total_label = QLabel("--")
        self.total_label.setFont(font)
        total_layout = QVBoxLayout()
        total_layout.addWidget(QLabel("Total Uploaded"))
        total_layout.addWidget(self.total_label)
        layout.addLayout(total_layout)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def create_error_tab(self):
        """Create failed uploads tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.error_table = QTableWidget()
        self.error_table.setColumnCount(5)
        self.error_table.setHorizontalHeaderLabels(
            ["Filename", "Type", "Attempts", "Error", "Timestamp"]
        )
        self.error_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.error_table)

        btn_layout = QHBoxLayout()
        retry_btn = QPushButton("Retry Selected")
        retry_btn.clicked.connect(self.retry_failed)
        btn_layout.addWidget(retry_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_error_table)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return widget

    def create_log_tab(self):
        """Create activity log tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        return widget

    def load_config(self):
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    self.config = json.load(f)
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                self.config = {}
        else:
            self.config = {}

    def save_config(self):
        """Save configuration to file."""
        self.config["upload_key"] = self.upload_key_edit.text()
        self.config["staging_dir"] = self.staging_dir_edit.text()
        self.config["concurrency_mode"] = "auto" if self.auto_radio.isChecked() else "manual"
        self.config["concurrency_value"] = self.worker_spin.value()

        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving config: {e}")

    def browse_staging_dir(self):
        """Browse for staging directory."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Staging Directory", self.staging_dir_edit.text()
        )
        if directory:
            self.staging_dir_edit.setText(directory)
            self.save_config()
            self.update_staging_space()

    def update_staging_space(self):
        """Update staging directory space label."""
        staging_dir = self.staging_dir_edit.text()
        try:
            if Path(staging_dir).exists():
                usage = psutil.disk_usage(staging_dir)
                free_gb = usage.free / (1024**3)
                self.staging_space_label.setText(f"({free_gb:.1f} GB free)")
            else:
                self.staging_space_label.setText("(directory does not exist)")
        except Exception as e:
            self.staging_space_label.setText("(error)")

    def check_sd_cards(self):
        """Check for SD card changes."""
        changes = self.sd_monitor.check_for_changes()

        if changes["added"]:
            for card in changes["added"]:
                msg = f"SD card detected: {card.path}\n"
                msg += f"Capacity: {card.total_gb:.1f} GB\n"
                msg += f"Images: ~{card.count_images()}"
                self.log(msg)
                self.refresh_sd_list()

        if changes["removed"]:
            for card in changes["removed"]:
                self.log(f"SD card removed: {card.path}")
                self.refresh_sd_list()

    def refresh_sd_list(self):
        """Refresh SD card list."""
        self.sd_list.clear()
        cards = self.sd_monitor.get_sd_cards()
        for card in cards:
            item_text = f"{card.path} ({card.total_gb:.1f} GB, ~{card.count_images()} images)"
            self.sd_list.addItem(item_text)

    def start_sd_copy(self):
        """Start copying images from SD card."""
        # Validate
        if not self.sd_list.currentItem():
            QMessageBox.warning(self, "No SD Card", "Please select an SD card from the list.")
            return

        staging_dir = Path(self.staging_dir_edit.text())
        if not staging_dir.exists():
            try:
                staging_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not create staging directory: {e}")
                return

        # Get selected SD card
        cards = self.sd_monitor.get_sd_cards()
        selected_idx = self.sd_list.currentRow()
        if selected_idx >= len(cards):
            QMessageBox.warning(self, "Error", "Selected SD card no longer available.")
            return

        sd_card = cards[selected_idx]

        # Confirmation dialog
        image_type = self.image_type_combo.currentText()
        msg = f"Copy images from SD card?\n\n"
        msg += f"Source: {sd_card.path}\n"
        msg += f"Destination: {staging_dir}\n"
        msg += f"Image Type: {image_type}\n"
        msg += f"Estimated images: {sd_card.count_images()}"

        reply = QMessageBox.question(
            self, "Confirm Copy", msg, QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Start staging thread
        self.staging_thread = StagingCopier(
            sd_card.path, staging_dir, image_type, self.state_manager
        )
        self.staging_thread.progress.connect(self.on_staging_progress)
        self.staging_thread.speed_update.connect(self.on_staging_speed)
        self.staging_thread.finished.connect(self.on_staging_finished)
        self.staging_thread.error.connect(self.on_staging_error)
        self.staging_thread.disk_space_warning.connect(self.on_disk_space_warning)
        self.staging_thread.disk_space_critical.connect(self.on_disk_space_critical)

        self.copy_btn.setEnabled(False)
        self.staging_progress.setValue(0)
        self.staging_thread.start()
        self.log(f"Started copying images from {sd_card.path}")

    def on_staging_progress(self, current, total, filename):
        """Handle staging progress update."""
        self.staging_progress.setMaximum(total)
        self.staging_progress.setValue(current)
        self.staging_status_label.setText(f"{current}/{total}: {filename}")

    def on_staging_speed(self, bytes_per_sec):
        """Handle staging speed update."""
        speed_str = self.stats_tracker.format_rate(bytes_per_sec)
        # Could update UI with speed if desired

    def on_staging_finished(self, successful, failed):
        """Handle staging completion."""
        self.copy_btn.setEnabled(True)
        self.staging_progress.setValue(0)
        self.staging_status_label.setText("")

        msg = f"Staging completed!\n"
        msg += f"Successful: {successful}\n"
        msg += f"Failed: {failed}"
        QMessageBox.information(self, "Staging Complete", msg)
        self.log(f"Staging completed: {successful} successful, {failed} failed")

        # Update counts
        self.update_counts()

    def on_staging_error(self, filename, error):
        """Handle staging error."""
        self.log(f"Error staging {filename}: {error}")

    def on_disk_space_warning(self, gb_remaining):
        """Handle disk space warning."""
        msg = f"Warning: Only {gb_remaining:.1f} GB remaining on staging disk!"
        QMessageBox.warning(self, "Low Disk Space", msg)
        self.log(msg)

    def on_disk_space_critical(self, gb_remaining):
        """Handle critical disk space."""
        msg = f"Critical: Only {gb_remaining:.1f} GB remaining! Stopping copy."
        QMessageBox.critical(self, "Critical Disk Space", msg)
        self.log(msg)

    def start_upload(self):
        """Start uploading."""
        upload_key = self.upload_key_edit.text().strip()
        if not upload_key:
            QMessageBox.warning(self, "No Upload Key", "Please enter an upload key.")
            return

        # Check if there are images to upload
        counts = self.state_manager.get_image_counts()
        if counts.get("staged", 0) == 0:
            QMessageBox.information(
                self, "No Images", "No staged images to upload. Please copy images from an SD card first."
            )
            return

        # Start upload thread
        self.upload_thread = UploadManager(
            upload_key, self.state_manager, self.stats_tracker
        )

        # Set concurrency mode
        if self.auto_radio.isChecked():
            self.upload_thread.set_auto_optimize(True)
        else:
            self.upload_thread.set_manual_workers(self.worker_spin.value())

        # Connect signals
        self.upload_thread.upload_started.connect(self.on_upload_started)
        self.upload_thread.upload_completed.connect(self.on_upload_completed)
        self.upload_thread.upload_failed.connect(self.on_upload_failed)
        self.upload_thread.progress_update.connect(self.on_upload_progress)
        self.upload_thread.stats_update.connect(self.on_stats_update)
        self.upload_thread.worker_count_changed.connect(self.on_worker_count_changed)
        self.upload_thread.finished.connect(self.on_upload_finished)

        self.upload_start_btn.setEnabled(False)
        self.upload_pause_btn.setEnabled(True)
        self.upload_stop_btn.setEnabled(True)

        self.upload_thread.start()
        self.log("Started upload")

    def pause_upload(self):
        """Pause/resume upload."""
        if self.upload_thread:
            if self.upload_pause_btn.text() == "Pause":
                self.upload_thread.pause()
                self.upload_pause_btn.setText("Resume")
                self.log("Upload paused")
            else:
                self.upload_thread.resume()
                self.upload_pause_btn.setText("Pause")
                self.log("Upload resumed")

    def stop_upload(self):
        """Stop upload."""
        if self.upload_thread:
            self.upload_thread.stop()
            self.log("Stopping upload...")

    def on_upload_started(self, filename):
        """Handle upload started."""
        self.current_file_label.setText(f"Uploading: {filename}")

    def on_upload_completed(self, filename, bytes_uploaded):
        """Handle upload completed."""
        self.log(f"Uploaded: {filename}")
        self.update_counts()

    def on_upload_failed(self, filename, error):
        """Handle upload failed."""
        self.log(f"Failed: {filename} - {error}")
        self.update_counts()

    def on_upload_progress(self, uploaded, total):
        """Handle upload progress."""
        self.upload_progress.setMaximum(total)
        self.upload_progress.setValue(uploaded)

    def on_stats_update(self, stats):
        """Handle statistics update."""
        # These are updated by the timer

    def on_worker_count_changed(self, count):
        """Handle worker count change."""
        if self.auto_radio.isChecked():
            self.workers_label.setText(f"Workers: {count} (auto)")

    def on_upload_finished(self):
        """Handle upload finished."""
        self.upload_start_btn.setEnabled(True)
        self.upload_pause_btn.setEnabled(False)
        self.upload_pause_btn.setText("Pause")
        self.upload_stop_btn.setEnabled(False)
        self.current_file_label.setText("Upload completed")
        self.workers_label.setText("")
        self.log("Upload finished")
        self.update_counts()

    def update_counts(self):
        """Update image counts."""
        counts = self.state_manager.get_image_counts()
        self.uploaded_label.setText(f"Uploaded: {counts.get('uploaded', 0)}")
        self.pending_label.setText(f"Pending: {counts.get('staged', 0)}")
        self.failed_label.setText(f"Failed: {counts.get('failed', 0)}")

    def update_display_stats(self):
        """Update statistics display."""
        instant = self.stats_tracker.get_instantaneous_rate()
        avg_1h = self.stats_tracker.get_average_rate(1)
        avg_12h = self.stats_tracker.get_average_rate(12)

        self.instant_rate_label.setText(self.stats_tracker.format_rate(instant))
        self.avg_1h_label.setText(self.stats_tracker.format_rate(avg_1h))
        self.avg_12h_label.setText(self.stats_tracker.format_rate(avg_12h))

        # Calculate ETA
        counts = self.state_manager.get_image_counts()
        if counts.get("staged", 0) > 0:
            # Estimate remaining bytes (rough estimate)
            staged_images = self.state_manager.get_staged_images()
            remaining_bytes = sum(img.get("file_size", 0) for img in staged_images)
            eta_seconds = self.stats_tracker.estimate_time_remaining(remaining_bytes, 12)
            self.eta_label.setText(self.stats_tracker.format_time(eta_seconds))
        else:
            self.eta_label.setText("--")

        # Total uploaded
        total_bytes = self.stats_tracker.total_bytes_uploaded
        self.total_label.setText(self.stats_tracker.format_size(total_bytes))

        # Update staging space periodically
        self.update_staging_space()

    def refresh_error_table(self):
        """Refresh failed uploads table."""
        failed_images = self.state_manager.get_failed_images()
        self.error_table.setRowCount(len(failed_images))

        for row, image in enumerate(failed_images):
            self.error_table.setItem(row, 0, QTableWidgetItem(image["filename"]))
            self.error_table.setItem(row, 1, QTableWidgetItem(image["image_type"]))
            self.error_table.setItem(row, 2, QTableWidgetItem(str(image["retry_count"])))
            self.error_table.setItem(row, 3, QTableWidgetItem(image.get("error_message", "")))
            self.error_table.setItem(row, 4, QTableWidgetItem(image["add_timestamp"]))

    def retry_failed(self):
        """Retry selected failed uploads."""
        selected_rows = set(item.row() for item in self.error_table.selectedItems())
        if not selected_rows:
            QMessageBox.information(self, "No Selection", "Please select images to retry.")
            return

        failed_images = self.state_manager.get_failed_images()
        for row in selected_rows:
            if row < len(failed_images):
                image_id = failed_images[row]["id"]
                self.state_manager.update_image_status(image_id, "staged")

        self.refresh_error_table()
        self.update_counts()
        self.log(f"Reset {len(selected_rows)} failed images to staged")

    def log(self, message):
        """Add message to activity log."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        logger.info(message)

    def closeEvent(self, event):
        """Handle window close."""
        # Stop threads if running
        if self.staging_thread and self.staging_thread.isRunning():
            self.staging_thread.stop()
            self.staging_thread.wait()

        if self.upload_thread and self.upload_thread.isRunning():
            self.upload_thread.stop()
            self.upload_thread.wait()

        event.accept()
