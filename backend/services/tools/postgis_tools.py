"""PostGIS discovery and loading tools for the GeoAgent agent."""

import asyncio
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from typing_extensions import Annotated

from core.config import GEODATA_DATABASE_URL
from models.geodata import DataOrigin, DataType, GeoDataObject
from models.states import GeoDataAgentState
from services.storage.file_management import store_file_stream

logger = logging.getLogger(__name__)

MAX_POSTGIS_FEATURES = 10000

try:
    from psycopg_pool import AsyncConnectionPool

    PSYCOPG_POOL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in incomplete envs
    AsyncConnectionPool = None
    PSYCOPG_POOL_AVAILABLE = False


def _normalize_conninfo(conninfo: str) -> str:
    """Normalize SQLAlchemy-style URLs for psycopg_pool."""
    return (
        conninfo.replace("postgresql+psycopg://", "postgresql://")
        .replace("postgis://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
    )


def _validate_identifier(value: str, label: str) -> str:
    """Allow only simple PostgreSQL identifiers used by our generated SQL."""
    if not value or not value.replace("_", "").isalnum():
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _cap_row_limit(row_limit: int) -> int:
    try:
        limit = int(row_limit)
    except (TypeError, ValueError):
        limit = MAX_POSTGIS_FEATURES
    return max(1, min(limit, MAX_POSTGIS_FEATURES))


@asynccontextmanager
async def _get_connection():
    """Open and close the pool on the same loop as this database operation.

    Sync LangChain tools use a fresh asyncio.run() loop for each invocation.
    A process-global async pool retains dead worker tasks after that loop exits.
    """
    if not PSYCOPG_POOL_AVAILABLE:
        raise RuntimeError("psycopg_pool is not available")
    if not GEODATA_DATABASE_URL:
        raise RuntimeError("GEODATA_DATABASE_URL is not configured")

    async with AsyncConnectionPool(
        conninfo=_normalize_conninfo(GEODATA_DATABASE_URL),
        min_size=0,
        max_size=1,
        open=False,
    ) as pool:
        async with pool.connection() as conn:
            yield conn


async def _list_spatial_tables(query: Optional[str] = None) -> List[Dict[str, Any]]:
    async with _get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT f_table_schema, f_table_name, f_geometry_column, type, srid
                FROM geometry_columns
                WHERE f_table_schema NOT IN ('topology', 'tiger')
                ORDER BY f_table_schema, f_table_name, f_geometry_column
                """
            )
            rows = await cur.fetchall()

    tables = [
        {
            "schema": row[0],
            "table": row[1],
            "geometry_column": row[2],
            "type": row[3],
            "srid": row[4],
            "qualified_name": f"{row[0]}.{row[1]}",
        }
        for row in rows
    ]

    if query and query.strip():
        terms = query.lower().split()
        tables = [
            table
            for table in tables
            if all(
                term
                in " ".join(
                    [
                        table["schema"],
                        table["table"],
                        table["geometry_column"],
                        table["type"] or "",
                    ]
                ).lower()
                for term in terms
            )
        ]

    return tables


async def _find_geometry_metadata(
    schema_name: str, table_name: str, geom_column: str
) -> Dict[str, Any]:
    async with _get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT type, srid
                FROM geometry_columns
                WHERE f_table_schema = %s
                  AND f_table_name = %s
                  AND f_geometry_column = %s
                LIMIT 1
                """,
                (schema_name, table_name, geom_column),
            )
            row = await cur.fetchone()

    if not row:
        raise ValueError(f"Spatial table not found: {schema_name}.{table_name} ({geom_column})")

    return {"type": row[0], "srid": row[1]}


async def _load_spatial_table_as_geojson(
    schema_name: str,
    table_name: str,
    geom_column: str,
    row_limit: int,
) -> Dict[str, Any]:
    schema_name = _validate_identifier(schema_name, "schema name")
    table_name = _validate_identifier(table_name, "table name")
    geom_column = _validate_identifier(geom_column, "geometry column")
    row_limit = _cap_row_limit(row_limit)

    metadata = await _find_geometry_metadata(schema_name, table_name, geom_column)
    srid = metadata.get("srid")
    schema_sql = _quote_ident(schema_name)
    table_sql = _quote_ident(table_name)
    geom_sql = _quote_ident(geom_column)

    geom_expr = f"t.{geom_sql}"
    if srid and int(srid) not in (0, 4326):
        geom_expr = f"ST_Transform(t.{geom_sql}, 4326)"

    query = f"""
        WITH limited AS (
            SELECT *
            FROM {schema_sql}.{table_sql}
            WHERE {geom_sql} IS NOT NULL
            LIMIT %s
        ), features AS (
            SELECT jsonb_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON({geom_expr})::jsonb,
                'properties', to_jsonb(t.*) - %s
            ) AS feature
            FROM limited t
        )
        SELECT jsonb_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
        ),
        (SELECT COUNT(*) FROM limited),
        (SELECT ST_AsText(ST_Envelope(ST_Extent({geom_expr}))) FROM limited t)
        FROM features;
    """

    async with _get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, (row_limit, geom_column))
            row = await cur.fetchone()

    geojson_data = row[0] if row and row[0] else {"type": "FeatureCollection", "features": []}
    feature_count = int(row[1] or 0) if row else 0
    bounding_box = row[2] if row and row[2] else None

    return {
        "geojson": geojson_data,
        "feature_count": feature_count,
        "bounding_box": bounding_box,
        "geometry_type": metadata.get("type"),
        "srid": srid,
        "row_limit": row_limit,
    }


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # asyncio cannot run a second loop in the same thread. The worker owns
    # this coroutine and closes its database resources before its loop exits.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


