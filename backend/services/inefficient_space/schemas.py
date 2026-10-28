"""Pydantic models for inefficient-space analysis."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from models.geodata import GeoDataObject


INEFFICIENT_TYPES = (
    "idle_vacant",
    "industrial",
    "commercial",
    "residential",
)


class FieldMapping(BaseModel):
    """Maps source attribute columns onto canonical indicator names."""

    far: Optional[str] = Field(default="far", description="容积率字段名")
    building_density: Optional[str] = Field(
        default="building_density", description="建筑密度字段名"
    )
    idle_years: Optional[str] = Field(default="idle_years", description="闲置年限字段名")
    tax_output: Optional[str] = Field(default="tax_output", description="税收产出字段名")
    land_use: Optional[str] = Field(default="land_use", description="用地性质字段名")
    enterprise_tax_field: Optional[str] = Field(
        default="tax_output",
        description="企业图层用于挂接的税收字段名",
    )


class TypeThresholds(BaseModel):
    """Thresholds used when scoring a single inefficient-space family."""

    max_far: float = Field(default=0.8, description="容积率低于该值视为偏低")
    max_building_density: float = Field(default=0.3, description="建筑密度低于该值视为偏低")
    min_idle_years: float = Field(default=2.0, description="闲置年限达到该值视为闲置风险")
    min_tax_output: float = Field(default=50.0, description="税收产出低于该值视为偏低")
    near_zero_far: float = Field(default=0.05, description="接近零容积率阈值")
    near_zero_density: float = Field(default=0.05, description="接近零建筑密度阈值")


class ThresholdBundle(BaseModel):
    idle_vacant: TypeThresholds = Field(default_factory=TypeThresholds)
    industrial: TypeThresholds = Field(
        default_factory=lambda: TypeThresholds(
            max_far=1.0,
            max_building_density=0.35,
            min_idle_years=2.0,
            min_tax_output=80.0,
        )
    )
    commercial: TypeThresholds = Field(
        default_factory=lambda: TypeThresholds(
            max_far=1.5,
            max_building_density=0.4,
            min_idle_years=2.0,
            min_tax_output=120.0,
        )
    )
    residential: TypeThresholds = Field(
        default_factory=lambda: TypeThresholds(
            max_far=1.2,
            max_building_density=0.3,
            min_idle_years=2.0,
            min_tax_output=40.0,
        )
    )


class AnalyzeRequest(BaseModel):
    parcel_data_link: str = Field(..., description="地块矢量图层 data_link")
    poi_data_link: Optional[str] = Field(default=None, description="可选 POI 图层")
    enterprise_data_link: Optional[str] = Field(default=None, description="可选企业工商图层")
    field_mapping: FieldMapping = Field(default_factory=FieldMapping)
    thresholds: ThresholdBundle = Field(default_factory=ThresholdBundle)
    enabled_types: List[str] = Field(
        default_factory=lambda: list(INEFFICIENT_TYPES),
        description="启用的低效类型",
    )
    include_non_match: bool = Field(
        default=False,
        description="是否在结果中保留未命中低效规则的要素",
    )
    result_name: Optional[str] = Field(default=None, description="结果图层名称")


class TypeSummary(BaseModel):
    count: int = 0
    area_sqm: float = 0.0


class AnalyzeSummary(BaseModel):
    total: int = 0
    matched: int = 0
    by_type: Dict[str, TypeSummary] = Field(default_factory=dict)
    area_stats: Dict[str, float] = Field(default_factory=dict)


class AnalyzeResponse(BaseModel):
    layer: GeoDataObject
    summary: AnalyzeSummary


class InefficientSpacePresets(BaseModel):
    field_mapping: FieldMapping
    thresholds: ThresholdBundle
    enabled_types: List[str]
    land_use_hints: Dict[str, List[str]]
    type_labels: Dict[str, str]
    type_colors: Dict[str, str]
