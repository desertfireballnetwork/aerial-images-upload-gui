# Drone -> Cloud

Batch upload drone images to [find.gfo.rocks](find.gfo.rocks).

Cross-platform GUI application for staging drone survey images uploading them to the drone meteorite searching webapp with optimized parallel transfers.

## Features

- **SD Card Staging**: Automatically detect memory cards, copy images locally with progress tracking and retry on errors.
- **Parallel Uploads**: Auto-optimizing concurrent uploads (1-10 workers) to saturate Starlink bandwidth.
- **Smart Ordering**: Uploads images in chronological order based on EXIF timestamps.
- **Progress Tracking**: Real-time statistics including instantaneous rate, 1hr/12hr averages, and ETA.
- **Crash Recovery**: Persistent state allows resuming uploads after application restart.
- **Image Type Selection**: Configure whether images are survey, training_true, or training_false per batch
- **Disk Space Monitoring**: Warns when storage is low, prevents copying when critically low


## Installation

Download the appropriate package for your platform:
[https://github.com/desertfireballnetwork/aerial-images-upload-gui/releases]


## Features / Usage

1. **Configure**: Enter your upload key and select staging directory.
2. **SD Card**: Optional step to copy drone images directly from mounted external media to the staging directory.
3. **Stage**: Stage images to be uploaded, with confirmation of which image type and which survey.
4. **Upload**: Upload of staged images.
5. **Monitor Progress**: View real-time statistics and upload rates.
6. **Auto-Optimization**: System adjusts concurrent workers to maximize throughput.

## Configuration

Settings are persisted in `config.json`:
- `upload_key`: Survey-specific authentication key
- `staging_dir`: Local directory for staging images
- `concurrency_mode`: "auto" or "manual"
- `concurrency_value`: Number of parallel workers (1-10). Note: if for whatever reason you don't want to max out your upload bandwidth, set this to 1.
- `base_url`: Webapp server URL (defaults to `https://find.gfo.rocks`)




## Development

### Architecture

- **state_manager.py**: SQLite database for persistent state tracking
- **sd_monitor.py**: Cross-platform SD card detection using psutil
- **staging.py**: Multi-threaded image copying with retry logic
- **upload_manager.py**: Async upload queue with adaptive concurrency
- **api_client.py**: HTTP client for DFN webapp REST API
- **stats_tracker.py**: Upload statistics and rate calculations
- **uploader.py**: PySide6 main GUI application

### Requirements

- Python 3.10, 3.11, or 3.12 (3.13 is currently blocked by the PySide6 dependency)
- PySide6 for GUI
- Internet connection for uploads

### Install
```bash
poetry install
poetry run drone_to_cloud
```



### Testing

```bash
poetry run pytest
poetry run pytest --cov=src --cov-report=html
```

## Building

See [DEPLOYMENT.md](DEPLOYMENT.md) for instructions on building platform-specific packages.


## License

See [LICENSE](LICENSE) in the root of the repository.
