import json

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from models.geodata import DataType
from services.tools import postgis_tools
from services.tools.postgis_tools import list_postgis_layers, load_postgis_layer


def base_state():
    return {
        "messages": [HumanMessage(content="查看数据库里有什么图层")],
        "geodata_layers": [],
        "geodata_results": [],
        "geodata_last_results": [],
        "results_title": "",
        "options": {},
        "execution_plan": None,
        "remaining_steps": 10,
    }


def test_list_postgis_layers_returns_metadata(monkeypatch):
    async def fake_list_spatial_tables(query=None):
        assert query == "park"
        return [
            {
                "schema": "public",
                "table": "city_parks",
                "geometry_column": "geom",
                "type": "MULTIPOLYGON",
                "srid": 4326,
                "qualified_name": "public.city_parks",
            }
        ]

    monkeypatch.setattr(postgis_tools, "_list_spatial_tables", fake_list_spatial_tables)

    result = list_postgis_layers.func(
        state=base_state(),
        tool_call_id="list-postgis",
        query="park",
        max_results=5,
    )

    assert isinstance(result, Command)
    message = result.update["messages"][0]
    assert message.name == "list_postgis_layers"
    payload = json.loads(message.content)
    assert payload["total_matches"] == 1
    assert payload["tables"][0]["qualified_name"] == "public.city_parks"


def test_load_postgis_layer_adds_result_and_map_layer(monkeypatch):
    async def fake_load_spatial_table_as_geojson(
        schema_name,
        table_name,
        geom_column,
        row_limit,
    ):
        assert schema_name == "public"
        assert table_name == "city_parks"
        assert geom_column == "geom"
        assert row_limit == 100
        return {
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [114.0, 22.5]},
                        "properties": {"name": "Test Park"},
                    }
                ],
            },
            "feature_count": 1,
            "bounding_box": "POLYGON((114 22.5,114 22.5,114 22.5,114 22.5,114 22.5))",
            "geometry_type": "POINT",
            "srid": 4326,
            "row_limit": 100,
        }

    monkeypatch.setattr(
        postgis_tools,
        "_load_spatial_table_as_geojson",
        fake_load_spatial_table_as_geojson,
    )
    monkeypatch.setattr(
        postgis_tools,
        "store_file_stream",
        lambda filename, stream: (f"/api/stream/{filename}", "stored-layer-id"),
    )

    result = load_postgis_layer.func(
        state=base_state(),
        tool_call_id="load-postgis",
        schema_name="public",
        table_name="city_parks",
        geom_column="geom",
        row_limit=100,
        add_to_map=True,
    )

    assert isinstance(result, Command)
    assert len(result.update["geodata_results"]) == 1
    assert len(result.update["geodata_layers"]) == 1

    layer = result.update["geodata_layers"][0]
    assert layer.id == "stored-layer-id"
    assert layer.name == "public.city_parks"
    assert layer.data_type == DataType.POSTGIS
    assert layer.data_link == "/api/stream/public_city_parks.geojson"
    assert layer.properties["feature_count"] == 1
    assert "Loaded PostGIS layer public.city_parks" in result.update["messages"][0].content


def test_load_postgis_layer_can_leave_layer_in_results_only(monkeypatch):
    async def fake_load_spatial_table_as_geojson(*_args, **_kwargs):
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "feature_count": 0,
            "bounding_box": None,
            "geometry_type": "POLYGON",
            "srid": 4326,
            "row_limit": 10,
        }

    monkeypatch.setattr(
        postgis_tools,
        "_load_spatial_table_as_geojson",
        fake_load_spatial_table_as_geojson,
    )
    monkeypatch.setattr(
        postgis_tools,
        "store_file_stream",
        lambda filename, stream: (f"/api/stream/{filename}", "result-only-id"),
    )

    result = load_postgis_layer.func(
        state=base_state(),
        tool_call_id="load-result-only",
        schema_name="public",
        table_name="districts",
        geom_column="geom",
        row_limit=10,
        add_to_map=False,
    )

    assert len(result.update["geodata_results"]) == 1
    assert "geodata_layers" not in result.update
    assert result.update["geodata_results"][0].name == "public.districts"


