"""Tests for the GridWorld evaluation & dataset-generation harness.

Covers reproducibility (same seed → identical rollout), the controller
comparison result that anchors the portfolio story (localized shedding clears a
radial overload that do-nothing leaves standing), metric correctness, and the
shape contract of the generated trajectory tensors.
"""

from __future__ import annotations

import numpy as np
import pytest

from eval.controllers import DoNothingController, GreedyRuleController
from eval.metrics import StepSummary, compute_metrics
from eval.runner import run_scenario
from eval.scenario import Scenario, ScenarioEvent, scenario_library
from physics.fault_handler import FaultType
from physics.network import BUSES, LINES, TRANSFORMERS


# A short scenario keeps determinism checks fast.
def _short_scenario() -> Scenario:
    return Scenario(
        id="t_short", family="gen_dropout", seed=42, settle_s=2.0, duration_s=8.0,
        events=[ScenarioEvent(at_s=2.0, fault_type=FaultType.GEN_DROPOUT,
                              target_rid="ri.city-grid.main.generator.3")],
    )


def test_scenario_library_is_wellformed():
    lib = scenario_library()
    assert lib, "library is empty"
    families = {s.family for s in lib.values()}
    # The research-plan fault families must all be represented.
    assert {"gen_dropout", "line_trip", "load_spike", "trafo_trip"} <= families
    for s in lib.values():
        assert s.events, f"{s.id} has no events"
        assert s.total_s > s.settle_s


def test_rollout_is_deterministic():
    """Same scenario + controller + seed → bit-identical metrics and traces."""
    scen = _short_scenario()
    a = run_scenario(scen, GreedyRuleController())
    b = run_scenario(scen, GreedyRuleController())
    assert a.metrics.model_dump() == b.metrics.model_dump()
    assert [s.frequency_hz for s in a.steps] == [s.frequency_hz for s in b.steps]
    assert a.metrics.n_steps > 0


def test_do_nothing_takes_no_actions():
    res = run_scenario(_short_scenario(), DoNothingController())
    assert res.metrics.n_actions == 0
    assert res.metrics.load_shed_mw == 0.0
    assert not res.action_log


@pytest.fixture(scope="module")
def trafo_trip_results():
    scen = scenario_library()["trafo_trip_radial"]
    do_nothing = run_scenario(scen, DoNothingController())
    greedy = run_scenario(scen, GreedyRuleController())
    return do_nothing, greedy


def test_do_nothing_leaves_radial_overload_unresolved(trafo_trip_results):
    do_nothing, _ = trafo_trip_results
    assert not do_nothing.metrics.final_secure
    assert do_nothing.metrics.violation_seconds > 0


def test_greedy_recovers_radial_overload_and_beats_do_nothing(trafo_trip_results):
    """The anchor result: localized load-shedding restores security and the
    rule controller's total cost is far below the passive baseline."""
    do_nothing, greedy = trafo_trip_results
    assert greedy.metrics.final_secure
    assert greedy.metrics.time_to_recover_s is not None
    assert greedy.metrics.load_shed_mw > 0          # it did shed
    assert greedy.metrics.load_shed_mw < 150         # but only locally, not wholesale
    assert greedy.metrics.cost < do_nothing.metrics.cost * 0.5


def test_compute_metrics_handles_empty_run():
    m = compute_metrics("x", "y", [], 0.1, 0, 0.0)
    assert m.n_steps == 0
    assert m.cost == 0.0


def test_time_to_recover_none_when_never_insecure():
    steps = [
        StepSummary(sim_time_s=t / 10, frequency_hz=60.0, total_generation_mw=100,
                    total_load_mw=100, max_line_loading_pct=50, max_voltage_dev_pu=0.01,
                    n_violations=0, shed_mw_cumulative=0.0, secure=True)
        for t in range(20)
    ]
    m = compute_metrics("c", "s", steps, 0.1, 0, 1.0)
    assert m.time_to_recover_s is None
    assert m.final_secure


def test_trajectory_tensor_shapes():
    import os
    import shutil

    out_dir = os.path.join(os.path.dirname(__file__), "_tmp_traj")
    shutil.rmtree(out_dir, ignore_errors=True)

    scen = _short_scenario()
    res = run_scenario(scen, GreedyRuleController(), record_trajectory=True)
    rec = res.trajectory
    assert rec is not None and rec.n_steps == res.metrics.n_steps

    try:
        path = rec.save(out_dir)
        d = np.load(path)
        T = rec.n_steps
        assert d["node_features"].shape == (T, len(BUSES), 7)
        assert d["edge_features"].shape == (T, len(LINES) + len(TRANSFORMERS), 6)
        assert d["edge_index"].shape == (2, len(LINES) + len(TRANSFORMERS))
        assert d["global_features"].shape == (T, 6)
        assert d["actions"].shape == (T, 4)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
