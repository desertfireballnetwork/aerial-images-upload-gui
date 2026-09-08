# Deployment Guide for Drone -> Cloud

This guide covers building platform-specific packages for the Drone -> Cloud application.

## Prerequisites

### All Platforms
- Python 3.10, 3.11, or 3.12 (3.13 is currently blocked by the PySide6 dependency)
- Poetry for dependency management

### Platform-Specific

#### Windows
- PyInstaller
- Visual C++ Redistributable (for PySide6)

#### macOS
- Xcode Command Line Tools
- PyInstaller
- create-dmg (optional, for DMG creation)

#### Linux
- PyInstaller
- binutils (required by PyInstaller to analyze shared libraries)
- appimagetool (downloaded automatically by the build steps below)
- FUSE (for testing AppImages)

## Building

### Install Dependencies

```bash
curl -sSL https://install.python-poetry.org | python3 -
git clone https://github.com/desertfireballnetwork/aerial-images-upload-gui.git
cd aerial-images-upload-gui
poetry install
```

On Linux, also install `binutils` (needed by PyInstaller — see Prerequisites above):
```bash
sudo apt install binutils
```

### Windows Executable

> PyInstaller does not cross-compile: this must be run on an actual Windows machine (or a Windows VM), not on Linux/macOS. Running it on Linux will produce a Linux ELF binary named `DroneToCloud`, not a `.exe`. Also note `--add-data` uses `;` as the separator on Windows but `:` on Linux/macOS.

```bash
# Install PyInstaller
poetry add --group dev pyinstaller

# Build single-file executable
poetry run pyinstaller --name="DroneToCloud" \
    --windowed \
    --onefile \
    --collect-all PySide6 \
    --icon=icon.ico \
    --add-data="icon.ico;." \
    entrypoint.py

# Output will be in dist/DroneToCloud.exe

# Debug build — opens a console window on launch so runtime errors are visible
poetry run pyinstaller --name="DroneToCloud-debug" \
    --onefile \
    --collect-all PySide6 \
    --icon=icon.ico \
    --add-data="icon.ico;." \
    entrypoint.py

# Output will be in dist/DroneToCloud-debug.exe
```

### macOS Application Bundle

```bash
# Install PyInstaller
poetry add --group dev pyinstaller

# Build .app bundle
poetry run pyinstaller --name="DroneToCloud" \
    --windowed \
    --onefile \
    --icon=icon.icns \
    --osx-bundle-identifier=au.csiro.dfn.uploader \
    entrypoint.py

# Output will be in dist/DroneToCloud.app

# Optional: Create DMG
brew install create-dmg
create-dmg \
    --volname "DroneToCloud" \
    --window-pos 200 120 \
    --window-size 600 300 \
    --icon-size 100 \
    --app-drop-link 450 120 \
    "DroneToCloud.dmg" \
    "dist/DroneToCloud.app"
```

### Linux AppImage

The AppImage must be self-contained (no reliance on the target machine having Python/PySide6 installed), so it's built by wrapping a PyInstaller onefile binary with `appimagetool` rather than via `python-appimage`.

```bash
# Install PyInstaller
poetry add --group dev pyinstaller

# 1. Build a self-contained onefile binary (icon is not applicable to
#    PyInstaller on Linux — it's set via the .desktop entry instead)
poetry run pyinstaller --name="DroneToCloud" \
    --onefile \
    --collect-all PySide6 \
    entrypoint.py

# 2. Assemble the AppDir
mkdir -p AppDir/usr/bin
mkdir -p AppDir/usr/share/applications
mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps

cp dist/DroneToCloud AppDir/usr/bin/
cp icon.png AppDir/usr/share/icons/hicolor/256x256/apps/DroneToCloud.png
cp icon.png AppDir/DroneToCloud.png

cat > AppDir/usr/share/applications/DroneToCloud.desktop << EOF
[Desktop Entry]
Type=Application
Name=Drone -> Cloud
Exec=DroneToCloud
Icon=DroneToCloud
Categories=Utility;
EOF
cp AppDir/usr/share/applications/DroneToCloud.desktop AppDir/
ln -s usr/bin/DroneToCloud AppDir/AppRun

# 3. Download appimagetool (not preinstalled on most distros)
curl -L -o appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool

# 4. Build the AppImage
# --appimage-extract-and-run avoids needing FUSE on the build machine
./appimagetool --appimage-extract-and-run AppDir DroneToCloud.AppImage
```

## Testing Builds

### Windows
```cmd
dist\DroneToCloud.exe
dist\DroneToCloud-debug.exe
```

On Windows, file logs are written to `%APPDATA%\DFN\uploader.log` (not next to the executable).

### macOS
```bash
open "dist/DroneToCloud.app"
```

### Linux
```bash
chmod +x DroneToCloud.AppImage
./DroneToCloud.AppImage
```

## Continuous Integration

`.github/workflows/build.yml` runs tests on every push/PR to `main`. Pushing a tag matching `v*.*.*` additionally triggers build jobs for Windows, macOS, and Linux (using GitHub-hosted runners — no cross-compilation needed, see above), then creates a GitHub Release with all three packages attached as assets.

## Code Signing

### Windows
Use SignTool from Windows SDK:
```cmd
signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com dist\DroneToCloud.exe
```

### macOS
```bash
codesign --deep --force --verify --verbose --sign "Developer ID Application: Your Name" "dist/DroneToCloud.app"

# Notarize with Apple
xcrun notarytool submit "DroneToCloud.dmg" --keychain-profile "notarytool-profile" --wait

# Staple notarization ticket
xcrun stapler staple "DroneToCloud.dmg"
```

## Distribution

### GitHub Releases
1. Tag the release: `git tag -a v0.1.0 -m "Release version 0.1.0"`
2. Push the tag: `git push origin v0.1.0`
3. Create GitHub Release and upload platform-specific packages
4. Assets should be named:
   - `DroneToCloud-v0.1.0-Windows.exe`
   - `DroneToCloud-v0.1.0-macOS.dmg`
   - `DroneToCloud-v0.1.0-Linux.AppImage`

## Troubleshooting

### Missing Dependencies
If PyInstaller misses dependencies, add them to the spec file:
```python
hiddenimports=['PySide6.QtCore', 'PySide6.QtWidgets', 'aiohttp', ...]
```

### Large Binary Size
Use PyInstaller's `--exclude-module` to remove unnecessary modules:
```bash
pyinstaller ... --exclude-module matplotlib --exclude-module numpy
```

### Icon Issues
- Windows: Use `.ico` format (256x256 or multiple sizes)
- macOS: Use `.icns` format (1024x1024 recommended)
- Linux: Use `.png` format (256x256 or 512x512)
- App icons (`icon.ico`, `icon.icns`, `icon.png`) are derived from the fireball mark in the webapp navbar SVG (`dfn-meteorite-drone-webapp/webapp/src/static/images/dfn_drone_logo_white.svg` — use only the orange path and grey circle). Regenerate with `rsvg-convert`, then ImageMagick `-trim` to crop to content bounds, then square to `max(w,h)`. Do not use ImageMagick to render the SVG directly (it clips the path).

### Runtime Errors
Enable debug mode:
```bash
pyinstaller ... --debug all
```

Check console output for missing files or modules.

## Version Management

Update version in three places:
1. `pyproject.toml`: `version = "x.y.z"`
2. `src/__init__.py`: `__version__ = "x.y.z"`
3. Git tag: `git tag -a vx.y.z`
