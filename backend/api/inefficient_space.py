"""HTTP API for urban inefficient-space identification."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from services.inefficient_space.analyzer import analyze_inefficient_space, get_presets
from services.inefficient_space.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    InefficientSpacePresets,
)

router = APIRouter(prefix="/inefficient-space", tags=["inefficient-space"])
logger = logging.getLogger(__name__)


@router.get("/presets", response_model=InefficientSpacePresets)
async def inefficient_space_presets() -> InefficientSpacePresets:
    """Return default field mapping, thresholds and type metadata."""
    return get_presets()


@router.post("/analyze", response_model=AnalyzeResponse)
async def inefficient_space_analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Run rule-based inefficient-space classification on a parcel layer."""
    try:
        return analyze_inefficient_space(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IOError as exc:
        logger.exception("Failed to load layer for inefficient-space analysis")
        raise HTTPException(status_code=400, detail=f"无法加载图层: {exc}") from exc
    except Exception as exc:
        logger.exception("Inefficient-space analysis failed")
        raise HTTPException(status_code=500, detail=f"判别失败: {exc}") from exc
