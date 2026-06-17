"""Tests for the SQLite persistence layer."""

from __future__ import annotations

from eval.controllers import GreedyRuleController
from eval.runner import run_scenario
from eval.scenario import Scenario, ScenarioEvent
from physics.fault_handler import FaultType
from physics.swing import GridSimulator
from storage import GridStore


def _store() -> GridStore:
    return GridStore(":memory:")  # isolated, no filesystem


def test_schema_initialises_empty():
    s = _store()
    assert s.counts() == {"telemetry": 0, "decisions": 0, "eval_runs": 0}
    s.close()


def test_record_and_query_telemetry():
    s = _store()
    sim = GridSimulator()
    for _ in range(5):
        st = sim.step()
        if st is not None:
            s.record_telemetry(st, run_id="live")
    rows = s.telemetry_history(run_id="live", limit=100)
    assert len(rows) >= 1
    r = rows[-1]
    assert r["frequency_hz"] > 0
    assert "n_violations" in r and "max_line_loading_pct" in r
    s.close()


def test_decision_upsert_updates_status():
    s = _store()
    decision = {
        "id": "d-1", "risk_level": "CONTROLLED", "status": "PENDING",
        "executed_by": None,
        "action": {"action_type": "GEN_SETPOINT", "target_rid": "ri.x.1",
                   "estimated_impact_mw": 40.0, "rationale": "ramp"},
    }
    s.record_decision(decision)
    assert s.counts()["decisions"] == 1

    decision["status"] = "EXECUTED"
    decision["executed_by"] = "OPERATOR"
    s.record_decision(decision)               # upsert, not duplicate
    rows = s.decision_history()
    assert s.counts()["decisions"] == 1
    assert rows[0]["status"] == "EXECUTED"
    assert rows[0]["executed_by"] == "OPERATOR"
    s.close()


def test_eval_run_persisted_from_metrics():
    s = _store()
    scen = Scenario(
        id="t", family="gen_dropout", seed=1, settle_s=2.0, duration_s=6.0,
        events=[ScenarioEvent(at_s=2.0, fault_type=FaultType.GEN_DROPOUT,
                              target_rid="ri.city-grid.main.generator.3")],
    )
    res = run_scenario(scen, GreedyRuleController())
    s.record_eval_run(res.metrics.model_dump(), seed=scen.seed)
    runs = s.eval_runs(scenario_id="t")
    assert len(runs) == 1
    assert runs[0]["controller"] == "greedy_rule"
    assert runs[0]["seed"] == 1
    s.close()


def test_telemetry_runs_are_isolated_by_run_id():
    s = _store()
    sim = GridSimulator()
    st = None
    while st is None:
        st = sim.step()
    s.record_telemetry(st, run_id="A")
    s.record_telemetry(st, run_id="B")
    assert len(s.telemetry_history("A")) == 1
    assert len(s.telemetry_history("B")) == 1
    s.close()
