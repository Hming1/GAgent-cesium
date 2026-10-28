"""Deterministic harness runner for agent capability suites."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from services.agent_skills import (
    build_available_tools,
    build_plan_tool_aliases,
    build_system_prompt,
    build_tool_metadata,
    required_tool_keys_for_query,
)

HARNESS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = HARNESS_DIR / "fixtures"

SUITE_PATHS = {
    "agent": HARNESS_DIR / "cases_agent_core.json",
    "inefficient_postgis": HARNESS_DIR / "cases_inefficient_postgis.json",
    "expanded_200": HARNESS_DIR / "cases_expanded_200.json",
}

# Backward-compatible default for older CLI usage.
CASES_PATH = SUITE_PATHS["inefficient_postgis"]


@dataclass
class CaseResult:
    id: str
    skill: str
    mode: str
    passed: bool
    checks: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


def load_cases(path: Optional[Union[Path, str]] = None) -> List[Dict[str, Any]]:
    case_path = Path(path) if path is not None else CASES_PATH
    with open(case_path, encoding="utf-8") as handle:
        return json.load(handle)


def _check_contains(actual: List[str], expected: List[str], label: str, result: CaseResult) -> None:
    missing = [item for item in expected if item not in actual]
    if missing:
        result.failures.append(f"{label} missing: {missing}; actual={actual}")
    else:
        result.checks.append(f"{label} ok: {expected}")


def _check_forbidden(
    actual: List[str], forbidden: List[str], label: str, result: CaseResult
) -> None:
    hit = [item for item in forbidden if item in actual]
    if hit:
        result.failures.append(f"{label} forbidden present: {hit}")
    else:
        result.checks.append(f"{label} forbidden absent ok")


def run_routing_case(case: Dict[str, Any]) -> CaseResult:
    result = CaseResult(
        id=case["id"],
        skill=case.get("skill", ""),
        mode="routing",
        passed=False,
    )
    available = case.get("available_tools") or []
    required = required_tool_keys_for_query(case["query"], available)
    result.details["required_tools"] = required
    _check_contains(required, case.get("expect_required_tools") or [], "required_tools", result)
    _check_forbidden(required, case.get("forbid_required_tools") or [], "required_tools", result)
    result.passed = not result.failures
    return result


def run_infer_mapping_case(case: Dict[str, Any]) -> CaseResult:
    from services.inefficient_space.field_mapping import infer_mapping_from_columns

    result = CaseResult(
        id=case["id"],
        skill=case.get("skill", ""),
        mode="infer_mapping",
        passed=False,
    )
    inferred = infer_mapping_from_columns(case.get("columns") or [])
    result.details = {
        "matched": inferred.get("matched"),
        "missing": inferred.get("missing"),
        "critical_missing": inferred.get("critical_missing"),
        "clarifying_question": inferred.get("clarifying_question"),
    }

    for key, expected_col in (case.get("expect_matched") or {}).items():
        actual = (inferred.get("matched") or {}).get(key)
        if actual != expected_col:
            result.failures.append(f"matched[{key}] expected={expected_col} actual={actual}")
        else:
            result.checks.append(f"matched[{key}]={actual}")

    for key in case.get("expect_critical_missing_contains") or []:
        if key not in (inferred.get("critical_missing") or []):
            result.failures.append(f"critical_missing missing {key}")
        else:
            result.checks.append(f"critical_missing has {key}")

    expect_q = bool(case.get("expect_clarifying_question"))
    has_q = bool(inferred.get("clarifying_question"))
    if expect_q != has_q:
        result.failures.append(f"clarifying_question expected={expect_q} actual={has_q}")
    else:
        result.checks.append(f"clarifying_question={has_q}")

    result.passed = not result.failures
    return result


def run_analyze_fixture_case(case: Dict[str, Any], monkeypatch_store: bool = True) -> CaseResult:
    from services.inefficient_space.analyzer import analyze_inefficient_space
    from services.inefficient_space.schemas import AnalyzeRequest

    result = CaseResult(
        id=case["id"],
        skill=case.get("skill", ""),
        mode="analyze_fixture",
        passed=False,
    )
    fixture_path = FIXTURES_DIR / case["fixture"]
    if not fixture_path.exists():
        result.failures.append(f"fixture not found: {fixture_path}")
        return result

    stored: Dict[str, Any] = {}

    def fake_store_file(name: str, content: bytes):
        stored["name"] = name
        stored["content"] = content
        return "http://localhost:8000/api/stream/harness.geojson", "harness-id"

    if monkeypatch_store:
        import services.inefficient_space.analyzer as analyzer_mod

        original = analyzer_mod.store_file
        analyzer_mod.store_file = fake_store_file
    else:
        original = None

    try:
        response = analyze_inefficient_space(
            AnalyzeRequest(
                parcel_data_link=str(fixture_path),
                include_non_match=False,
            )
        )
        summary = response.summary.model_dump()
        result.details["summary"] = summary
        matched = int(summary.get("matched") or 0)
        min_matched = int(case.get("expect_min_matched") or 0)
        if matched < min_matched:
            result.failures.append(f"matched={matched} < expect_min_matched={min_matched}")
        else:
            result.checks.append(f"matched={matched} >= {min_matched}")

        types_present = {
            key
            for key, stats in (summary.get("by_type") or {}).items()
            if (stats.get("count") or 0) > 0
        }
        for expected in case.get("expect_types_present") or []:
            if expected not in types_present:
                result.failures.append(f"expected type absent: {expected}")
            else:
                result.checks.append(f"type present: {expected}")
        for absent in case.get("expect_types_absent") or []:
            if absent in types_present:
                result.failures.append(f"unexpected type present: {absent}")
            else:
                result.checks.append(f"type absent ok: {absent}")

        if stored.get("content"):
            fc = json.loads(stored["content"].decode("utf-8"))
            feature_types = {
                f.get("properties", {}).get("inefficient_type") for f in fc.get("features", [])
            }
            result.details["feature_types"] = sorted(t for t in feature_types if t)
    finally:
        if monkeypatch_store and original is not None:
            import services.inefficient_space.analyzer as analyzer_mod

            analyzer_mod.store_file = original

    result.passed = not result.failures
    return result


def run_plan_aliases_case(case: Dict[str, Any]) -> CaseResult:
    result = CaseResult(
        id=case["id"],
        skill=case.get("skill", ""),
        mode="plan_aliases",
        passed=False,
    )
    aliases = build_plan_tool_aliases()
    for alias, expected in (case.get("aliases") or {}).items():
        actual = aliases.get(alias)
        if actual != expected:
            result.failures.append(f"alias[{alias}] expected={expected} actual={actual}")
        else:
            result.checks.append(f"alias[{alias}]={actual}")
    result.passed = not result.failures
    return result


def run_registry_tools_case(case: Dict[str, Any]) -> CaseResult:
    result = CaseResult(
        id=case["id"],
        skill=case.get("skill", ""),
        mode="registry_tools",
        passed=False,
    )
    tools = build_available_tools()
    tool_keys = sorted(tools.keys())
    metadata = build_tool_metadata()
    result.details["tool_count"] = len(tool_keys)

    present = case.get("expect_tools_present") or []
    missing = [key for key in present if key not in tools]
    if missing:
        result.failures.append(f"tools missing: {missing}")
    else:
        result.checks.append(f"tools present ok: {present}")

    forbidden = case.get("forbid_tools_present") or []
    hit = [key for key in forbidden if key in tools]
    if hit:
        result.failures.append(f"forbidden tools present: {hit}")
    elif forbidden:
        result.checks.append("forbidden tools absent ok")

    for tool_key, expect_meta in (case.get("expect_tool_metadata") or {}).items():
        actual_meta = metadata.get(tool_key) or {}
        for field_name, expected_value in expect_meta.items():
            actual_value = actual_meta.get(field_name)
            if actual_value != expected_value:
                result.failures.append(
                    f"metadata[{tool_key}].{field_name} expected={expected_value} "
                    f"actual={actual_value}"
                )
            else:
                result.checks.append(f"metadata[{tool_key}].{field_name}={actual_value}")

    result.passed = not result.failures
    return result


def run_system_prompt_case(case: Dict[str, Any]) -> CaseResult:
    result = CaseResult(
        id=case["id"],
        skill=case.get("skill", ""),
        mode="system_prompt",
        passed=False,
    )
    prompt = build_system_prompt()
    result.details["prompt_length"] = len(prompt)

    for snippet in case.get("expect_contains") or []:
        if snippet not in prompt:
            result.failures.append(f"prompt missing snippet: {snippet!r}")
        else:
            result.checks.append(f"prompt contains: {snippet!r}")

    for snippet in case.get("forbid_contains") or []:
        if snippet in prompt:
            result.failures.append(f"prompt unexpectedly contains: {snippet!r}")
        else:
            result.checks.append(f"prompt forbid ok: {snippet!r}")

    result.passed = not result.failures
    return result


def run_case(case: Dict[str, Any]) -> CaseResult:
    mode = case.get("mode")
    if mode == "routing":
        return run_routing_case(case)
    if mode == "infer_mapping":
        return run_infer_mapping_case(case)
    if mode == "analyze_fixture":
        return run_analyze_fixture_case(case)
    if mode == "plan_aliases":
        return run_plan_aliases_case(case)
    if mode == "registry_tools":
        return run_registry_tools_case(case)
    if mode == "system_prompt":
        return run_system_prompt_case(case)
    return CaseResult(
        id=case.get("id", "unknown"),
        skill=case.get("skill", ""),
        mode=str(mode),
        passed=False,
        failures=[f"unsupported mode: {mode}"],
    )


def run_all(
    cases: Optional[List[Dict[str, Any]]] = None,
    path: Optional[Union[Path, str]] = None,
) -> Dict[str, Any]:
    loaded = cases if cases is not None else load_cases(path)
    results = [run_case(case) for case in loaded]
    passed = sum(1 for item in results if item.passed)
    total = len(results)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round((passed / total) if total else 0.0, 4),
        "results": [asdict(item) for item in results],
    }


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        cases_path = SUITE_PATHS["agent"]
    elif args[0] in SUITE_PATHS:
        cases_path = SUITE_PATHS[args[0]]
    else:
        cases_path = Path(args[0])
    report = run_all(path=cases_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
