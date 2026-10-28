"""Pytest entry for general Agent capability harness (excludes inefficient-space)."""

from __future__ import annotations

import pytest

from evals.harness.runner import SUITE_PATHS, load_cases, run_case


CASES = load_cases(SUITE_PATHS["agent"])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_agent_core_harness_case(case):
    result = run_case(case)
    assert result.passed, (
        f"{result.id} failed: {result.failures}\n"
        f"checks={result.checks}\ndetails={result.details}"
    )


def test_agent_core_suite_shape():
    assert len(CASES) == 10
    skills = {case.get("skill") for case in CASES}
    assert "postgis" in skills
    assert "registry" in skills
    assert "inefficient_space" not in skills
    assert all(case.get("mode") != "analyze_fixture" for case in CASES)
    assert all(case.get("mode") != "infer_mapping" for case in CASES)
    modes = {case.get("mode") for case in CASES}
    assert "routing" in modes
    assert "registry_tools" in modes
    assert "system_prompt" in modes
