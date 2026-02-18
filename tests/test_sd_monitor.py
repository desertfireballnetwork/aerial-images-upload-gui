"""Unit tests for SDCardInfo properties and image-counting helpers."""

import pytest
from pathlib import Path
from src.sd_monitor import SDCardInfo


ONE_GB = 1024**3


def make_info(total_gb: float = 32.0, free_gb: float = 20.0, path: str = "/fake/sd") -> SDCardInfo:
    """Factory helper for SDCardInfo instances."""
    return SDCardInfo(
        path=path,
        device="/dev/sdb1",
        total_bytes=int(total_gb * ONE_GB),
        free_bytes=int(free_gb * ONE_GB),
    )


class TestSDCardInfoProperties:
    def test_used_bytes_computed_correctly(self):
        info = make_info(total_gb=32.0, free_gb=20.0)
        assert info.used_bytes == info.total_bytes - info.free_bytes

    def test_total_gb(self):
        info = make_info(total_gb=64.0, free_gb=0.0)
        assert info.total_gb == pytest.approx(64.0, rel=1e-3)

    def test_used_gb(self):
        info = make_info(total_gb=32.0, free_gb=20.0)
        assert info.used_gb == pytest.approx(12.0, rel=1e-3)

    def test_free_gb(self):
        info = make_info(total_gb=32.0, free_gb=20.0)
        assert info.free_gb == pytest.approx(20.0, rel=1e-3)

    def test_used_plus_free_equals_total(self):
        info = make_info(total_gb=16.0, free_gb=7.5)
        assert info.used_gb + info.free_gb == pytest.approx(info.total_gb, rel=1e-6)

    def test_repr_contains_path(self, tmp_path):
        info = SDCardInfo(str(tmp_path), "/dev/sdb1", ONE_GB * 8, ONE_GB * 4)
        r = repr(info)
        assert str(tmp_path) in r
        assert "8.0GB" in r


class TestSDCardInfoCountImages:
    def test_count_images_empty_dir(self, tmp_path):
        info = SDCardInfo(str(tmp_path), "/dev/sdb1", ONE_GB, ONE_GB // 2)
        assert info.count_images() == 0

    def test_count_images_with_jpegs(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"fake")
        (tmp_path / "b.JPG").write_bytes(b"fake")
        (tmp_path / "c.jpeg").write_bytes(b"fake")
        (tmp_path / "note.txt").write_bytes(b"text")
        info = SDCardInfo(str(tmp_path), "/dev/sdb1", ONE_GB, ONE_GB // 2)
        assert info.count_images() == 3

    def test_count_images_in_subdirectory(self, tmp_path):
        sub = tmp_path / "DCIM" / "100MEDIA"
        sub.mkdir(parents=True)
        (sub / "IMG_001.jpg").write_bytes(b"fake")
        (sub / "IMG_002.jpg").write_bytes(b"fake")
        info = SDCardInfo(str(tmp_path), "/dev/sdb1", ONE_GB, ONE_GB // 2)
        assert info.count_images() == 2

    def test_count_images_nonexistent_path(self, tmp_path):
        missing = tmp_path / "nonexistent"
        info = SDCardInfo(str(missing), "/dev/sdb1", ONE_GB, ONE_GB // 2)
        # Should return 0 and not raise
        assert info.count_images() == 0


class TestSDCardInfoGetImages:
    def test_get_images_empty_dir(self, tmp_path):
        info = SDCardInfo(str(tmp_path), "/dev/sdb1", ONE_GB, ONE_GB // 2)
        assert info.get_images() == []

    def test_get_images_returns_paths(self, tmp_path):
        f1 = tmp_path / "img1.jpg"
        f2 = tmp_path / "img2.JPEG"
        f1.write_bytes(b"fake")
        f2.write_bytes(b"fake")
        info = SDCardInfo(str(tmp_path), "/dev/sdb1", ONE_GB, ONE_GB // 2)
        result = info.get_images()
        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"img1.jpg", "img2.JPEG"}

    def test_get_images_non_jpeg_excluded(self, tmp_path):
        (tmp_path / "photo.png").write_bytes(b"fake")
        (tmp_path / "photo.tiff").write_bytes(b"fake")
        (tmp_path / "photo.jpg").write_bytes(b"fake")
        info = SDCardInfo(str(tmp_path), "/dev/sdb1", ONE_GB, ONE_GB // 2)
        result = info.get_images()
        assert len(result) == 1
        assert result[0].name == "photo.jpg"

    def test_get_images_count_matches_count_images(self, tmp_path):
        for i in range(5):
            (tmp_path / f"img{i}.jpg").write_bytes(b"fake")
        info = SDCardInfo(str(tmp_path), "/dev/sdb1", ONE_GB, ONE_GB // 2)
        assert len(info.get_images()) == info.count_images()
