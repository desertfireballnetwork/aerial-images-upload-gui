"""Tests for API client functionality."""

import pytest
import aiohttp
from aioresponses import aioresponses
from pathlib import Path
from unittest.mock import patch
from src.api_client import APIClient


CHECK_URL = "https://find.gfo.rocks/survey/upload/check/"
UPLOAD_URL = "https://find.gfo.rocks/survey/upload/"


@pytest.mark.asyncio
async def test_check_image_uploaded_new():
    """Test checking if an image is uploaded (new image)."""
    with aioresponses() as m:
        m.post(CHECK_URL, status=200, body="0")
        async with APIClient() as client:
            result = await client.check_image_uploaded("test-key", "test.jpg")
            assert result is False


@pytest.mark.asyncio
async def test_check_image_uploaded_exists():
    """Test checking if an image is uploaded (already exists)."""
    with aioresponses() as m:
        m.post(CHECK_URL, status=200, body="1")
        async with APIClient() as client:
            result = await client.check_image_uploaded("test-key", "test.jpg")
            assert result is True


@pytest.mark.asyncio
async def test_check_image_uploaded_non_200_returns_false():
    """Non-200 check response is treated as 'not uploaded' (returns False)."""
    with aioresponses() as m:
        m.post(CHECK_URL, status=500, body="Server Error")
        async with APIClient() as client:
            result = await client.check_image_uploaded("test-key", "test.jpg")
            assert result is False


@pytest.mark.asyncio
async def test_check_image_uploaded_network_error_raises():
    """A network error during check propagates as ClientError."""
    with aioresponses() as m:
        m.post(CHECK_URL, exception=aiohttp.ClientConnectionError("connection refused"))
        async with APIClient() as client:
            with pytest.raises(aiohttp.ClientError):
                await client.check_image_uploaded("test-key", "test.jpg")


@pytest.mark.asyncio
async def test_check_outside_context_manager_raises():
    """Calling check_image_uploaded without entering the context manager raises."""
    client = APIClient()
    with pytest.raises(RuntimeError, match="context manager"):
        await client.check_image_uploaded("test-key", "test.jpg")


@pytest.mark.asyncio
async def test_upload_image_success(sample_image):
    """Test successful image upload."""
    with aioresponses() as m:
        m.post(UPLOAD_URL, status=200, body="SUCCESS")
        async with APIClient() as client:
            success, message = await client.upload_image("test-key", "survey", sample_image)
            assert success is True
            assert message == "SUCCESS"


@pytest.mark.asyncio
async def test_upload_image_already_uploaded(sample_image):
    """Test uploading an image that already exists."""
    with aioresponses() as m:
        m.post(UPLOAD_URL, status=200, body="ALREADY_UPLOADED")
        async with APIClient() as client:
            success, message = await client.upload_image("test-key", "survey", sample_image)
            assert success is True
            assert message == "ALREADY_UPLOADED"


@pytest.mark.asyncio
async def test_upload_image_error(sample_image):
    """Test upload with non-200 status."""
    with aioresponses() as m:
        m.post(UPLOAD_URL, status=400, body="ERROR: Invalid upload key")
        async with APIClient() as client:
            success, message = await client.upload_image("test-key", "survey", sample_image)
            assert success is False
            assert "400" in message


@pytest.mark.asyncio
async def test_upload_image_unexpected_body(sample_image):
    """200 response with unexpected body is treated as failure."""
    with aioresponses() as m:
        m.post(UPLOAD_URL, status=200, body="UNEXPECTED_RESPONSE")
        async with APIClient() as client:
            success, message = await client.upload_image("test-key", "survey", sample_image)
            assert success is False
            assert message == "UNEXPECTED_RESPONSE"


@pytest.mark.asyncio
async def test_upload_image_network_error(sample_image):
    """A network error during upload is caught and returns (False, error_str)."""
    with aioresponses() as m:
        m.post(UPLOAD_URL, exception=aiohttp.ClientConnectionError("dropped"))
        async with APIClient() as client:
            success, message = await client.upload_image("test-key", "survey", sample_image)
            assert success is False
            assert "dropped" in message


