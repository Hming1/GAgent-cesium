"""Canonical indicator fields and land-use keyword hints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from services.inefficient_space.schemas import FieldMapping

LAND_USE_HINTS: Dict[str, List[str]] = {
    "industrial": ["工业", "工矿", "仓储", "厂房", "M", "industrial", "factory"],
    "commercial": ["商业", "商服", "商务", "零售", "C", "commercial", "retail"],
    "residential": ["居住", "住宅", "住", "R", "residential", "housing"],
    "idle_vacant": ["闲置", "空地", "空闲", "未利用", "vacant", "idle", "裸地"],
}

TYPE_LABELS: Dict[str, str] = {
    "idle_vacant": "闲置空地",
    "industrial": "工业低效",
    "commercial": "商业低效",
    "residential": "居住低效",
    "efficient": "非低效",
}

TYPE_COLORS: Dict[str, str] = {
    "idle_vacant": "#7f8c8d",
    "industrial": "#c0392b",
    "commercial": "#e67e22",
    "residential": "#8e44ad",
    "efficient": "#27ae60",
}

FIELD_ALIASES: Dict[str, List[str]] = {
    "far": ["far", "容积率", "plot_ratio", "floor_area_ratio", "rjl"],
    "building_density": [
        "building_density",
        "建筑密度",
        "density",
        "jzmd",
        "bd",
    ],
    "idle_years": ["idle_years", "闲置年限", "idle_year", "vacant_years"],
    "tax_output": [
        "tax_output",
        "税收产出",
        "税收",
        "tax",
        "tax_per_mu",
        "shuishou",
    ],
    "land_use": ["land_use", "用地性质", "用地类型", "ydxz", "landuse", "type"],
}


def resolve_column(
    columns: List[str], preferred: Optional[str], aliases: List[str]
) -> Optional[str]:
    """Pick the best matching column from preferred name then aliases."""
    lower_map = {str(c).lower(): c for c in columns}
    candidates: List[str] = []
    if preferred:
        candidates.append(preferred)
    candidates.extend(aliases)
    for name in candidates:
        if name in columns:
            return name
        lowered = name.lower()
        if lowered in lower_map:
            return lower_map[lowered]
    return None


def apply_field_mapping(df: pd.DataFrame, mapping: FieldMapping) -> pd.DataFrame:
    """Copy mapped source columns onto canonical indicator names."""
    out = df.copy()
    columns = [str(c) for c in out.columns]
    mapping_dict = mapping.model_dump()
    for canonical, preferred in mapping_dict.items():
        if canonical == "enterprise_tax_field":
            continue
        aliases = FIELD_ALIASES.get(canonical, [canonical])
        source = resolve_column(columns, preferred, aliases)
        if source is None:
            out[canonical] = None
        elif source == canonical:
            continue
        else:
            out[canonical] = out[source]
    return out


def to_float(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_land_use(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def classify_land_use_family(land_use: str) -> Optional[str]:
    text = land_use.lower()
    for family, hints in LAND_USE_HINTS.items():
        for hint in hints:
            if hint.lower() in text:
                return family
    return None


CANONICAL_FIELDS = (
    "far",
    "building_density",
    "idle_years",
    "tax_output",
    "land_use",
)

# Core fields that strongly affect classification quality.
CRITICAL_FIELDS = ("land_use", "far", "building_density")


def infer_mapping_from_columns(columns: List[str]) -> Dict[str, Any]:
    """Infer FieldMapping-like dict from raw attribute column names.

    Returns mapping, matched/missing lists, and at most one clarifying question
    when critical fields cannot be resolved.
    """
    mapping: Dict[str, Optional[str]] = {}
    matched: Dict[str, str] = {}
    missing: List[str] = []

    for canonical in CANONICAL_FIELDS:
        aliases = FIELD_ALIASES.get(canonical, [canonical])
        source = resolve_column(columns, preferred=None, aliases=aliases)
        mapping[canonical] = source
        if source:
            matched[canonical] = source
        else:
            missing.append(canonical)

    mapping["enterprise_tax_field"] = resolve_column(
        columns,
        preferred=None,
        aliases=FIELD_ALIASES.get("tax_output", ["tax_output"]),
    )

    clarifying_question: Optional[str] = None
    critical_missing = [name for name in CRITICAL_FIELDS if name in missing]
    if critical_missing:
        labels = {
            "far": "容积率",
            "building_density": "建筑密度",
            "idle_years": "闲置年限",
            "tax_output": "税收产出",
            "land_use": "用地性质",
        }
        first = critical_missing[0]
        clarifying_question = (
            f"地块图层中未找到「{labels.get(first, first)}」对应字段。"
            f"当前字段有：{', '.join(columns[:30])}。"
            f"请告知该指标对应的属性字段名是什么？"
        )

    return {
        "field_mapping": mapping,
        "matched": matched,
        "missing": missing,
        "critical_missing": critical_missing,
        "clarifying_question": clarifying_question,
        "columns": list(columns),
    }