def _build_postgis_layer(
    schema_name: str,
    table_name: str,
    geom_column: str,
    loaded: Dict[str, Any],
) -> GeoDataObject:
    geojson_str = json.dumps(loaded["geojson"])
    stream = io.BytesIO(geojson_str.encode("utf-8"))
    filename = f"{schema_name}_{table_name}.geojson"
    url, unique_id = store_file_stream(filename, stream)
    qualified_name = f"{schema_name}.{table_name}"

    return GeoDataObject(
        id=unique_id,
        data_source_id="postgis",
        data_type=DataType.POSTGIS,
        data_origin=DataOrigin.TOOL.value,
        data_source="PostGIS",
        data_link=url,
        name=qualified_name,
        title=qualified_name,
        description=(
            f"Loaded from PostGIS table {qualified_name}. "
            f"Feature count loaded: {loaded['feature_count']}"
        ),
        llm_description=(
            f"PostGIS spatial table {qualified_name} with geometry column "
            f"{geom_column}, geometry type {loaded.get('geometry_type')}, "
            f"SRID {loaded.get('srid')}."
        ),
        bounding_box=loaded.get("bounding_box"),
        layer_type="VECTOR",
        properties={
            "schema": schema_name,
            "table": table_name,
            "geometry_column": geom_column,
            "geometry_type": loaded.get("geometry_type"),
            "srid": loaded.get("srid"),
            "feature_count": loaded.get("feature_count"),
            "row_limit": loaded.get("row_limit"),
        },
    )


@tool
def list_postgis_layers(
    state: Annotated[GeoDataAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    query: Optional[str] = None,
    max_results: int = 50,
) -> Union[Dict[str, Any], Command]:
    """
    List available spatial tables in the configured PostGIS database.

    Use this when the user asks what data exists in PostGIS, the database,
    internal spatial tables, or asks to find a layer before loading it.
    Optionally pass a short query to filter table names, schemas, geometry
    columns, or geometry types. This tool only reads metadata and does not
    load features into the map.
    """
    try:
        tables = _run_async(_list_spatial_tables(query=query))
        limit = max(1, min(int(max_results or 50), 100))
        limited = tables[:limit]
        payload = {
            "operation": "list_postgis_layers",
            "query": query,
            "total_matches": len(tables),
            "returned": len(limited),
            "tables": limited,
        }
        content = json.dumps(payload, ensure_ascii=False)
        message = ToolMessage(
            name="list_postgis_layers",
            content=content,
            tool_call_id=tool_call_id,
        )
    except Exception as e:
        logger.exception("Failed to list PostGIS layers")
        message = ToolMessage(
            name="list_postgis_layers",
            content=f"Error listing PostGIS layers: {e}",
            tool_call_id=tool_call_id,
            status="error",
        )

    return Command(update={"messages": [message]})


@tool
def load_postgis_layer(
    state: Annotated[GeoDataAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    schema_name: str,
    table_name: str,
    geom_column: str = "geom",
    row_limit: int = MAX_POSTGIS_FEATURES,
    add_to_map: bool = True,
) -> Union[Dict[str, Any], Command]:
    """
    Load a PostGIS spatial table as a GeoDataObject for map display and analysis.

    Use this after list_postgis_layers identifies a relevant table, or when the
    user explicitly names a PostGIS table. The tool exports up to row_limit
    features as a GeoJSON stream, stores it through GeoAgent file storage, and
    returns a layer that other tools can analyze.

    Args:
        schema_name: PostgreSQL schema name, for example "public".
        table_name: Spatial table name.
        geom_column: Geometry column from geometry_columns, default "geom".
        row_limit: Maximum features to export, capped at 10000.
        add_to_map: If true, add the layer to geodata_layers; otherwise only add
            it to geodata_results for user review.
    """
    try:
        loaded = _run_async(
            _load_spatial_table_as_geojson(
                schema_name=schema_name,
                table_name=table_name,
                geom_column=geom_column,
                row_limit=row_limit,
            )
        )
        layer = _build_postgis_layer(schema_name, table_name, geom_column, loaded)
        new_results = (state.get("geodata_results") or []) + [layer]
        layer_location = "added to the map" if add_to_map else "available in results"
        update: Dict[str, Any] = {
            "messages": [
                ToolMessage(
                    name="load_postgis_layer",
                    content=(
                        f"Loaded PostGIS layer {layer.name} with "
                        f"{loaded['feature_count']} feature(s). "
                        f"Layer id: {layer.id}. Data link: {layer.data_link}. "
                        f"The layer is {layer_location} "
                        "and can be used by attribute and geoprocessing tools."
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
            "geodata_results": new_results,
            "results_title": "PostGIS 数据加载结果",
        }
        if add_to_map:
            update["geodata_layers"] = (state.get("geodata_layers") or []) + [layer]
        return Command(update=update)
    except Exception as e:
        logger.exception("Failed to load PostGIS layer")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        name="load_postgis_layer",
                        content=f"Error loading PostGIS layer {schema_name}.{table_name}: {e}",
                        tool_call_id=tool_call_id,
                        status="error",
                    )
                ]
            }
        )
