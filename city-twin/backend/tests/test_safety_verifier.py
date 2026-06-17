"""Tests for the physics safety verifier and its gating of the autonomous engine."""

from __future__ import annotations

import random

import pytest

from decisions.autonomous_engine import AutonomousEngine
from decisions.models import GridDecision, ProposedAction, RiskLevel
from decisions.safety_verifier import SafetyVerifier
from physics.swing import GridSimulator
from reasoning.engine import ReasoningEngine


def _action(action_type, target, params=None, impact=20.0, reversible=True) -> ProposedAction:
    return ProposedAction(
        action_type=action_type, target_rid=target, parameters=params or {},
        rationale="test", confidence=1.0, estimated_impact_mw=impact, reversible=reversible,
    )


@pytest.fixture(scope="module")
def settled_state():
    random.seed(0)
    sim = GridSimulator()
    for _ in range(25):
        sim.step()
    return sim.get_state()


def test_benign_gen_setpoint_is_safe(settled_state):
    v = SafetyVerifier()
    r = v.verify(settled_state, _action("GEN_SETPOINT", "ri.city-grid.main.generator.8",
                                        {"delta_mw": 20.0}))
    assert r.safe
    assert r.converged
    assert r.post_violations == 0


def test_tripping_weak_line_is_unsafe(settled_state):
    """Opening line 26 overloads the network at nominal — the verifier must reject it."""
    v = SafetyVerifier()
    r = v.verify(settled_state, _action("LINE_SWITCH", "ri.city-grid.main.transmission-line.26",
                                        {"switch_open": True}, impact=50.0, reversible=False))
    assert not r.safe
    assert r.post_severity > r.pre_severity


def test_tripping_distribution_transformer_is_unsafe(settled_state):
    v = SafetyVerifier()
    r = v.verify(settled_state, _action("TRANSFORMER_TAP", "ri.city-grid.main.transformer.17"))
    assert not r.safe


def test_verifier_result_has_diagnostics(settled_state):
    v = SafetyVerifier()
    r = v.verify(settled_state, _action("GEN_SETPOINT", "ri.city-grid.main.generator.8",
                                        {"delta_mw": 10.0}))
    assert r.worst_voltage_pu is not None
    assert r.worst_loading_pct is not None
    assert "secure" in r.reason.lower()


# --- engine gating --------------------------------------------------------

def _engine() -> AutonomousEngine:
    sim = GridSimulator()
    for _ in range(20):
        sim.step()
    return AutonomousEngine(sim, ReasoningEngine("", demo_mode=True), verify_actions=True)


def test_engine_executes_verified_safe_advisory():
    eng = _engine()
    d = GridDecision(risk_level=RiskLevel.ADVISORY,
                     action=_action("GEN_SETPOINT", "ri.city-grid.main.generator.8",
                                    {"delta_mw": 8.0}, impact=8.0))
    eng._apply_mode_policy(d)            # ADVISORY in SEMI → auto-executes (after verify)
    assert d.status == "EXECUTED"
    assert d.verification is not None and d.verification["safe"]


def test_engine_blocks_unsafe_action_on_approval():
    eng = _engine()
    d = GridDecision(
        risk_level=RiskLevel.CRITICAL,
        action=_action("LINE_SWITCH", "ri.city-grid.main.transmission-line.26",
                       {"switch_open": True}, impact=50.0, reversible=False),
    )
    eng.decision_log.record(d)
    ok = eng.approve(d.id)
    assert ok is False                   # physics overruled the approval
    assert d.status == "REJECTED"
    assert d.verification is not None and not d.verification["safe"]