@pytest.mark.asyncio
async def test_upload_image_file_not_found(tmp_path):
    """OSError when opening the file is caught and returns (False, error_str)."""
    missing = tmp_path / "nonexistent.jpg"
    async with APIClient() as client:
        success, message = await client.upload_image("test-key", "survey", missing)
        assert success is False
        assert message  # some error string is returned


@pytest.mark.asyncio
async def test_upload_outside_context_manager_raises(sample_image):
    """Calling upload_image without entering the context manager raises."""
    client = APIClient()
    with pytest.raises(RuntimeError, match="context manager"):
        await client.upload_image("test-key", "survey", sample_image)


@pytest.mark.asyncio
async def test_custom_base_url():
    """Test using a custom base URL."""
    with aioresponses() as m:
        m.post("https://custom.example.com/survey/upload/check/", status=200, body="0")
        async with APIClient("https://custom.example.com") as client:
            result = await client.check_image_uploaded("test-key", "test.jpg")
            assert result is False


@pytest.mark.asyncio
async def test_upload_image_uses_correct_mime_type_for_png(tmp_path):
    """Upload of a .png file should use content_type='image/png', not 'image/jpeg'."""
    from PIL import Image as PILImage

    png_file = tmp_path / "test_image.png"
    PILImage.new("RGB", (100, 100), color="red").save(png_file, "PNG")

    captured_content_type = None
    original_add_field = aiohttp.FormData.add_field

    def patched_add_field(self, name, value, **kwargs):
        nonlocal captured_content_type
        if name == "image":
            captured_content_type = kwargs.get("content_type")
        return original_add_field(self, name, value, **kwargs)

    with aioresponses() as m:
        m.post(UPLOAD_URL, status=200, body="SUCCESS")
        with patch.object(aiohttp.FormData, "add_field", patched_add_field):
            async with APIClient() as client:
                success, message = await client.upload_image("test-key", "survey", png_file)
                assert success is True

    assert captured_content_type == "image/png"


@pytest.mark.asyncio
async def test_upload_image_uses_jpeg_mime_for_jpg(sample_image):
    """Upload of a .jpg file should use content_type='image/jpeg'."""
    captured_content_type = None
    original_add_field = aiohttp.FormData.add_field

    def patched_add_field(self, name, value, **kwargs):
        nonlocal captured_content_type
        if name == "image":
            captured_content_type = kwargs.get("content_type")
        return original_add_field(self, name, value, **kwargs)

    with aioresponses() as m:
        m.post(UPLOAD_URL, status=200, body="SUCCESS")
        with patch.object(aiohttp.FormData, "add_field", patched_add_field):
            async with APIClient() as client:
                success, message = await client.upload_image("test-key", "survey", sample_image)
                assert success is True

    assert captured_content_type == "image/jpeg"


@pytest.mark.asyncio
async def test_upload_image_unknown_extension_uses_octet_stream(tmp_path):
    """Upload of a file with unknown extension falls back to application/octet-stream."""
    unknown_file = tmp_path / "test_image.xyz123"
    unknown_file.write_bytes(b"some binary data")

    captured_content_type = None
    original_add_field = aiohttp.FormData.add_field

    def patched_add_field(self, name, value, **kwargs):
        nonlocal captured_content_type
        if name == "image":
            captured_content_type = kwargs.get("content_type")
        return original_add_field(self, name, value, **kwargs)

    with aioresponses() as m:
        m.post(UPLOAD_URL, status=200, body="SUCCESS")
        with patch.object(aiohttp.FormData, "add_field", patched_add_field):
            async with APIClient() as client:
                success, message = await client.upload_image("test-key", "survey", unknown_file)
                assert success is True

    assert captured_content_type == "application/octet-stream"
