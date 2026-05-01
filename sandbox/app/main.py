from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.runner import execute_python


class SandboxLayerInput(BaseModel):
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


class SandboxExecutionRequest(BaseModel):
    analysis_goal: str
    code: str = ""
    layers: List[SandboxLayerInput] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    max_seconds: Optional[int] = None
    max_output_bytes: Optional[int] = None


app = FastAPI(title="NaLaMap Python Analysis Sandbox", version="0.1.0")


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/execute")
async def execute(request: SandboxExecutionRequest) -> Dict[str, Any]:
    return execute_python(request.model_dump(mode="json"))
