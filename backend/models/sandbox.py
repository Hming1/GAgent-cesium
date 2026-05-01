from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SandboxLayerInput(BaseModel):
    """Layer payload passed from the backend to the analysis sandbox."""

    layer_id: str
    data_source_id: str
    name: str
    title: Optional[str] = None
    data_link: Optional[str] = None
    layer_type: Optional[str] = None
    geojson: Optional[Dict[str, Any]] = None
    feature_count: Optional[int] = None
    sent_feature_count: Optional[int] = None
    truncated: bool = False
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SandboxArtifact(BaseModel):
    """Non-map artifact returned by the sandbox."""

    name: str
    content_type: str = "text/plain"
    content: Optional[str] = None
    uri: Optional[str] = None


class SandboxGeoJSONOutput(BaseModel):
    """Map output returned by the sandbox."""

    name: str
    geojson: Dict[str, Any]
    title: Optional[str] = None
    description: Optional[str] = None


class SandboxExecutionRequest(BaseModel):
    """Request contract for Python analysis sandbox execution."""

    analysis_goal: str
    code: str = ""
    layers: List[SandboxLayerInput] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    max_seconds: Optional[int] = None
    max_output_bytes: Optional[int] = None


class SandboxExecutionResponse(BaseModel):
    """Response contract returned by the Python analysis sandbox."""

    ok: bool
    summary: str = ""
    stdout: str = ""
    stderr: str = ""
    result: Optional[Any] = None
    artifacts: List[SandboxArtifact] = Field(default_factory=list)
    geojson_outputs: List[SandboxGeoJSONOutput] = Field(default_factory=list)
    error: Optional[str] = None
