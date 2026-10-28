import io
import json
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import GEODATA_DATABASE_URL
from services.storage.file_management import store_file_stream

router = APIRouter(prefix="/postgis", tags=["postgis"])
logger = logging.getLogger(__name__)

# Try to import psycopg_pool, handle missing gracefully
try:
    from psycopg_pool import AsyncConnectionPool

    PSYCOPG_AVAILABLE = True
except ImportError:
    AsyncConnectionPool = None
    PSYCOPG_AVAILABLE = False

geodata_pool = None


async def get_geodata_pool():
    global geodata_pool
    if not PSYCOPG_AVAILABLE:
        raise HTTPException(status_code=500, detail="psycopg_pool not available")

    if not GEODATA_DATABASE_URL:
        raise HTTPException(
            status_code=500,
            detail="GEODATA_DATABASE_URL is not configured",
        )

    if geodata_pool is None:
        try:
            # Normalize URL: psycopg_pool expects plain libpq conninfo,
            # not SQLAlchemy dialect strings like "postgresql+psycopg://".
            conninfo = GEODATA_DATABASE_URL
            conninfo = conninfo.replace("postgresql+psycopg://", "postgresql://")
            conninfo = conninfo.replace("postgis://", "postgresql://")

            geodata_pool = AsyncConnectionPool(
                conninfo=conninfo, min_size=1, max_size=5
            )
            await geodata_pool.open()
        except Exception as e:
            logger.error(f"Failed to initialize geodata database connection pool: {e}")
            raise HTTPException(status_code=500, detail="Database connection failed")
    return geodata_pool


@router.get("/tables")
async def list_spatial_tables():
    """List all spatial tables in the geodata database."""
    pool = await get_geodata_pool()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Ensure PostGIS extension is installed
                await cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
                await conn.commit()
                # Query geometry_columns to find spatial tables
                await cur.execute(
                    """
                    SELECT f_table_schema, f_table_name, f_geometry_column, type
                    FROM geometry_columns
                    WHERE f_table_schema NOT IN ('topology', 'tiger')
                """
                )
                rows = await cur.fetchall()
                results = []
                for row in rows:
                    results.append(
                        {
                            "schema": row[0],
                            "table": row[1],
                            "geometry_column": row[2],
                            "type": row[3],
                        }
                    )
                return {"tables": results}
    except Exception as e:
        logger.error(f"Error fetching spatial tables: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/layer/{schema_name}/{table_name}")
