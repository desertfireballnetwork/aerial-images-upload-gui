"""
Main GUI application for DFN image uploader.

Field-optimised UX: high-contrast dark/light themes, large touch targets,
numbered wizard-step layout, plain-English instructions.
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
    QFrame,
    QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QColor
import psutil
import logging

from .state_manager import StateManager
from .sd_monitor import SDMonitor
from .staging import StagingCopier
from .upload_manager import UploadManager
from .stats_tracker import StatsTracker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Theme / Stylesheet
# ---------------------------------------------------------------------------

# Colour tokens — referenced by both palettes
_COLORS = {
    "primary": "#0A84FF",
    "primary_hover": "#409CFF",
    "success": "#30D158",
    "success_hover": "#4ADE80",
    "warning": "#FF9F0A",
    "warning_hover": "#FFB340",
    "danger": "#FF453A",
    "danger_hover": "#FF6961",
}

_DARK = {
    "bg": "#18181B",
    "surface": "#27272A",
    "surface_alt": "#3F3F46",
    "border": "#71717A",
    "text": "#FAFAFA",
    "text_muted": "#A1A1AA",
    "input_bg": "#111113",
    "progressbar_bg": "#111113",
    "banner_bg": "#27272A",
    "tab_bg": "#27272A",
    "tab_selected": "#3F3F46",
    "scrollbar_bg": "#27272A",
    "scrollbar_handle": "#71717A",
    **_COLORS,
}

_LIGHT = {
    "bg": "#F2F2F7",
    "surface": "#FFFFFF",
    "surface_alt": "#E5E5EA",
    "border": "#C7C7CC",
    "text": "#1C1C1E",
    "text_muted": "#636366",
    "input_bg": "#FFFFFF",
    "progressbar_bg": "#D1D1D6",
    "banner_bg": "#E5E5EA",
    "tab_bg": "#FFFFFF",
    "tab_selected": "#E5E5EA",
    "scrollbar_bg": "#E5E5EA",
    "scrollbar_handle": "#AEAEB2",
    **_COLORS,
}

# Banner colour map — keys are banner state names
_BANNER_COLORS = {
    "READY": {"dark": "#48484A", "light": "#C7C7CC"},
    "COPYING": {"dark": "#0A84FF", "light": "#0A84FF"},
    "DONE_COPYING": {"dark": "#30D158", "light": "#30D158"},
    "UPLOADING": {"dark": "#0A84FF", "light": "#0A84FF"},
    "PAUSED": {"dark": "#FF9F0A", "light": "#FF9F0A"},
    "COMPLETE": {"dark": "#30D158", "light": "#30D158"},
}

_BANNER_TEXT = {
    "READY": "Ready — Insert an SD card and follow the steps below",
    "COPYING": "Copying images from SD card… please wait",
    "DONE_COPYING": "Copy complete — you can now start the upload (Step 3)",
    "UPLOADING": "Uploading images to the server…",
    "PAUSED": "Upload paused — press Resume to continue",
    "COMPLETE": "All images uploaded successfully!",
}


def _build_stylesheet(p: dict) -> str:
    """Build a full QSS string from a palette dict *p*."""
    return f"""
    /* ---- Global ---- */
    QWidget {{
        background-color: {p['bg']};
        color: {p['text']};
    }}
    QMainWindow {{
        background-color: {p['bg']};
    }}
    QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
        background-color: {p['bg']};
        border: none;
    }}

    /* Text-bearing widgets should be transparent so the panel behind shows through */
    QLabel, QRadioButton, QCheckBox, QGroupBox::title {{
        background-color: transparent;
    }}

    /* ---- Group boxes (steps) ---- */
    QGroupBox {{
        background-color: {p['surface']};
        border: 2px solid {p['border']};
        border-radius: 8px;
        margin-top: 18px;
        padding: 10px 10px 8px 10px;
        font-size: 11pt;
        font-weight: bold;
        color: {p['text']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 2px 6px;
        background-color: transparent;
        color: {p['text']};
    }}

    /* ---- Labels ---- */
    QLabel {{
        color: {p['text']};
        font-size: 10pt;
    }}
    QLabel[objectName="help_text"] {{
        color: {p['text_muted']};
        font-size: 9pt;
        font-style: italic;
        padding: 1px 0 4px 0;
    }}
    QLabel[objectName="status_banner"] {{
        font-size: 12pt;
        font-weight: bold;
        padding: 8px;
        border-radius: 6px;
        color: #FFFFFF;
    }}
    QLabel[objectName="stat_header"] {{
        font-size: 9pt;
        color: {p['text_muted']};
        font-weight: normal;
    }}
    QLabel[objectName="stat_value"] {{
        font-size: 13pt;
        font-weight: bold;
        color: {p['text']};
    }}
    QLabel[objectName="staging_speed_label"] {{
        font-size: 9pt;
        color: {p['text_muted']};
    }}

    /* ---- Inputs ---- */
    QLineEdit, QComboBox {{
        background-color: {p['input_bg']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 5px;
        min-height: 26px;
        font-size: 10pt;
        padding: 2px 6px;
    }}
    QLineEdit:focus, QComboBox:focus {{
        border-color: {p['primary']};
    }}
    QComboBox::drop-down {{
        border: none;
        padding-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p['surface']};
        color: {p['text']};
        selection-background-color: {p['primary']};
        selection-color: #FFFFFF;
    }}

    /* ---- Spin box ---- */
    QSpinBox {{
        background-color: {p['input_bg']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 5px;
        min-height: 26px;
        font-size: 10pt;
        padding: 2px 6px;
    }}

    /* ---- Radio buttons ---- */
    QRadioButton {{
        color: {p['text']};
        font-size: 10pt;
        spacing: 6px;
        outline: none;
    }}
    QRadioButton:focus {{
        border: none;
        outline: none;
    }}
    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 8px;
        border: 2px solid {p['border']};
        background-color: {p['input_bg']};
    }}
    QRadioButton::indicator:hover {{
        border-color: {p['primary']};
    }}
    QRadioButton::indicator:checked {{
        background-color: #FFFFFF;
        border: 5px solid {p['primary']};
        border-radius: 9px; /* Force circular shape (half of 16px + borders) */
        image: none;
    }}

    /* ---- Buttons (default / secondary) ---- */
    QPushButton {{
        background-color: {p['surface_alt']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 6px;
        min-height: 30px;
        font-size: 10pt;
        padding: 4px 14px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: {p['border']};
    }}
    QPushButton:pressed {{
        background-color: {p['surface']};
    }}
    QPushButton:disabled {{
        opacity: 0.45;
        color: {p['text_muted']};
    }}

    /* Primary action buttons */
    QPushButton[objectName="copy_btn"] {{
        background-color: {p['primary']};
        color: #FFFFFF;
        border: none;
        min-height: 38px;
        font-size: 11pt;
    }}
    QPushButton[objectName="copy_btn"]:hover {{
        background-color: {p['primary_hover']};
    }}
    QPushButton[objectName="upload_start_btn"] {{
        background-color: {p['success']};
        color: #FFFFFF;
        border: none;
        min-height: 38px;
        font-size: 11pt;
    }}
    QPushButton[objectName="upload_start_btn"]:hover {{
        background-color: {p['success_hover']};
    }}
    QPushButton[objectName="upload_stop_btn"] {{
        background-color: {p['danger']};
        color: #FFFFFF;
        border: none;
    }}
    QPushButton[objectName="upload_stop_btn"]:hover {{
        background-color: {p['danger_hover']};
    }}
    QPushButton[objectName="retry_btn"] {{
        background-color: {p['warning']};
        color: #FFFFFF;
        border: none;
    }}
    QPushButton[objectName="retry_btn"]:hover {{
        background-color: {p['warning_hover']};
    }}
    QPushButton[objectName="theme_toggle_btn"] {{
        background-color: {p['surface_alt']};
        color: {p['text']};
        border: 1px solid {p['border']};
        min-height: 24px;
        font-size: 9pt;
        padding: 2px 10px;
        border-radius: 5px;
    }}
    QPushButton[objectName="theme_toggle_btn"]:hover {{
        background-color: {p['border']};
    }}
    QPushButton[objectName="advanced_toggle_btn"] {{
        min-height: 22px;
        font-size: 8pt;
        font-weight: normal;
        padding: 1px 8px;
        border-radius: 5px;
        color: {p['text_muted']};
        background-color: transparent;
        border: 1px solid {p['border']};
    }}

    /* ---- List widget ---- */
    QListWidget {{
        background-color: {p['input_bg']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 5px;
        font-size: 10pt;
        padding: 2px;
    }}
    QListWidget::item {{
        padding: 4px;
        border-radius: 3px;
    }}
    QListWidget::item:selected {{
        background-color: {p['primary']};
        color: #FFFFFF;
    }}

    /* ---- Progress bars ---- */
    QProgressBar {{
        border: 1px solid {p['border']};
        border-radius: 5px;
        text-align: center;
        min-height: 14px;
        font-size: 9pt;
        font-weight: bold;
        color: {p['text']};
        background-color: {p['progressbar_bg']};
    }}
    QProgressBar::chunk {{
        background-color: {p['success']};
        border-radius: 4px;
    }}

    /* ---- Tab widget ---- */
    QTabWidget::pane {{
        border: 1px solid {p['border']};
        border-radius: 6px;
        background-color: {p['surface']};
        padding: 2px;
    }}
    QTabBar::tab {{
        background-color: {p['tab_bg']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        min-width: 110px;
        min-height: 28px;
        padding: 4px 12px;
        font-size: 10pt;
        font-weight: bold;
    }}
    QTabBar::tab:selected {{
        background-color: {p['tab_selected']};
        border-bottom: 1px solid {p['tab_selected']};
    }}

    /* ---- Table widget ---- */
    QTableWidget {{
        background-color: {p['input_bg']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 5px;
        font-size: 9pt;
        gridline-color: {p['border']};
    }}
    QHeaderView::section {{
        background-color: {p['surface_alt']};
        color: {p['text']};
        border: 1px solid {p['border']};
        padding: 4px;
        font-size: 9pt;
        font-weight: bold;
    }}

    /* ---- Text edit (log) ---- */
    QTextEdit {{
        background-color: {p['input_bg']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 5px;
        font-size: 9pt;
        font-family: "Courier New", "Consolas", "Liberation Mono", monospace;
        padding: 4px;
    }}

    /* ---- Scrollbars ---- */
    QScrollBar:vertical {{
        background: {p['scrollbar_bg']};
        width: 10px;
        border-radius: 5px;
    }}
    QScrollBar::handle:vertical {{
        background: {p['scrollbar_handle']};
        min-height: 24px;
        border-radius: 5px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: {p['scrollbar_bg']};
        height: 10px;
        border-radius: 5px;
    }}
    QScrollBar::handle:horizontal {{
        background: {p['scrollbar_handle']};
        min-width: 24px;
        border-radius: 5px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ---- Separator ---- */
    QFrame[objectName="separator"] {{
        color: {p['border']};
        max-height: 2px;
    }}
    """


DARK_STYLESHEET = _build_stylesheet(_DARK)
LIGHT_STYLESHEET = _build_stylesheet(_LIGHT)


def apply_stylesheet(app_or_widget, dark: bool = True):
    """Apply the high-contrast dark or light stylesheet."""
    app_or_widget.setStyleSheet(DARK_STYLESHEET if dark else LIGHT_STYLESHEET)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------


class UploaderWindow(QMainWindow):
    """Main application window — field-optimised wizard layout."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DFN Image Uploader")
        self.setMinimumSize(860, 620)

        # Initialize components
        self.state_manager = StateManager()
        self.sd_monitor = SDMonitor()
        self.stats_tracker = StatsTracker()
        self.staging_thread = None
        self.upload_thread = None

        # Theme state (default dark)
        self._dark_mode = True

        # Load config
        self.config_file = Path("config.json")
        self.load_config()

        # Setup UI
        self.setup_ui()

        # Apply theme from config
        self._dark_mode = self.config.get("dark_mode", True)
        self._apply_current_theme()

        # Setup timers
        self.sd_check_timer = QTimer()
        self.sd_check_timer.timeout.connect(self.check_sd_cards)
        self.sd_check_timer.start(2000)

        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_display_stats)
        self.stats_timer.start(1000)

        # Initial updates
        self.refresh_sd_list()
        self.update_counts()
        self.set_banner_state("READY")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def setup_ui(self):
        """Build the wizard-step interface."""
        central_widget = QWidget()
        central_widget.setObjectName("central")
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(12, 6, 12, 6)

        # -- Top bar: banner + theme toggle --
        top_bar = QHBoxLayout()
        self.status_banner = QLabel("")
        self.status_banner.setObjectName("status_banner")
        self.status_banner.setAlignment(Qt.AlignCenter)
        self.status_banner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        top_bar.addWidget(self.status_banner, stretch=1)

        self.theme_toggle_btn = QPushButton("☀  Light Mode")
        self.theme_toggle_btn.setObjectName("theme_toggle_btn")
        self.theme_toggle_btn.setToolTip("Switch between dark and light mode")
        self.theme_toggle_btn.clicked.connect(self.toggle_theme)
        self.theme_toggle_btn.setFixedWidth(150)
        top_bar.addWidget(self.theme_toggle_btn)
        main_layout.addLayout(top_bar)

        # Use a scroll area so the layout never clips on smaller screens
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(6)
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, stretch=1)

        # STEP 1 — Setup
        step1 = self._create_step1()
        scroll_layout.addWidget(step1)

        # STEP 2 — Copy from SD Card
        step2 = self._create_step2()
        scroll_layout.addWidget(step2)

        # STEP 3 — Upload to Server
        step3 = self._create_step3()
        scroll_layout.addWidget(step3)

        # Tabs for errors and logs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_error_tab(), "Failed Uploads")
        self.tabs.addTab(self._create_log_tab(), "Activity Log")
        scroll_layout.addWidget(self.tabs)

    # ---- Step 1: Setup -------------------------------------------------

    def _create_step1(self):
        group = QGroupBox("STEP 1 — Setup")
        layout = QVBoxLayout()
        layout.setSpacing(6)

        help_label = QLabel(
            "Enter your Upload Key and choose a folder on your laptop for temporary image storage. "
            "You can find your Upload Key on the survey's Parameters page of the DFN web portal."
        )
        help_label.setObjectName("help_text")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # Upload Key (field: upload_key on Survey model in the webapp)
        key_layout = QHBoxLayout()
        key_lbl = QLabel("Upload Key:")
        key_layout.addWidget(key_lbl)
        self.upload_key_edit = QLineEdit()
        self.upload_key_edit.setPlaceholderText("Paste your Upload Key here")
        self.upload_key_edit.setText(self.config.get("upload_key", ""))
        self.upload_key_edit.textChanged.connect(self.save_config)
        self.upload_key_edit.setToolTip(
            "Your Upload Key from the DFN web portal — find it on the survey's Parameters page. Required to upload."
        )
        key_layout.addWidget(self.upload_key_edit)
        layout.addLayout(key_layout)

        # Local storage folder (was "Staging Directory")
        staging_layout = QHBoxLayout()
        staging_layout.addWidget(QLabel("Local Storage Folder:"))
        self.staging_dir_edit = QLineEdit()
        self.staging_dir_edit.setText(self.config.get("staging_dir", str(Path.home() / "staging")))
        self.staging_dir_edit.setReadOnly(True)
        self.staging_dir_edit.setToolTip("Images are temporarily saved here before upload.")
        staging_layout.addWidget(self.staging_dir_edit)

        self.staging_browse_btn = QPushButton("Browse…")
        self.staging_browse_btn.clicked.connect(self.browse_staging_dir)
        self.staging_browse_btn.setToolTip(
            "Choose a folder on your laptop where images will be temporarily "
            "saved before upload."
        )
        staging_layout.addWidget(self.staging_browse_btn)
        self.staging_space_label = QLabel()
        staging_layout.addWidget(self.staging_space_label)
        layout.addLayout(staging_layout)
        self.update_staging_space()

        group.setLayout(layout)
        return group

    # ---- Step 2: Copy from SD Card ------------------------------------

    def _create_step2(self):
        group = QGroupBox("STEP 2 — Copy from SD Card")
        layout = QVBoxLayout()
        layout.setSpacing(6)

        help_label = QLabel(
            "Insert the SD card from your drone. Wait for it to appear in the list "
            "below, select it, choose the image type, then press Copy."
        )
        help_label.setObjectName("help_text")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # SD card list
        list_layout = QHBoxLayout()
        list_layout.addWidget(QLabel("Detected SD Cards:"))
        self.sd_list = QListWidget()
        self.sd_list.setMinimumHeight(90)
        self.sd_list.setMaximumHeight(120)
        self.sd_list.setToolTip("SD cards plugged into your laptop will appear here automatically.")
        list_layout.addWidget(self.sd_list, stretch=1)

        self.sd_refresh_btn = QPushButton("Refresh")
        self.sd_refresh_btn.clicked.connect(self.refresh_sd_list)
        self.sd_refresh_btn.setToolTip("Re-scan for SD cards")
        list_layout.addWidget(self.sd_refresh_btn)
        layout.addLayout(list_layout)

        # Image type
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Image Type:"))
        self.image_type_combo = QComboBox()
        self.image_type_combo.addItems(
            [
                "survey",
                "training_true",
                "training_false",
            ]
        )
        self.image_type_combo.setToolTip("Choose what kind of flight this SD card is from.")
        type_layout.addWidget(self.image_type_combo)
        self.image_type_desc = QLabel("Survey flight images")
        self.image_type_desc.setObjectName("help_text")
        type_layout.addWidget(self.image_type_desc)
        type_layout.addStretch()
        layout.addLayout(type_layout)
        self.image_type_combo.currentTextChanged.connect(self._update_image_type_desc)

        # Copy button — full width, primary action colour
        self.copy_btn = QPushButton("📋  Copy Images from SD Card")
        self.copy_btn.setObjectName("copy_btn")
        self.copy_btn.clicked.connect(self.start_sd_copy)
        self.copy_btn.setToolTip("Copies all images from the selected SD card to your laptop.")
        layout.addWidget(self.copy_btn)

        # Progress
        self.staging_progress = QProgressBar()
        layout.addWidget(self.staging_progress)

        prog_info = QHBoxLayout()
        self.staging_status_label = QLabel()
        self.staging_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        prog_info.addWidget(self.staging_status_label, stretch=1)
        self.staging_speed_label = QLabel()
        self.staging_speed_label.setObjectName("staging_speed_label")
        self.staging_speed_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        prog_info.addWidget(self.staging_speed_label)
        layout.addLayout(prog_info)

        group.setLayout(layout)
        return group

    # ---- Step 3: Upload to Server -------------------------------------

    def _create_step3(self):
        group = QGroupBox("STEP 3 — Upload to Server")
        layout = QVBoxLayout()
        layout.setSpacing(6)

        help_label = QLabel(
            "Once images are copied, press Start Upload. You can pause and "
            "resume at any time without losing progress."
        )
        help_label.setObjectName("help_text")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # Start button — full width, success colour
        self.upload_start_btn = QPushButton("▶  Start Upload")
        self.upload_start_btn.setObjectName("upload_start_btn")
        self.upload_start_btn.clicked.connect(self.start_upload)
        self.upload_start_btn.setToolTip("Begins uploading all copied images to the DFN server.")
        layout.addWidget(self.upload_start_btn)

        # Pause / Stop side by side
        ctrl_layout = QHBoxLayout()
        self.upload_pause_btn = QPushButton("⏸  Pause")
        self.upload_pause_btn.clicked.connect(self.pause_upload)
        self.upload_pause_btn.setEnabled(False)
        self.upload_pause_btn.setToolTip(
            "Pauses the upload. No data is lost — you can resume anytime."
        )
        ctrl_layout.addWidget(self.upload_pause_btn)

        self.upload_stop_btn = QPushButton("⏹  Stop")
        self.upload_stop_btn.setObjectName("upload_stop_btn")
        self.upload_stop_btn.clicked.connect(self.stop_upload)
        self.upload_stop_btn.setEnabled(False)
        self.upload_stop_btn.setToolTip(
            "Stops the upload. Images already copied are safe and can be " "uploaded next time."
        )
        ctrl_layout.addWidget(self.upload_stop_btn)
        layout.addLayout(ctrl_layout)

        # Current file label
        self.current_file_label = QLabel("Ready")
        self.current_file_label.setAlignment(Qt.AlignCenter)
        cf_font = QFont()
        cf_font.setPointSize(11)
        self.current_file_label.setFont(cf_font)
        layout.addWidget(self.current_file_label)

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

        # Workers label (auto-mode info)
        self.workers_label = QLabel("")
        self.workers_label.setObjectName("stat_header")
        layout.addWidget(self.workers_label)

        # ---- Statistics sub-section ----
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        stats_title = QLabel("Upload Statistics")
        stats_title.setObjectName("stat_header")
        st_font = QFont()
        st_font.setPointSize(12)
        st_font.setBold(True)
        stats_title.setFont(st_font)
        layout.addWidget(stats_title)

        stats_row = QHBoxLayout()

        for attr, header in [
            ("instant_rate_label", "Speed Now"),
            ("avg_1h_label", "1 Hour Avg"),
            ("avg_12h_label", "12 Hour Avg"),
            ("eta_label", "Time Left"),
            ("total_label", "Total Sent"),
        ]:
            col = QVBoxLayout()
            h = QLabel(header)
            h.setObjectName("stat_header")
            h.setAlignment(Qt.AlignCenter)
            col.addWidget(h)
            v = QLabel("--")
            v.setObjectName("stat_value")
            v.setAlignment(Qt.AlignCenter)
            col.addWidget(v)
            stats_row.addLayout(col)
            setattr(self, attr, v)

        stats_row.addStretch()
        layout.addLayout(stats_row)

        # Advanced settings (collapsed by default)
        self.advanced_toggle_btn = QPushButton("Show Advanced ▾")
        self.advanced_toggle_btn.setObjectName("advanced_toggle_btn")
        self.advanced_toggle_btn.clicked.connect(self._toggle_advanced)
        layout.addWidget(self.advanced_toggle_btn, alignment=Qt.AlignLeft)

        self.advanced_group = QGroupBox("⚙  Advanced Settings")
        adv_layout = QVBoxLayout()
        adv_layout.setSpacing(6)

        concurrency_layout = QHBoxLayout()
        concurrency_layout.setSpacing(10)
        concurrency_layout.addWidget(QLabel("Upload Concurrency:"))

        self.auto_radio = QRadioButton("Auto-optimise")
        self.auto_radio.setToolTip("Automatically adjusts connections based on network speed.")
        self.manual_radio = QRadioButton("Manual:")
        self.manual_radio.setToolTip("Set the number of simultaneous upload connections manually.")
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
        concurrency_layout.addSpacing(16)
        concurrency_layout.addWidget(self.manual_radio)

        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 10)
        self.worker_spin.setFixedWidth(56)
        self.worker_spin.setValue(self.config.get("concurrency_value", 3))
        self.worker_spin.setEnabled(self.manual_radio.isChecked())
        self.worker_spin.valueChanged.connect(self.save_config)
        self.manual_radio.toggled.connect(
            lambda: self.worker_spin.setEnabled(self.manual_radio.isChecked())
        )
        self.worker_spin.setToolTip("Number of simultaneous upload connections (1–10).")
        concurrency_layout.addWidget(self.worker_spin)
        concurrency_layout.addWidget(QLabel("workers"))
        concurrency_layout.addStretch()
        adv_layout.addLayout(concurrency_layout)

        concurrency_hint = QLabel("Auto-optimise is recommended for most connections.")
        concurrency_hint.setObjectName("help_text")
        adv_layout.addWidget(concurrency_hint)

        self.advanced_group.setLayout(adv_layout)
        self.advanced_group.setVisible(False)
        layout.addWidget(self.advanced_group)

        group.setLayout(layout)
        return group

    # ---- Tabs ----------------------------------------------------------

    def _create_error_tab(self):
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
        self.retry_btn = QPushButton("🔄  Retry Selected")
        self.retry_btn.setObjectName("retry_btn")
        self.retry_btn.clicked.connect(self.retry_failed)
        self.retry_btn.setToolTip("Re-queue the selected images so they will be uploaded again.")
        btn_layout.addWidget(self.retry_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_error_table)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return widget

    def _create_log_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        return widget

    # ------------------------------------------------------------------
    # Banner state
    # ------------------------------------------------------------------

    def set_banner_state(self, state: str):
        """Update the top status banner.

        *state* must be one of:
        READY, COPYING, DONE_COPYING, UPLOADING, PAUSED, COMPLETE
        """
        text = _BANNER_TEXT.get(state, state)
        self.status_banner.setText(text)

        palette_key = "dark" if self._dark_mode else "light"
        bg = _BANNER_COLORS.get(state, _BANNER_COLORS["READY"])[palette_key]
        self.status_banner.setStyleSheet(
            f"background-color: {bg}; color: #FFFFFF; "
            f"font-size: 12pt; font-weight: bold; padding: 8px; "
            f"border-radius: 6px;"
        )

    # ------------------------------------------------------------------
    # Theme toggle
    # ------------------------------------------------------------------

    def toggle_theme(self):
        """Switch between dark and light mode."""
        self._dark_mode = not self._dark_mode
        self._apply_current_theme()
        self.save_config()

    def _apply_current_theme(self):
        """Apply the current theme to the application."""
        apply_stylesheet(self, self._dark_mode)
        if self._dark_mode:
            self.theme_toggle_btn.setText("☀  Light Mode")
        else:
            self.theme_toggle_btn.setText("🌙  Dark Mode")
        # Re-apply banner colour for the new palette
        current_text = self.status_banner.text()
        state = "READY"
        for key, txt in _BANNER_TEXT.items():
            if txt == current_text:
                state = key
                break
        self.set_banner_state(state)

    # ------------------------------------------------------------------
    # Advanced panel toggle
    # ------------------------------------------------------------------

    def _toggle_advanced(self):
        """Show / hide the advanced settings panel."""
        visible = not self.advanced_group.isVisible()
        self.advanced_group.setVisible(visible)
        if visible:
            self.advanced_toggle_btn.setText("Hide Advanced ▴")
        else:
            self.advanced_toggle_btn.setText("Show Advanced ▾")

    # ------------------------------------------------------------------
    # Image type description
    # ------------------------------------------------------------------

    def _update_image_type_desc(self, text: str):
        """Update the descriptive label next to the image type combo."""
        descs = {
            "survey": "Survey flight images",
            "training_true": "Training: confirmed meteorite",
            "training_false": "Training: no meteorite",
        }
        self.image_type_desc.setText(descs.get(text, ""))

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

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
        self.config["dark_mode"] = self._dark_mode

        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving config: {e}")

    # ------------------------------------------------------------------
    # Directory browsing / disk space
    # ------------------------------------------------------------------

    def browse_staging_dir(self):
        """Browse for staging directory."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Local Storage Folder", self.staging_dir_edit.text()
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
        except Exception:
            self.staging_space_label.setText("(error)")

    # ------------------------------------------------------------------
    # SD card detection
    # ------------------------------------------------------------------

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
            item_text = f"{card.path}  ({card.total_gb:.1f} GB, " f"~{card.count_images()} images)"
            self.sd_list.addItem(item_text)

    # ------------------------------------------------------------------
    # SD card copy (staging)
    # ------------------------------------------------------------------

    def start_sd_copy(self):
        """Start copying images from SD card."""
        if not self.sd_list.currentItem():
            QMessageBox.warning(
                self,
                "No SD Card Selected",
                "Please select an SD card from the list above before copying.",
            )
            return

        staging_dir = Path(self.staging_dir_edit.text())
        if not staging_dir.exists():
            try:
                staging_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Cannot Create Folder",
                    f"Could not create the local storage folder:\n{e}",
                )
                return

        cards = self.sd_monitor.get_sd_cards()
        selected_idx = self.sd_list.currentRow()
        if selected_idx >= len(cards):
            QMessageBox.warning(
                self,
                "SD Card Unavailable",
                "The selected SD card is no longer available. Try refreshing the list.",
            )
            return

        sd_card = cards[selected_idx]
        image_type = self.image_type_combo.currentText()

        msg = (
            f"Ready to copy images?\n\n"
            f"From:  {sd_card.path}\n"
            f"To:  {staging_dir}\n"
            f"Type:  {image_type}\n"
            f"Images found:  ~{sd_card.count_images()}"
        )
        reply = QMessageBox.question(self, "Confirm Copy", msg, QMessageBox.Yes | QMessageBox.No)
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
        self.set_banner_state("COPYING")
        self.log(f"Started copying images from {sd_card.path}")

    def on_staging_progress(self, current, total, filename):
        """Handle staging progress update."""
        self.staging_progress.setMaximum(total)
        self.staging_progress.setValue(current)
        self.staging_status_label.setText(f"{current}/{total}: {filename}")

    def on_staging_speed(self, bytes_per_sec):
        """Handle staging speed update."""
        speed_str = self.stats_tracker.format_rate(bytes_per_sec)
        self.staging_speed_label.setText(speed_str)

    def on_staging_finished(self, successful, failed):
        """Handle staging completion."""
        self.copy_btn.setEnabled(True)
        self.staging_progress.setValue(0)
        self.staging_status_label.setText("")
        self.staging_speed_label.setText("")

        msg = (
            f"Copy complete!\n\n"
            f"Successful:  {successful}\n"
            f"Failed:  {failed}\n\n"
            f"You can now start the upload in Step 3."
        )
        QMessageBox.information(self, "Copy Complete", msg)
        self.log(f"Staging completed: {successful} successful, {failed} failed")

        self.set_banner_state("DONE_COPYING")
        self.update_counts()

    def on_staging_error(self, filename, error):
        """Handle staging error."""
        self.log(f"Error staging {filename}: {error}")

    def on_disk_space_warning(self, gb_remaining):
        """Handle disk space warning."""
        msg = (
            f"Your laptop is running low on disk space!\n\n"
            f"Only {gb_remaining:.1f} GB remaining.\n"
            f"Consider freeing up space or choosing a different storage folder."
        )
        QMessageBox.warning(self, "Low Disk Space", msg)
        self.log(f"Warning: Only {gb_remaining:.1f} GB remaining on staging disk!")

    def on_disk_space_critical(self, gb_remaining):
        """Handle critical disk space — copy will stop."""
        msg = (
            f"Critically low disk space — copy has been stopped!\n\n"
            f"Only {gb_remaining:.1f} GB remaining.\n"
            f"Free up space before continuing."
        )
        QMessageBox.critical(self, "Disk Space Critical", msg)
        self.log(f"Critical: Only {gb_remaining:.1f} GB remaining! Stopping copy.")

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def start_upload(self):
        """Start uploading."""
        upload_key = self.upload_key_edit.text().strip()
        if not upload_key:
            QMessageBox.warning(
                self,
                "Upload Key Missing",
                "Please enter your Upload Key in Step 1 before uploading.\n\n"
                "You can find it on the survey's Parameters page in the DFN web portal.",
            )
            return

        counts = self.state_manager.get_image_counts()
        if counts.get("staged", 0) == 0:
            QMessageBox.information(
                self,
                "Nothing to Upload",
                "No images have been copied yet. Complete Step 2 first.",
            )
            return

        # Start upload thread
        self.upload_thread = UploadManager(upload_key, self.state_manager, self.stats_tracker)

        if self.auto_radio.isChecked():
            self.upload_thread.set_auto_optimize(True)
        else:
            self.upload_thread.set_manual_workers(self.worker_spin.value())

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
        self.set_banner_state("UPLOADING")
        self.log("Started upload")

    def pause_upload(self):
        """Pause/resume upload."""
        if self.upload_thread:
            if "Pause" in self.upload_pause_btn.text():
                self.upload_thread.pause()
                self.upload_pause_btn.setText("▶  Resume")
                self.set_banner_state("PAUSED")
                self.log("Upload paused")
            else:
                self.upload_thread.resume()
                self.upload_pause_btn.setText("⏸  Pause")
                self.set_banner_state("UPLOADING")
                self.log("Upload resumed")

    def stop_upload(self):
        """Stop upload."""
        if self.upload_thread:
            self.upload_thread.stop()
            self.log("Stopping upload…")

    def on_upload_started(self, filename):
        """Handle upload started."""
        self.current_file_label.setText(f"Uploading: {filename}")

    def on_upload_completed(self, filename, bytes_uploaded):
        """Handle upload completed."""
        self.log(f"Uploaded: {filename}")
        self.update_counts()

    def on_upload_failed(self, filename, error):
        """Handle upload failed."""
        self.log(f"Failed: {filename} — {error}")
        self.update_counts()

    def on_upload_progress(self, uploaded, total):
        """Handle upload progress."""
        self.upload_progress.setMaximum(total)
        self.upload_progress.setValue(uploaded)

    def on_stats_update(self, stats):
        """Handle statistics update."""
        # Display updates are driven by the stats_timer

    def on_worker_count_changed(self, count):
        """Handle worker count change."""
        if self.auto_radio.isChecked():
            self.workers_label.setText(f"Workers: {count} (auto)")

    def on_upload_finished(self):
        """Handle upload finished."""
        self.upload_start_btn.setEnabled(True)
        self.upload_pause_btn.setEnabled(False)
        self.upload_pause_btn.setText("⏸  Pause")
        self.upload_stop_btn.setEnabled(False)
        self.current_file_label.setText("Upload completed")
        self.workers_label.setText("")
        self.set_banner_state("COMPLETE")
        self.log("Upload finished")
        self.update_counts()

    # ------------------------------------------------------------------
    # Image counts & statistics display
    # ------------------------------------------------------------------

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

        # ETA
        counts = self.state_manager.get_image_counts()
        if counts.get("staged", 0) > 0:
            staged_images = self.state_manager.get_staged_images()
            remaining_bytes = sum(img.get("file_size", 0) for img in staged_images)
            eta_seconds = self.stats_tracker.estimate_time_remaining(remaining_bytes, 12)
            self.eta_label.setText(self.stats_tracker.format_time(eta_seconds))
        else:
            self.eta_label.setText("--")

        # Total uploaded
        total_bytes = self.stats_tracker.total_bytes_uploaded
        self.total_label.setText(self.stats_tracker.format_size(total_bytes))

        self.update_staging_space()

    # ------------------------------------------------------------------
    # Error table / retry
    # ------------------------------------------------------------------

    def refresh_error_table(self):
        """Refresh failed uploads table."""
        failed_images = self.state_manager.get_failed_images()
        self.error_table.setRowCount(len(failed_images))

        red_bg = QColor(255, 69, 58, 40)
        for row, image in enumerate(failed_images):
            items = [
                QTableWidgetItem(image["filename"]),
                QTableWidgetItem(image["image_type"]),
                QTableWidgetItem(str(image["retry_count"])),
                QTableWidgetItem(image.get("error_message", "")),
                QTableWidgetItem(image["add_timestamp"]),
            ]
            for col, item in enumerate(items):
                item.setBackground(red_bg)
                self.error_table.setItem(row, col, item)

    def retry_failed(self):
        """Retry selected failed uploads."""
        selected_rows = set(item.row() for item in self.error_table.selectedItems())
        if not selected_rows:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select one or more failed images from the table, " "then press Retry.",
            )
            return

        failed_images = self.state_manager.get_failed_images()
        for row in selected_rows:
            if row < len(failed_images):
                image_id = failed_images[row]["id"]
                self.state_manager.update_image_status(image_id, "staged")

        self.refresh_error_table()
        self.update_counts()
        self.log(f"Reset {len(selected_rows)} failed images to staged")

    # ------------------------------------------------------------------
    # Activity log
    # ------------------------------------------------------------------

    def log(self, message):
        """Add message to activity log."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        logger.info(message)

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        """Handle window close."""
        if self.staging_thread and self.staging_thread.isRunning():
            self.staging_thread.stop()
            self.staging_thread.wait()

        if self.upload_thread and self.upload_thread.isRunning():
            self.upload_thread.stop()
            self.upload_thread.wait()

        event.accept()
