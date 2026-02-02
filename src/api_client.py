"""
API client for communicating with DFN webapp upload endpoints.
"""
import aiohttp
from pathlib import Path
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class APIClient:
    """Client for DFN webapp upload API."""

    def __init__(self, base_url: str = "https://find.gfo.rocks"):
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Create session on context enter."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=300, connect=30)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close session on context exit."""
        if self.session:
            await self.session.close()

    async def check_image_uploaded(self, upload_key: str, filename: str) -> bool:
        """
        Check if an image has already been uploaded.

        Args:
            upload_key: Survey upload key (UUID)
            filename: Name of the file to check

        Returns:
            True if already uploaded, False if new
        """
        if not self.session:
            raise RuntimeError("APIClient must be used as context manager")

        url = f"{self.base_url}/dfnweb/check_image_uploaded/"
        data = {"upload_key": upload_key, "filename": filename}

        try:
            async with self.session.post(url, data=data) as response:
                if response.status == 200:
                    text = await response.text()
                    return text.strip() == "1"
                else:
                    logger.warning(
                        f"Check image uploaded returned status {response.status} for {filename}"
                    )
                    return False
        except aiohttp.ClientError as e:
            logger.error(f"Error checking if image uploaded: {e}")
            raise

    async def upload_image(
        self, upload_key: str, image_type: str, file_path: Path
    ) -> Tuple[bool, str]:
        """
        Upload an image to the DFN webapp.

        Args:
            upload_key: Survey upload key (UUID)
            image_type: One of 'survey', 'training_true', 'training_false'
            file_path: Path to the image file

        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self.session:
            raise RuntimeError("APIClient must be used as context manager")

        url = f"{self.base_url}/dfnweb/upload_image/"

        try:
            with open(file_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("upload_key", upload_key)
                data.add_field("image_type", image_type)
                data.add_field(
                    "image_file",
                    f,
                    filename=file_path.name,
                    content_type="image/jpeg",
                )

                async with self.session.post(url, data=data) as response:
                    text = await response.text()
                    text = text.strip()

                    if response.status == 200:
                        if text == "SUCCESS" or text == "ALREADY_UPLOADED":
                            return True, text
                        else:
                            logger.warning(
                                f"Upload returned unexpected response for {file_path.name}: {text}"
                            )
                            return False, text
                    else:
                        logger.error(
                            f"Upload failed with status {response.status} for {file_path.name}: {text}"
                        )
                        return False, f"HTTP {response.status}: {text}"

        except aiohttp.ClientError as e:
            logger.error(f"Network error uploading {file_path.name}: {e}")
            return False, str(e)
        except OSError as e:
            logger.error(f"File error uploading {file_path.name}: {e}")
            return False, str(e)
