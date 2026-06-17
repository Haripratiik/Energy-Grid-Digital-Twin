"""Tests for N-1 contingency analysis.

These also pin the physics down: the meshed 400 kV transmission core should be
N-1 secure, while the radial distribution edges should surface as the weak
points — a property of the network design that a regression here would catch.
"""

from __future__ import annotations

import pytest

from physics.contingency import (
    ContingencyAnalyzer,
    ContingencyKind,
    ContingencyOutcome,
)
from physics.network import SLACK_BUS
from physics.swing import GridSimulator


@pytest.fixture(scope="module")
def report():
    sim = GridSimulator()
    for _ in range(25):  # let the system settle
        sim.step()
    analyzer = ContingencyAnalyzer()
    return analyzer.analyze(sim.get_state())


def test_base_case_is_secure(report):
    """At nominal equilibrium the grid itself must be within limits."""
    assert report.base_converged
    assert report.base_secure


def test_every_in_service_element_is_screened(report):
    """N-1 enumerates all lines + transformers + non-slack generators."""
    # 91 lines + 21 transformers + (12 gens - 1 slack) = 123
    assert report.n_screened == 123


def test_slack_generator_is_excluded(report):
    """Tripping the single slack machine is out of N-1 scope; never a candidate."""
    gen_ids = {r.contingency_id for r in report.results
               if r.kind == ContingencyKind.GENERATOR}
    assert f"GEN-bus{SLACK_BUS}" not in gen_ids


def test_results_sorted_by_descending_severity(report):
    sev = [r.severity for r in report.results]
    assert sev == sorted(sev, reverse=True)


def test_meshed_400kv_core_is_n1_secure(report):
    """The 400 kV ring (lines 0-7) is meshed and should survive any single loss."""
    by_id = {r.contingency_id: r for r in report.results}
    for i in range(8):  # the 8 HV ring/radial lines
        r = by_id[f"LINE-{i}"]
        assert r.outcome == ContingencyOutcome.SECURE, (
            f"LINE-{i} unexpectedly insecure: {r.outcome} (sev {r.severity})"
        )


def test_insecure_contingencies_exist_and_are_ranked_first(report):
    """The grid has known radial weak points; the worst must top the list."""
    assert report.n_insecure > 0
    assert report.worst is not None
    assert report.worst.outcome != ContingencyOutcome.SECURE
    assert report.worst is report.results[0]


def test_insecure_results_carry_violation_detail(report):
    for r in report.results:
        if r.outcome in (ContingencyOutcome.THERMAL_OVERLOAD,
                         ContingencyOutcome.VOLTAGE_VIOLATION):
            assert r.n_violations > 0
            assert r.violations, f"{r.contingency_id} insecure but no violation detail"
