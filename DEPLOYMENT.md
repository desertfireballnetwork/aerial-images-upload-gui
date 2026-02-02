# Deployment Guide for DFN Image Uploader

This guide covers building platform-specific packages for the DFN Image Uploader.

## Prerequisites

### All Platforms
- Python 3.10 or higher
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
- python-appimage or AppImageKit
- FUSE (for testing AppImages)

## Building

### Install Dependencies

```bash
### Install Dependencies

```bash
poetry install
```

### Windows Executable

```bash
# Install PyInstaller
poetry add --group dev pyinstaller

# Build single-file executable
poetry run pyinstaller --name="DFN-Uploader" \
    --windowed \
    --onefile \
    --icon=icon.ico \
    --add-data="icon.ico:." \
    src/main.py

# Output will be in dist/DFN-Uploader.exe
```

### macOS Application Bundle

```bash
# Install PyInstaller
poetry add --group dev pyinstaller

# Build .app bundle
poetry run pyinstaller --name="DFN Uploader" \
    --windowed \
    --onefile \
    --icon=icon.icns \
    --osx-bundle-identifier=au.csiro.dfn.uploader \
    src/main.py

# Output will be in dist/DFN Uploader.app

# Optional: Create DMG
brew install create-dmg
create-dmg \
    --volname "DFN Uploader" \
    --window-pos 200 120 \
    --window-size 600 300 \
    --icon-size 100 \
    --app-drop-link 450 120 \
    "DFN-Uploader.dmg" \
    "dist/DFN Uploader.app"
```

### Linux AppImage

```bash
# Install python-appimage
pip install python-appimage

# Build AppImage
python-appimage build app \
    --python-version 3.10 \
    --linux-tag manylinux2014_x86_64 \
    src/main.py

# Or using AppImageKit
# 1. Create AppDir structure
mkdir -p AppDir/usr/bin
mkdir -p AppDir/usr/share/applications
mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps

# 2. Copy application files
cp -r src AppDir/usr/bin/
cp icon.png AppDir/usr/share/icons/hicolor/256x256/apps/dfn-uploader.png

# 3. Create desktop entry
cat > AppDir/usr/share/applications/dfn-uploader.desktop << EOF
[Desktop Entry]
Type=Application
Name=DFN Uploader
Exec=python -m src.main
Icon=dfn-uploader
Categories=Utility;
EOF

# 4. Build AppImage
appimagetool AppDir DFN-Uploader.AppImage
```

## Testing Builds

### Windows
```cmd
dist\DFN-Uploader.exe
```

### macOS
```bash
open "dist/DFN Uploader.app"
```

### Linux
```bash
chmod +x DFN-Uploader.AppImage
./DFN-Uploader.AppImage
```

## Continuous Integration

GitHub Actions workflow can automate builds for all platforms. See `.github/workflows/build.yml`.

## Code Signing

### Windows
Use SignTool from Windows SDK:
```cmd
signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com dist\DFN-Uploader.exe
```

### macOS
```bash
codesign --deep --force --verify --verbose --sign "Developer ID Application: Your Name" "dist/DFN Uploader.app"

# Notarize with Apple
xcrun notarytool submit "DFN-Uploader.dmg" --keychain-profile "notarytool-profile" --wait

# Staple notarization ticket
xcrun stapler staple "DFN-Uploader.dmg"
```

## Distribution

### GitHub Releases
1. Tag the release: `git tag -a v0.1.0 -m "Release version 0.1.0"`
2. Push the tag: `git push origin v0.1.0`
3. Create GitHub Release and upload platform-specific packages
4. Assets should be named:
   - `DFN-Uploader-v0.1.0-Windows.exe`
   - `DFN-Uploader-v0.1.0-macOS.dmg`
   - `DFN-Uploader-v0.1.0-Linux.AppImage`

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
