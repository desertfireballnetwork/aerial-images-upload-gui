"""
Entry point for DFN image uploader application.
"""

import sys
import logging
from logging.handlers import RotatingFileHandler

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .app_paths import log_file_path, resolve_icon_path
from .uploader import UploaderWindow, apply_stylesheet


def setup_logging():
    """Setup logging configuration."""
    handlers = [
        RotatingFileHandler(
            log_file_path(),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
        ),
        logging.StreamHandler(),
    ]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )


def main():
    """Main entry point."""
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        app = QApplication(sys.argv)
        app.setApplicationName("DFN Image Uploader")
        app.setOrganizationName("DFN")
        app.setStyle("Fusion")  # Consistent cross-platform base

        icon_path = resolve_icon_path()
        if icon_path is not None:
            app.setWindowIcon(QIcon(str(icon_path)))

        window = UploaderWindow()
        window.show()

        return app.exec()

    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