# Exercise the real database helpers while emulating psycopg's loop affinity.
# The previous global pool survived asyncio.run(), but its workers did not.
def install_loop_bound_pool(monkeypatch, fail_fetch=False):
    import asyncio
    from contextlib import asynccontextmanager

    pools = []

    class Cursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, query, params=None):
            self.query = query

        async def fetchall(self):
            if fail_fetch:
                raise RuntimeError("metadata query failed")
            return [("public", "city_parks", "geom", "MULTIPOLYGON", 4326)]

        async def fetchone(self):
            if "SELECT type, srid" in self.query:
                return ("MULTIPOLYGON", 4326)
            return ({"type": "FeatureCollection", "features": []}, 0, None)

    class Connection:
        def cursor(self):
            return Cursor()

        async def commit(self):
            pass

    class LoopBoundPool:
        def __init__(self, **kwargs):
            self.loop = None
            self.closed = False
            pools.append(self)

        async def open(self):
            self.loop = asyncio.get_running_loop()

        async def close(self):
            assert self.loop is asyncio.get_running_loop()
            self.closed = True

        async def __aenter__(self):
            await self.open()
            return self

        async def __aexit__(self, *args):
            await self.close()

        @asynccontextmanager
        async def connection(self):
            if self.closed or self.loop is not asyncio.get_running_loop():
                raise RuntimeError("database pool belongs to a different event loop")
            yield Connection()

    monkeypatch.setattr(postgis_tools, "AsyncConnectionPool", LoopBoundPool)
    monkeypatch.setattr(postgis_tools, "PSYCOPG_POOL_AVAILABLE", True)
    monkeypatch.setattr(postgis_tools, "GEODATA_DATABASE_URL", "postgresql://localhost/test")
    monkeypatch.setattr(postgis_tools, "_postgis_pool", None, raising=False)
    return pools


def test_repeated_tool_calls_release_connections_before_loop_closes(monkeypatch):
    pools = install_loop_bound_pool(monkeypatch)

    for index in range(3):
        result = list_postgis_layers.func(
            state=base_state(), tool_call_id=f"list-{index}", query="park"
        )
        message = result.update["messages"][0]
        assert message.status == "success"
        assert json.loads(message.content)["total_matches"] == 1

    assert pools
    assert all(pool.closed and pool.loop.is_closed() for pool in pools)


def test_metadata_failure_still_releases_connections(monkeypatch):
    pools = install_loop_bound_pool(monkeypatch, fail_fetch=True)
    result = list_postgis_layers.func(state=base_state(), tool_call_id="failed-query")
    message = result.update["messages"][0]
    assert message.status == "error"
    assert "metadata query failed" in message.content
    assert all(pool.closed for pool in pools)


def test_list_then_load_across_tool_calls_does_not_reuse_closed_loop(monkeypatch):
    pools = install_loop_bound_pool(monkeypatch)
    postgis_tools._run_async(postgis_tools._list_spatial_tables())
    result = postgis_tools._run_async(
        postgis_tools._load_spatial_table_as_geojson("public", "city_parks", "geom", 1)
    )
    assert result["feature_count"] == 0
    assert all(pool.closed and pool.loop.is_closed() for pool in pools)


def test_sync_tool_can_be_called_from_an_active_event_loop(monkeypatch):
    import asyncio

    pools = install_loop_bound_pool(monkeypatch)

    async def caller():
        result = list_postgis_layers.func(state=base_state(), tool_call_id="async-caller")
        assert result.update["messages"][0].status == "success"

    asyncio.run(caller())
    assert all(pool.closed for pool in pools)
