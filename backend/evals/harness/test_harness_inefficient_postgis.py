"""Pytest entry for inefficient-space + PostGIS harness cases."""

from __future__ import annotations

import pytest

from evals.harness.runner import load_cases, run_case


CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_inefficient_postgis_harness_case(case):
    result = run_case(case)
    assert result.passed, (
        f"{result.id} failed: {result.failures}\n"
        f"checks={result.checks}\ndetails={result.details}"
    )


def test_harness_suite_has_ten_cases():
    assert len(CASES) == 10
    skills = {case.get("skill") for case in CASES}
    assert "inefficient_space" in skills
    assert "postgis" in skills
    assert "combined" in skills
