"""
Entry point for DFN image uploader application.
"""

import sys
import logging
from pathlib import Path
from PySide6.QtWidgets import QApplication

from .uploader import UploaderWindow, apply_stylesheet


def setup_logging():
    """Setup logging configuration."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "uploader.log"),
            logging.StreamHandler(),
        ],
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

        window = UploaderWindow()
        window.show()

        return app.exec()

    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
