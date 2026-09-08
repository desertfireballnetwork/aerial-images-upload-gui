"""
PyInstaller entry point (see DEPLOYMENT.md).

PyInstaller runs its target script as a top-level module, which breaks the
relative imports inside src/main.py. Importing src.main as a package here
lets those relative imports resolve normally.
"""

import sys

from src.main import main

if __name__ == "__main__":
    sys.exit(main())
