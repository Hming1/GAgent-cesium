import io
import json
import logging
from fastapi import APIRouter, HTTPException
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

    if geodata_pool is None:
        try:
            geodata_pool = AsyncConnectionPool(
                conninfo=GEODATA_DATABASE_URL, min_size=1, max_size=5
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
