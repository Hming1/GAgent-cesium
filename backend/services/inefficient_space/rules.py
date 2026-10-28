"""Rule engine for urban inefficient-space classification."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from services.inefficient_space.field_mapping import (
    classify_land_use_family,
    normalize_land_use,
    to_float,
)
from services.inefficient_space.schemas import ThresholdBundle, TypeThresholds


def _score_idle(attrs: Dict[str, Any], thresholds: TypeThresholds) -> Tuple[float, List[str]]:
    matched: List[str] = []
    score = 0.0
    idle_years = to_float(attrs.get("idle_years"))
    far = to_float(attrs.get("far"))
    density = to_float(attrs.get("building_density"))
    land_family = classify_land_use_family(normalize_land_use(attrs.get("land_use")))

    if land_family == "idle_vacant":
        matched.append("land_use_idle")
        score += 1.0
    if idle_years is not None and idle_years >= thresholds.min_idle_years:
        matched.append("idle_years")
        score += 1.0
    if (
        far is not None
        and density is not None
        and far <= thresholds.near_zero_far
        and density <= thresholds.near_zero_density
    ):
        matched.append("near_zero_development")
        score += 1.0
    return score, matched


def _score_indicators(attrs: Dict[str, Any], thresholds: TypeThresholds) -> Tuple[float, List[str]]:
    matched: List[str] = []
    score = 0.0
    far = to_float(attrs.get("far"))
    density = to_float(attrs.get("building_density"))
    idle_years = to_float(attrs.get("idle_years"))
    tax_output = to_float(attrs.get("tax_output"))

    if far is not None and far < thresholds.max_far:
        matched.append("low_far")
        score += 1.0
    if density is not None and density < thresholds.max_building_density:
        matched.append("low_building_density")
        score += 1.0
    if idle_years is not None and idle_years >= thresholds.min_idle_years:
        matched.append("idle_years")
        score += 1.0
    if tax_output is not None and tax_output < thresholds.min_tax_output:
        matched.append("low_tax_output")
        score += 1.0

    poi_count = to_float(attrs.get("poi_count"))
    if poi_count is not None and poi_count <= 1:
        matched.append("low_poi_activity")
        score += 0.5

    return score, matched


def classify_feature(
    attrs: Dict[str, Any],
    thresholds: ThresholdBundle,
    enabled_types: Sequence[str],
) -> Dict[str, Any]:
    """Classify one parcel and return result attributes.

    Priority: idle_vacant first, then industrial / commercial / residential
    routed by land-use family.
    """
    enabled = set(enabled_types)

    idle_score, idle_rules = _score_idle(attrs, thresholds.idle_vacant)
    if "idle_vacant" in enabled and idle_score > 0:
        return {
            "inefficient_type": "idle_vacant",
            "inefficient_score": idle_score,
            "matched_rules": ",".join(idle_rules),
            "is_inefficient": True,
        }

    land_family = classify_land_use_family(normalize_land_use(attrs.get("land_use")))
    family_order = ("industrial", "commercial", "residential")

    if land_family in family_order and land_family in enabled:
        family_thresholds: TypeThresholds = getattr(thresholds, land_family)
        score, rules = _score_indicators(attrs, family_thresholds)
        if score > 0:
            return {
                "inefficient_type": land_family,
                "inefficient_score": score,
                "matched_rules": ",".join(rules),
                "is_inefficient": True,
            }

    # Unknown land use: require at least two indicator hits against any enabled family.
    if land_family is None:
        best = None
        for family in family_order:
            if family not in enabled:
                continue
            family_thresholds = getattr(thresholds, family)
            score, rules = _score_indicators(attrs, family_thresholds)
            if score < 2:
                continue
            if best is None or score > best[1]:
                best = (family, score, rules)
        if best is not None:
            family, score, rules = best
            return {
                "inefficient_type": family,
                "inefficient_score": score,
                "matched_rules": ",".join(rules),
                "is_inefficient": True,
            }

    return {
        "inefficient_type": "efficient",
        "inefficient_score": 0.0,
        "matched_rules": "",
        "is_inefficient": False,
    }
