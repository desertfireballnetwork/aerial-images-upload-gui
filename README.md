# DFN Image Uploader

Cross-platform GUI application for staging drone survey images from SD cards and uploading them to the DFN webapp with optimized parallel transfers.

## Features

- **SD Card Staging**: Automatically detect SD cards, copy images with progress tracking and retry on errors
- **Parallel Uploads**: Auto-optimizing concurrent uploads (1-10 workers) to saturate Starlink bandwidth
- **Smart Ordering**: Uploads images in chronological order based on EXIF timestamps
- **Progress Tracking**: Real-time statistics including instantaneous rate, 1hr/12hr averages, and ETA
- **Crash Recovery**: Persistent state allows resuming uploads after application restart
- **Image Type Selection**: Configure whether images are survey, training_true, or training_false per batch
- **Disk Space Monitoring**: Warns when storage is low, prevents copying when critically low

## Requirements

- Python 3.10 or higher
- PySide6 for GUI
- Internet connection for uploads

## Installation

### Development

```bash
### Development

```bash
poetry install
poetry run dfn-uploader
```

### Production

Download the appropriate package for your platform:
- **Windows**: `dfn-uploader.exe`
- **macOS**: `dfn-uploader.app` or `dfn-uploader.dmg`
- **Linux**: `dfn-uploader.AppImage`

## Usage

1. **Configure**: Enter your upload key and select staging directory
2. **Insert SD Card**: Application will detect and show confirmation dialog
3. **Select Image Type**: Choose survey/training_true/training_false for the batch
4. **Copy Images**: Confirm to start copying from SD card to local staging
5. **Start Upload**: Once staged, start the upload process
6. **Monitor Progress**: View real-time statistics and upload rates
7. **Auto-Optimization**: System adjusts concurrent workers to maximize throughput

## Configuration

Settings are persisted in `config.json`:
- `upload_key`: Survey-specific authentication key
- `staging_dir`: Local directory for staging images
- `concurrency_mode`: "auto" or "manual"
- `concurrency_value`: Number of parallel workers (1-10)

## Architecture

- **state_manager.py**: SQLite database for persistent state tracking
- **sd_monitor.py**: Cross-platform SD card detection using psutil
- **staging.py**: Multi-threaded image copying with retry logic
- **upload_manager.py**: Async upload queue with adaptive concurrency
- **api_client.py**: HTTP client for DFN webapp REST API
- **stats_tracker.py**: Upload statistics and rate calculations
- **uploader.py**: PySide6 main GUI application

## Testing

```bash
poetry run pytest
poetry run pytest --cov=src --cov-report=html
```

## Building

See [DEPLOYMENT.md](DEPLOYMENT.md) for instructions on building platform-specific packages.

## License

See [LICENSE](LICENSE) in the root of the repository.
