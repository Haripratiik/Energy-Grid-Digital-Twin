"""Tests for the physics safety verifier and its gating of the autonomous engine."""

from __future__ import annotations

import asyncio
import random
from types import SimpleNamespace

import numpy as np
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


def test_unmodellable_action_fails_closed(settled_state):
    """An action the verifier can't model (here: a malformed target RID) must be
    rejected, not silently certified safe by a no-op apply."""
    v = SafetyVerifier()
    r = v.verify(settled_state, _action("GEN_SETPOINT",
                                        "ri.city-grid.main.generator.NOT_A_NUMBER",
                                        {"target_mw": 100.0}))
    assert r.safe is False
    assert "fail-closed" in r.reason.lower()


def test_unknown_action_type_fails_closed(settled_state):
    """A duck-typed action with an unrecognised type is rejected (fail-closed)."""
    from types import SimpleNamespace
    v = SafetyVerifier()
    bogus = SimpleNamespace(action_type="FROBNICATE",
                            target_rid="ri.city-grid.main.generator.8",
                            parameters={}, estimated_impact_mw=0.0)
    r = v.verify(settled_state, bogus)
    assert r.safe is False


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


# --- N-1 second gate + physics-feedback self-correction -------------------

def test_n1_gate_reports_fields_when_checked(settled_state):
    """With check_n1=True the verifier reports the N-1 dimension."""
    v = SafetyVerifier()
    r = v.verify(settled_state, _action("GEN_SETPOINT", "ri.city-grid.main.generator.8",
                                        {"delta_mw": 10.0}), check_n1=True)
    assert r.n1_checked is True
    assert r.n1_post_insecure >= 0
    assert "N-1" in r.reason


def test_self_correction_replaces_vetoed_action():
    """Veto → physics-feedback re-proposal → verified-safe alternative, with a
    recorded self-correction trace. This is the closed LLM↔physics loop."""
    eng = _engine()
    state = eng._sim.get_state()
    bad = _action("LINE_SWITCH", "ri.city-grid.main.transmission-line.26",
                  {"switch_open": True}, impact=50.0, reversible=False)
    final_action, verdict, trace = eng._resolve_one(state, bad, "AUTO_CRITICAL", "alert-x")
    assert verdict is not None and verdict.safe          # ended on a safe action
    assert final_action.action_type != "LINE_SWITCH"     # the action actually changed
    assert len(trace) >= 2                                # rejected → corrected arc
    assert trace[0]["safe"] is False                     # first proposal vetoed
    assert trace[-1]["safe"] is True                     # final proposal verified


def test_self_correction_no_phantom_trace_when_no_alternative():
    """If the model offers no alternative, the result is a plain rejection — NOT a
    fabricated 2-attempt 'self-correction' with a duplicated entry."""
    class _NoAlt:
        def repropose(self, *a, **k):
            return []

    eng = _engine()
    eng._reasoning = _NoAlt()
    state = eng._sim.get_state()
    bad = _action("LINE_SWITCH", "ri.city-grid.main.transmission-line.26",
                  {"switch_open": True}, impact=50.0, reversible=False)
    _, verdict, trace = eng._resolve_one(state, bad, "AUTO_CRITICAL", "alert-x")
    assert not verdict.safe          # still rejected
    assert trace == []               # no phantom retry rendered


def test_demo_corrected_action_is_a_real_remedy():
    """The keyless demo's 'corrected' action must be a genuine remedy the verifier
    can model — never a setpoint on the slack bus, whose MW the power flow ignores
    (a physical no-op the verifier would rubber-stamp as 'safe')."""
    from physics.network import SLACK_BUS
    from reasoning.cached_responses import DEMO_CORRECTED_ACTION

    act = ProposedAction(**DEMO_CORRECTED_ACTION)
    if act.action_type == "GEN_SETPOINT":
        assert int(act.target_rid.rsplit(".", 1)[-1]) != SLACK_BUS
    # The verifier must be able to MODEL it AND verify it secure (not just a
    # modellable no-op).
    v = SafetyVerifier()
    sim = GridSimulator()
    for _ in range(20):
        sim.step()
    state = sim.get_state()
    gen_p, load_p, tl, tt = v._operating_point(state)
    applied, *_ = v._apply_action(act, gen_p, load_p, tl, tt)
    assert applied
    assert v.verify(state, act).safe


def test_demo_risky_action_is_vetoed_then_corrected():
    """The on-camera demo's *risky* proposal must genuinely be rejected, and the
    pipeline must self-correct to a verified-safe action — the showpiece invariant."""
    from reasoning.cached_responses import DEMO_RISKY_ACTION

    eng = _engine()
    state = eng._sim.get_state()
    _, verdict, trace = eng._resolve_one(
        state, ProposedAction(**DEMO_RISKY_ACTION), "AUTO_CRITICAL", "demo")
    assert len(trace) >= 2 and trace[0]["safe"] is False   # risky proposal vetoed
    assert verdict.safe                                     # corrected to a safe action


def test_score_fails_closed_on_nan_solution():
    """A converged-but-NaN power flow (islanded bus) must score as a collapse, not
    silently as 0 severity / 0 violations — the safety-critical guard."""
    v = SafetyVerifier()
    v._pf.solve = lambda **k: SimpleNamespace(   # type: ignore[method-assign]
        converged=True,
        bus_vm_pu=np.array([1.0, np.nan, 0.98]),
        line_loading_pct=np.array([40.0]),
        trafo_loading_pct=np.array([]),
    )
    ok, sev, n_viol, *_ = v._score({1: 100.0}, {2: 50.0}, set(), set())
    assert ok is False
    assert sev >= 1e6


def test_load_shed_on_zero_load_bus_fails_closed(settled_state):
    """LOAD_SHED on a bus with no load must fail closed — the verifier would model
    a no-op, but the executor injects negative load there."""
    v = SafetyVerifier()
    zero_bus = next(b.id for b in settled_state.buses if b.power_load_mw == 0)
    r = v.verify(settled_state,
                 _action("LOAD_SHED", f"ri.city-grid.main.load-bus.{zero_bus}", {"delta_mw": -20.0}))
    assert r.safe is False
    assert "fail-closed" in r.reason.lower() or "could not be modelled" in r.reason.lower()


def test_on_alert_records_verified_decisions():
    """End-to-end production entry point: an alert produces recorded decisions, each
    carrying a physics verdict."""
    eng = _engine()
    state = eng._sim.get_state()
    asyncio.run(eng.on_alert("THERMAL_OVERLOAD", "CRITICAL", state, "alert-e2e"))
    decisions = eng.decision_log.get_all(50)
    assert len(decisions) > 0
    assert all(d.verification is not None for d in decisions)
