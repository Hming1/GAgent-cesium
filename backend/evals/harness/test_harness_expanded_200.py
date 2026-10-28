"""Pytest entry for the 200-case expanded deterministic harness suite."""

from __future__ import annotations

import pytest

from evals.harness.runner import SUITE_PATHS, load_cases, run_case


CASES = load_cases(SUITE_PATHS["expanded_200"])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_expanded_200_harness_case(case):
    result = run_case(case)
    assert result.passed, (
        f"{result.id} failed: {result.failures}\n"
        f"checks={result.checks}\ndetails={result.details}"
    )


def test_expanded_200_suite_shape():
    assert len(CASES) == 200
    modes = {case.get("mode") for case in CASES}
    skills = {case.get("skill") for case in CASES}
    assert "routing" in modes
    assert "infer_mapping" in modes
    assert "plan_aliases" in modes
    assert "registry_tools" in modes
    assert "system_prompt" in modes
    assert "analyze_fixture" in modes
    assert "postgis" in skills
    assert "inefficient_space" in skills
    assert "registry" in skills
    assert "combined" in skills
    assert "none" in skills
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids)), "duplicate case ids"
