"""Smoke tests for the verifier catch-rate eval harness (research/verifier_eval.py).

Keeps the action set tiny so the exhaustive N-1 oracle stays fast; the full
battery is run offline via ``python -m research.verifier_eval``.
"""

from __future__ import annotations

import random

from decisions.models import ProposedAction
from decisions.safety_verifier import SafetyVerifier
from physics.contingency import ContingencyAnalyzer
from physics.swing import GridSimulator
from research.verifier_eval import EvalReport, oracle_unsafe


def _settled():
    random.seed(0)
    sim = GridSimulator()
    for _ in range(25):
        sim.step()
    return sim.get_state()


def _a(t, rid, params):
    return ProposedAction(action_type=t, target_rid=rid, parameters=params,
                          rationale="t", confidence=1.0, estimated_impact_mw=0.0, reversible=True)


def test_oracle_labels_safe_unsafe_and_unmodellable():
    state = _settled()
    v = SafetyVerifier()
    n1 = ContingencyAnalyzer(ac_verify_k=999)
    # benign gen ramp → safe
    assert oracle_unsafe(
        v, n1, state, _a("GEN_SETPOINT", "ri.city-grid.main.generator.8", {"delta_mw": 10.0})) is False
    # tripping a weak line overloads the network → unsafe
    assert oracle_unsafe(
        v, n1, state, _a("LINE_SWITCH", "ri.city-grid.main.transmission-line.26", {"switch_open": True})) is True
    # unmodellable action (malformed RID) → unsafe-to-certify
    assert oracle_unsafe(
        v, n1, state, _a("GEN_SETPOINT", "ri.city-grid.main.generator.BAD", {})) is True


def test_eval_report_metrics():
    r = EvalReport(n=10, tp=4, fn=1, tn=4, fp=1)
    assert r.n_unsafe == 5 and r.n_safe == 5
    assert r.catch_rate == 0.8        # 4 of 5 unsafe caught
    assert r.false_accept == 0.2      # 1 of 5 unsafe missed
    assert r.false_reject == 0.2      # 1 of 5 safe blocked
