"""Regression coverage for local artifact storage used by uploads and GIS tools."""

import io
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.storage import file_management as storage


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    destination = tmp_path / "new" / "uploads"
    monkeypatch.setattr(storage, "LOCAL_UPLOAD_DIR", str(destination))
    monkeypatch.setattr(storage, "BASE_URL", "http://localhost:8000")
    return destination


def test_generated_artifacts_create_directory_and_keep_unique_ids(upload_dir):
    content = b'{"type":"FeatureCollection","features":[]}'
    first_url, first_id = storage.store_file("../My Layer.GeoJSON", content)
    second_url, second_id = storage.store_file("../My Layer.GeoJSON", content)

    assert first_id != second_id
    for url, file_id in [(first_url, first_id), (second_url, second_id)]:
        assert Path(file_id).name == file_id
        assert file_id.endswith(".geojson")
        assert (upload_dir / file_id).read_bytes() == content
        assert url == f"http://localhost:8000/api/stream/{file_id}"


def test_streamed_upload_accepts_exact_size_limit(upload_dir, monkeypatch):
    monkeypatch.setattr("core.config.MAX_FILE_SIZE", 5)

    url, file_id = storage.store_file_stream("data.bin", io.BytesIO(b"12345"))

    assert (upload_dir / file_id).read_bytes() == b"12345"
    assert url.endswith(f"/api/stream/{file_id}")


def test_streamed_upload_removes_partial_file_on_size_limit(upload_dir, monkeypatch):
    monkeypatch.setattr("core.config.MAX_FILE_SIZE", 5)

    with pytest.raises(HTTPException) as error:
        storage.store_file_stream("data.bin", io.BytesIO(b"123456"))

    assert error.value.status_code == 413
    assert list(upload_dir.iterdir()) == []


def test_streamed_upload_removes_partial_file_on_read_error(upload_dir):
    class FailingStream:
        reads = 0

        def read(self, size):
            self.reads += 1
            if self.reads == 1:
                return b"partial content"
            raise OSError("source unavailable")

    with pytest.raises(OSError, match="source unavailable"):
        storage.store_file_stream("data.bin", FailingStream())

    assert list(upload_dir.iterdir()) == []
