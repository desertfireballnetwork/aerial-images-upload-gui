"""
Tests for API client functionality.
"""
import pytest
from aioresponses import aioresponses
from pathlib import Path
from src.api_client import APIClient


@pytest.mark.asyncio
async def test_check_image_uploaded_new():
    """Test checking if an image is uploaded (new image)."""
    with aioresponses() as m:
        m.post(
            "https://find.gfo.rocks/dfnweb/check_image_uploaded/",
            status=200,
            body="0",
        )

        async with APIClient() as client:
            result = await client.check_image_uploaded("test-key", "test.jpg")
            assert result is False


@pytest.mark.asyncio
async def test_check_image_uploaded_exists():
    """Test checking if an image is uploaded (already exists)."""
    with aioresponses() as m:
        m.post(
            "https://find.gfo.rocks/dfnweb/check_image_uploaded/",
            status=200,
            body="1",
        )

        async with APIClient() as client:
            result = await client.check_image_uploaded("test-key", "test.jpg")
            assert result is True


@pytest.mark.asyncio
async def test_upload_image_success(sample_image):
    """Test successful image upload."""
    with aioresponses() as m:
        m.post(
            "https://find.gfo.rocks/dfnweb/upload_image/",
            status=200,
            body="SUCCESS",
        )

        async with APIClient() as client:
            success, message = await client.upload_image(
                "test-key", "survey", sample_image
            )
            assert success is True
            assert message == "SUCCESS"


@pytest.mark.asyncio
async def test_upload_image_already_uploaded(sample_image):
    """Test uploading an image that already exists."""
    with aioresponses() as m:
        m.post(
            "https://find.gfo.rocks/dfnweb/upload_image/",
            status=200,
            body="ALREADY_UPLOADED",
        )

        async with APIClient() as client:
            success, message = await client.upload_image(
                "test-key", "survey", sample_image
            )
            assert success is True
            assert message == "ALREADY_UPLOADED"


@pytest.mark.asyncio
async def test_upload_image_error(sample_image):
    """Test upload with error response."""
    with aioresponses() as m:
        m.post(
            "https://find.gfo.rocks/dfnweb/upload_image/",
            status=400,
            body="ERROR: Invalid upload key",
        )

        async with APIClient() as client:
            success, message = await client.upload_image(
                "test-key", "survey", sample_image
            )
            assert success is False
            assert "400" in message


@pytest.mark.asyncio
async def test_custom_base_url():
    """Test using a custom base URL."""
    with aioresponses() as m:
        m.post(
            "https://custom.example.com/dfnweb/check_image_uploaded/",
            status=200,
            body="0",
        )

        async with APIClient("https://custom.example.com") as client:
            result = await client.check_image_uploaded("test-key", "test.jpg")
            assert result is False
