import hashlib
import os
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

import core.config as core_config
from core.config import MAX_FILE_SIZE
from services.storage.file_management import store_file_stream


# Helper function for formatting file size
def format_file_size(bytes_size):
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024 or unit == "GB":
            return f"{bytes_size:.2f} {unit}" if unit != "B" else f"{bytes_size} {unit}"
        bytes_size /= 1024.0


class StyleUpdateRequest(BaseModel):
    layer_id: str
    style: Dict[str, Any]


router = APIRouter()


SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _resolve_upload_path(file_id: str) -> str:
    """Safely resolve upload file path within uploads directory.

    Returns the validated absolute path as a string to satisfy CodeQL analysis.
    """
    if not file_id or not file_id.strip():
        raise HTTPException(status_code=400, detail="Invalid file identifier")

    # Normalize and validate segments before joining
    normalized = os.path.normpath(file_id)

    # Reject absolute paths and parent directory traversal
    if os.path.isabs(normalized) or normalized.startswith(".."):
        raise HTTPException(status_code=400, detail="Invalid file identifier")

    # Additional segment validation
    segments = normalized.split(os.sep)
    for part in segments:
        if part in {"..", ""} or part.startswith(".") or not SAFE_SEGMENT.match(part):
            raise HTTPException(status_code=400, detail="Invalid file identifier")

    # Build full path and normalize
    uploads_root = os.path.abspath(core_config.LOCAL_UPLOAD_DIR)
    fullpath = os.path.normpath(os.path.join(uploads_root, normalized))

    # Verify the normalized path is within uploads_root (CodeQL-approved pattern)
    if not fullpath.startswith(uploads_root + os.sep):
        raise HTTPException(status_code=400, detail="Invalid file identifier")

    # Check file exists and is a file
    if not os.path.exists(fullpath) or not os.path.isfile(fullpath):
        raise HTTPException(status_code=404, detail="File not found")

    return fullpath


