"""Local GeoJSON resolution for saving a loaded layer to PostGIS."""

import gzip
import shutil
from pathlib import Path

import pytest

from api.postgis_layers import (
    _local_stream_filename,
    _read_uploaded_geojson,
    _sanitize_table_name,
)


def test_local_stream_filename_accepts_loopback_and_relative_urls():
    name = "abc_school.geojson"
    assert _local_stream_filename(f"http://localhost:8000/api/stream/{name}") == name
    assert _local_stream_filename(f"http://127.0.0.1:8000/api/stream/{name}") == name
    assert _local_stream_filename(f"/api/stream/{name}") == name


def test_sanitize_table_name_fits_spatial_index():
    table = _sanitize_table_name(
        "school-areas-near-data-openstreetmap-contributors-odbl-10-httposmorgcopyright-filtered"
    )
    index_name = f"idx_{table}_geometry"
    assert len(table.encode("utf-8")) <= 63
    assert len(index_name.encode("utf-8")) <= 63
    assert table.startswith("layer_school_areas")


def test_local_stream_filename_ignores_remote_hosts():
    assert (
        _local_stream_filename("https://example.com/api/stream/abc_school.geojson")
        is None
    )


def _workspace_upload(monkeypatch, name: str) -> Path:
    import core.config as config

    upload_dir = Path(__file__).resolve().parent / "_tmp_postgis_uploads" / name
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "LOCAL_UPLOAD_DIR", str(upload_dir))
    return upload_dir


def test_read_uploaded_geojson_reads_plain_and_gzip(monkeypatch):
    upload_dir = _workspace_upload(monkeypatch, "plain")
    try:
        plain = upload_dir / "plain_layer.geojson"
        plain.write_bytes(b'{"type":"FeatureCollection","features":[]}')
        assert _read_uploaded_geojson("plain_layer.geojson") == plain.read_bytes()

        payload = b'{"type":"FeatureCollection","features":[1]}'
        with gzip.open(upload_dir / "gzip_only.geojson.gz", "wb") as handle:
            handle.write(payload)
        assert _read_uploaded_geojson("gzip_only.geojson") == payload
    finally:
        shutil.rmtree(upload_dir.parent, ignore_errors=True)


def test_read_uploaded_geojson_missing_file(monkeypatch):
    from fastapi import HTTPException

    upload_dir = _workspace_upload(monkeypatch, "missing")
    try:
        with pytest.raises(HTTPException) as exc:
            _read_uploaded_geojson("missing.geojson")
        assert exc.value.status_code == 404
        assert not (upload_dir / "missing.geojson").exists()
    finally:
        shutil.rmtree(upload_dir.parent, ignore_errors=True)
