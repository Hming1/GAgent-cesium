import pytest

from models.sandbox import SandboxExecutionResponse, SandboxGeoJSONOutput
from services.tools import python_analysis_tool
from services.tools.python_analysis_tool import _run_python_analysis_tool


@pytest.mark.asyncio
async def test_run_python_analysis_returns_geojson_results(monkeypatch):
    async def fake_execute(request):
        assert request.analysis_goal == "count features"
        return SandboxExecutionResponse(
            ok=True,
            summary="Python analysis completed.",
            result={"feature_count": 2},
            geojson_outputs=[
                SandboxGeoJSONOutput(
                    name="centroids",
                    title="Computed centroids",
                    description="Derived layer",
                    geojson={
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {"id": 1},
                                "geometry": {"type": "Point", "coordinates": [0, 0]},
                            }
                        ],
                    },
                )
            ],
        )

    monkeypatch.setattr(python_analysis_tool, "execute_python_analysis", fake_execute)
    monkeypatch.setattr(
        python_analysis_tool,
        "store_file",
        lambda filename, content: (f"http://backend/api/stream/{filename}", filename),
    )

    state = {"messages": [], "geodata_layers": [], "geodata_results": []}
    command = await _run_python_analysis_tool(
        state=state,
        tool_call_id="tool-call-1",
        analysis_goal="count features",
        code="result = {'feature_count': 2}",
    )

    assert command.update is not None
    assert "Python analysis completed." in command.update["messages"][0].content
    assert "geodata_results" in command.update
    assert len(command.update["geodata_results"]) == 1
    result_layer = command.update["geodata_results"][0]
    assert result_layer.title == "Computed centroids"
    assert result_layer.data_source_id == "python_analysis"
    assert result_layer.layer_type == "GeoJSON"


@pytest.mark.asyncio
async def test_run_python_analysis_reports_sandbox_configuration_error(monkeypatch):
    async def fake_execute(_request):
        from services.sandbox.client import SandboxClientError

        raise SandboxClientError("sandbox not configured")

    monkeypatch.setattr(python_analysis_tool, "execute_python_analysis", fake_execute)

    state = {"messages": [], "geodata_layers": [], "geodata_results": []}
    command = await _run_python_analysis_tool(
        state=state,
        tool_call_id="tool-call-1",
        analysis_goal="run analysis",
    )

    assert command.update is not None
    assert command.update["messages"][0].content == "sandbox not configured"
    assert "geodata_results" not in command.update


def test_python_analysis_tool_registered():
    from services.default_agent_settings import DEFAULT_AVAILABLE_TOOLS, TOOL_METADATA

    assert "run_python_analysis" in DEFAULT_AVAILABLE_TOOLS
    assert TOOL_METADATA["run_python_analysis"]["category"] == "analysis"
    assert TOOL_METADATA["run_python_analysis"]["enabled"] is True


def test_with_helpers_fallback_injects_find_layer():
    from services.tools.python_analysis_tool import _with_helpers_fallback

    wrapped = _with_helpers_fallback("result = {'ok': True}")
    assert "def find_layer" in wrapped
    assert "result = {'ok': True}" in wrapped
    # Do not double-inject when agent already defined helpers.
    again = _with_helpers_fallback(wrapped)
    assert again.count("def find_layer") == wrapped.count("def find_layer")


@pytest.mark.asyncio
async def test_run_python_analysis_warns_when_layer_truncated(monkeypatch):
    from models.geodata import GeoDataObject
    from models.sandbox import SandboxLayerInput

    async def fake_execute(request):
        assert request.layers
        return SandboxExecutionResponse(
            ok=True,
            summary="Python analysis completed.",
            result={"ok": True},
            geojson_outputs=[],
        )

    def fake_serialize(layer, max_features):
        return SandboxLayerInput(
            layer_id=layer.id,
            data_source_id=layer.data_source_id or "test",
            name=layer.name,
            title=layer.title,
            geojson={"type": "FeatureCollection", "features": []},
            feature_count=900,
            sent_feature_count=max_features,
            truncated=True,
        )

    monkeypatch.setattr(python_analysis_tool, "execute_python_analysis", fake_execute)
    monkeypatch.setattr(python_analysis_tool, "_serialize_layer", fake_serialize)

    layer = GeoDataObject(
        id="clip-1",
        data_source_id="geoprocess",
        data_source="GeoAgentGeoprocess",
        name="parks-clipped-by-buffer",
        title="Parks Clipped by Buffer",
        data_type="GeoJson",
        data_origin="tool",
        data_link="http://example/clip.geojson",
    )
    state = {
        "messages": [],
        "geodata_layers": [],
        "geodata_results": [layer],
        "options": {"session_id": "truncate-test"},
    }
    command = await _run_python_analysis_tool(
        state=state,
        tool_call_id="tool-call-trunc",
        analysis_goal="area top5",
        code="result = {'ok': True}",
        layer_names=["Parks Clipped by Buffer"],
    )

    content = command.update["messages"][0].content
    assert "WARNING" in content
    assert "truncated" in content.lower()
    assert "find_layer" in content