async def get_postgis_layer(schema_name: str, table_name: str, geom_column: str = "geom"):
    """Fetch a table, convert to GeoJSON and store it with a limit of 10000 rows."""
    # Ensure safe identifiers (to prevent SQL injection)
    if (
        not schema_name.replace("_", "").isalnum()
        or not table_name.replace("_", "").isalnum()
        or not geom_column.replace("_", "").isalnum()
    ):
        raise HTTPException(status_code=400, detail="Invalid table, schema or geom column name")

    pool = await get_geodata_pool()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Limit to 10000 rows to prevent overloading the client and server memory
                query = f"""
                    SELECT jsonb_build_object(
                        'type',     'FeatureCollection',
                        'features', coalesce(jsonb_agg(features.feature), '[]'::jsonb)
                    )
                    FROM (
                      SELECT jsonb_build_object(
                        'type',       'Feature',
                        'geometry',   ST_AsGeoJSON(t."{geom_column}")::jsonb,
                        'properties', to_jsonb(t.*) - '{geom_column}'
                      ) AS feature
                      FROM (SELECT * FROM "{schema_name}"."{table_name}" LIMIT 10000) t
                    ) features;
                """
                await cur.execute(query)
                row = await cur.fetchone()

                if row and row[0]:
                    geojson_data = row[0]
                else:
                    # Empty collection fallback
                    geojson_data = {"type": "FeatureCollection", "features": []}

                geojson_str = json.dumps(geojson_data)

                # Convert to stream and store using common file_management pipeline
                stream = io.BytesIO(geojson_str.encode("utf-8"))
                filename = f"{schema_name}_{table_name}.geojson"
                url, unique_id = store_file_stream(filename, stream)

                return {"url": url, "id": unique_id}

    except Exception as e:
        logger.error(f"Error generating GeoJSON for {schema_name}.{table_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Save a layer (GeoJSON) to PostGIS
# ---------------------------------------------------------------------------


class SaveToPostGISRequest(BaseModel):
    """Request body for saving a layer to PostGIS."""
    data_link: str  # URL of the GeoJSON (local or remote)
    name: str  # Layer name used to derive the table name
    table_name: Optional[str] = None  # Optional explicit table name


def _local_stream_filename(data_link: str) -> Optional[str]:
    """Return the upload filename when data_link points at this API's stream route."""
    raw = (data_link or "").strip()
    if not raw:
        return None

    if raw.startswith("/"):
        path = raw
        host = ""
    else:
        parsed = urlparse(raw)
        if parsed.scheme not in ("", "http", "https"):
            return None
        path = parsed.path or ""
        host = (parsed.hostname or "").lower()

    marker = "/api/stream/"
    index = path.find(marker)
    if index < 0:
        return None

    if host:
        base_host = (
            urlparse(os.getenv("BASE_URL", "http://localhost:8000")).hostname or ""
        ).lower()
        local_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
        if base_host:
            local_hosts.add(base_host)
        if host not in local_hosts:
            return None

    filename = unquote(path[index + len(marker) :]).strip().lstrip("/")
    if not filename or ".." in Path(filename).parts:
        return None
    return filename


def _read_uploaded_geojson(filename: str) -> bytes:
    """Read a generated layer from local storage, including a gzip-only copy."""
    import gzip

    from core.config import LOCAL_UPLOAD_DIR
    from services.compression.gzip_utils import get_compressed_path
    from utility.string_methods import sanitize_filename

    safe_filename = sanitize_filename(filename)
    if not safe_filename:
        raise HTTPException(status_code=400, detail="无效的图层文件名")

    upload_dir = Path(LOCAL_UPLOAD_DIR).resolve()
    original = (upload_dir / safe_filename).resolve()
    try:
        original.relative_to(upload_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的图层路径")

    if original.is_file():
        return original.read_bytes()

    compressed = get_compressed_path(original)
    if compressed.is_file():
        with gzip.open(compressed, "rb") as handle:
            return handle.read()

    raise HTTPException(status_code=404, detail=f"图层文件不存在: {safe_filename}")


# PostgreSQL identifiers are limited to 63 bytes. GeoAlchemy creates
# idx_{table}_{geometry_column}, so the table name must leave room for that.
_MAX_PG_IDENT_BYTES = 63


def _truncate_pg_identifier(name: str, max_bytes: int) -> str:
    encoded = name.encode("utf-8")
    if len(encoded) <= max_bytes:
        return name
    trimmed = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip("_")
    return trimmed or "layer"


def _limit_spatial_table_name(table_name: str, geom_column: str = "geometry") -> str:
    overhead = len(f"idx_{geom_column}".encode("utf-8")) + 1
    return _truncate_pg_identifier(table_name, _MAX_PG_IDENT_BYTES - overhead)


def _sanitize_table_name(name: str) -> str:
    """Convert a layer name into a safe PostgreSQL table name."""
    import re

    # Remove path separators and extension
    clean = name.rsplit(".", 1)[0].split("/")[-1].split("\\")[-1]
    # Replace non-alphanumeric (keeping CJK) with underscores
    clean = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]", "_", clean)
    # Collapse multiple underscores
    clean = re.sub(r"_+", "_", clean).strip("_").lower()
    return _limit_spatial_table_name(f"layer_{clean}" if clean else "layer")


@router.post("/save")
async def save_layer_to_postgis(body: SaveToPostGISRequest):
    """Fetch a GeoJSON layer by its data_link and persist it into PostGIS.

    The endpoint:
    1. Downloads the GeoJSON from data_link (supports local /api/stream/ and http URLs).
    2. Converts it to a GeoDataFrame via geopandas.
    3. Writes the GeoDataFrame into a PostGIS table.

    Returns the created table name and row count.
    """
    import httpx

    # --- 1. Load GeoJSON ---
    # Local /api/stream files are served as chunked responses. Fetching them
    # over HTTP from this same process never completes, so read the file directly.
    local_filename = _local_stream_filename(body.data_link)
    if local_filename:
        geojson_bytes = _read_uploaded_geojson(local_filename)
    else:
        data_link = body.data_link
        base_url = os.getenv("BASE_URL", "http://localhost:8000")
        if data_link.startswith("/"):
            data_link = f"{base_url}{data_link}"
        try:
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                resp = await client.get(data_link)
                resp.raise_for_status()
                geojson_bytes = resp.content
        except Exception as e:
            logger.error(
                "Failed to download GeoJSON from %s: %s", data_link, repr(e)
            )
            raise HTTPException(
                status_code=400,
                detail=f"无法下载图层数据: {e!r}",
            )

    # --- 3. Convert to GeoDataFrame ---
    try:
        import geopandas as gpd
        import pandas as pd

        geojson_text = geojson_bytes.decode("utf-8")
        gdf = gpd.read_file(io.StringIO(geojson_text))

        if gdf.empty:
            raise HTTPException(status_code=400, detail="图层数据为空，无法保存")

        # Ensure CRS is EPSG:4326
        if getattr(gdf, "crs", None) is None:
            gdf.set_crs(epsg=4326, inplace=True)
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        # Convert datetime columns to strings for PostgreSQL compatibility
        for col in gdf.columns:
            if col == "geometry":
                continue
            if hasattr(gdf[col], "dt") or pd.api.types.is_datetime64_any_dtype(
                gdf[col]
            ):
                gdf[col] = gdf[col].astype(str)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to parse GeoJSON: {e}")
        raise HTTPException(status_code=400, detail=f"GeoJSON 解析失败: {e}")

    # --- 4. Write to PostGIS ---
    table_name = _limit_spatial_table_name(body.table_name or _sanitize_table_name(body.name))

    try:
        from sqlalchemy import create_engine, text

        db_url = GEODATA_DATABASE_URL
        if not db_url:
            raise HTTPException(
                status_code=500,
                detail="GEODATA_DATABASE_URL 未配置",
            )

        # Normalize for SQLAlchemy (strip async driver suffix)
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

        row_count = len(gdf)
        logger.info(
            f"Saved layer '{body.name}' to PostGIS: public.{table_name} ({row_count} rows)"
        )
        engine.dispose()

        return {
            "success": True,
            "table_name": table_name,
            "schema": "public",
            "row_count": row_count,
            "message": f"已保存 {row_count} 条记录到 public.{table_name}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to write to PostGIS: {e}")
        raise HTTPException(status_code=500, detail=f"写入 PostGIS 失败: {e}")