# Layer styling endpoint
@router.put("/layers/{layer_id}/style")
async def update_layer_style_endpoint(layer_id: str, style_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Update the styling of a specific layer.
    """
    # In a real implementation, you would update the layer style in your database
    # For now, we'll just return a success message
    return {
        "message": f"Layer {layer_id} style updated successfully",
        "layer_id": layer_id,
    }


# Upload endpoint
import tempfile
import io
import logging

logger = logging.getLogger(__name__)


def _sanitize_table_name(filename: str) -> str:
    """Convert a filename into a safe PostgreSQL table name."""
    # Remove extension and path
    name = filename.rsplit(".", 1)[0].split("/")[-1].split("\\")[-1]
    # Replace non-alphanumeric chars with underscores
    name = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]", "_", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name).strip("_").lower()
    # Add prefix and limit length
    table_name = f"upload_{name}"[:63]  # PostgreSQL 63-char limit
    return table_name


def _write_gdf_to_postgis(gdf, table_name: str) -> bool:
    """Write a GeoDataFrame to PostGIS. Returns True on success, False on failure."""
    try:
        from sqlalchemy import create_engine, text

        db_url = core_config.GEODATA_DATABASE_URL
        if not db_url:
            logger.warning("No GEODATA_DATABASE_URL configured, skipping PostGIS write")
            return False

        # Convert psycopg3 dialect to psycopg2 for GeoPandas compatibility
        db_url = db_url.replace("postgresql+psycopg://", "postgresql://")
        engine = create_engine(db_url)

        # Ensure PostGIS extension exists
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.commit()

        # Write GeoDataFrame to PostGIS
        gdf.to_postgis(
            name=table_name,
            con=engine,
            schema="public",
            if_exists="replace",
            index=False,
        )
        logger.info(f"Successfully wrote {len(gdf)} rows to PostGIS table: public.{table_name}")
        engine.dispose()
        return True

    except Exception as e:
        logger.warning(f"Failed to write to PostGIS (non-blocking): {e}")
        return False


def _process_upload_to_geojson_stream(
    filename: str, file_obj
) -> tuple[str, io.BytesIO, Optional[str]]:
    """
    If filename corresponds to a GIS format (KML, Shapefile in zip, or CSV),
    parse it and convert it to a GeoJSON stream and write to PostGIS.
    Returns (new_filename, stream, postgis_table_name).
    postgis_table_name is None if PostGIS write was skipped or failed.
    """
    ext = filename.lower().split(".")[-1]
    if ext not in ["zip", "kml", "csv"]:
        return filename, file_obj, None

    try:
        import geopandas as gpd
        import pandas as pd

        # Write to temporary file for geopandas
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(file_obj.read())
            tmp_path = tmp.name

        try:
            if ext == "kml":
                import fiona

                fiona.drvsupport.supported_drivers["KML"] = "rw"
                gdf = gpd.read_file(tmp_path, driver="KML")
            elif ext == "zip":
                # geopandas can read zipped shapefiles using the zip scheme
                gdf = gpd.read_file(f"zip://{tmp_path}")
            elif ext == "csv":
                df = pd.read_csv(tmp_path)
                lat_col, lon_col = None, None
                for col in df.columns:
                    col_lower = str(col).lower()
                    if col_lower in ["y", "lat", "latitude", "point_y"]:
                        lat_col = col
                    elif col_lower in ["x", "lon", "longitude", "lng", "point_x"]:
                        lon_col = col
                if lat_col and lon_col:
                    gdf = gpd.GeoDataFrame(
                        df, geometry=gpd.points_from_xy(df[lon_col], df[lat_col])
                    )
                    gdf.set_crs(epsg=4326, inplace=True, allow_override=True)
                else:
                    raise ValueError("Could not find latitude and longitude columns in CSV.")

            # Reproject to EPSG:4326 standard
            if getattr(gdf, "crs", None) is not None and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            elif getattr(gdf, "crs", None) is None:
                gdf.set_crs(epsg=4326, inplace=True)

            # Convert datetime/Timestamp columns to strings for JSON compatibility
            for col in gdf.columns:
                if col == "geometry":
                    continue
                if hasattr(gdf[col], "dt") or pd.api.types.is_datetime64_any_dtype(gdf[col]):
                    gdf[col] = gdf[col].astype(str)

            # Convert GeoDataFrame to GeoJSON
            geojson_str = gdf.to_json()
            new_stream = io.BytesIO(geojson_str.encode("utf-8"))
            new_filename = filename.rsplit(".", 1)[0] + ".geojson"

            # Write to PostGIS (non-blocking)
            postgis_table = _sanitize_table_name(filename)
            if not gdf.empty:
                _write_gdf_to_postgis(gdf, postgis_table)
            else:
                logger.warning(f"Skipping PostGIS write for {filename}: GeoDataFrame is empty")
                postgis_table = None

            return new_filename, new_stream, postgis_table
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        logger.warning(f"Failed to convert {filename} to GeoJSON: {e}")
        file_obj.seek(0)
        return filename, file_obj, None


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)) -> Dict[str, str]:
    """Uploads a file to Azure Blob Storage or local disk, streaming the payload.

    Returns its public URL and unique ID. File size is limited to 100MB.
    Automatically converts .zip (shapefile), .kml, and .csv to GeoJSON.
    """
    try:
        # Prefer server-provided size (if multipart header contains it) for a fast pre-check
        content_length = getattr(file, "size", None)
        if content_length is not None and content_length > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File size ({format_file_size(content_length)}) exceeds the limit of 100MB."
                ),
            )

        safe_name = file.filename or "upload.bin"

        # Intercept and convert vector formats to GeoJSON
        final_name, final_stream, postgis_table = _process_upload_to_geojson_stream(
            safe_name, file.file
        )

        url, unique_name = store_file_stream(final_name, final_stream)
        result = {"url": url, "id": unique_name}
        if postgis_table:
            result["postgis_table"] = postgis_table
        return result
    finally:
        await file.close()


# Debug/ops: fetch file metadata (size, sha256) to verify integrity end-to-end
@router.get("/uploads/meta/{file_id:path}")
async def get_upload_meta(file_id: str) -> Dict[str, str]:
    """Return file size and SHA256 for a stored upload by its ID (filename).

    Supports both local storage and Azure Blob Storage backends.
    """
    # Check if we're using Azure Blob Storage
    if core_config.USE_AZURE and core_config.AZ_CONN:
        try:
            from azure.storage.blob import BlobServiceClient

            # Sanitize filename to prevent path traversal
            safe_file_id = file_id.split("/")[-1]  # Get just the filename

            blob_svc = BlobServiceClient.from_connection_string(core_config.AZ_CONN)
            container_client = blob_svc.get_container_client(core_config.AZ_CONTAINER)
            blob_client = container_client.get_blob_client(safe_file_id)

            # Download blob and compute hash
            sha256 = hashlib.sha256()
            size = 0

            stream = blob_client.download_blob()
            for chunk in stream.chunks():
                size += len(chunk)
                sha256.update(chunk)

            return {
                "id": file_id,
                "size": str(size),
                "sha256": sha256.hexdigest(),
                "storage": "azure",
            }
        except Exception as e:
            raise HTTPException(
                status_code=404, detail=f"File not found in Azure Blob Storage: {str(e)}"
            )
    else:
        # Local storage fallback
        fullpath = _resolve_upload_path(file_id)

        sha256 = hashlib.sha256()
        size = 0
        with open(fullpath, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                size += len(chunk)
                sha256.update(chunk)

        return {
            "id": file_id,
            "size": str(size),
            "sha256": sha256.hexdigest(),
            "storage": "local",
        }
