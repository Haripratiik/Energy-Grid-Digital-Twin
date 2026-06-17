"""Tests for risk classification, action execution, and mode policy."""

from __future__ import annotations

from decisions.action_executor import ActionExecutor
from decisions.autonomous_engine import AutonomousEngine
from decisions.models import AutonomousMode, GridDecision, ProposedAction, RiskLevel
from decisions.risk_classifier import RiskClassifier
from physics.swing import GridSimulator
from reasoning.engine import ReasoningEngine


def _action(action_type="GEN_SETPOINT", impact=20.0, reversible=True,
            confidence=0.9, target="ri.city-grid.main.generator.8",
            params=None) -> ProposedAction:
    return ProposedAction(
        action_type=action_type, target_rid=target,
        parameters=params or {"delta_mw": impact},
        rationale="test", confidence=confidence,
        estimated_impact_mw=impact, reversible=reversible,
    )


def test_risk_classification_boundaries():
    c = RiskClassifier.classify
    assert c(_action(impact=5.0)) == RiskLevel.ADVISORY
    assert c(_action(impact=20.0)) == RiskLevel.CONTROLLED
    assert c(_action(impact=60.0)) == RiskLevel.CRITICAL          # >50
    assert c(_action(impact=150.0)) == RiskLevel.EMERGENCY         # >100
    assert c(_action(action_type="ISLANDING", impact=5.0)) == RiskLevel.EMERGENCY
    assert c(_action(impact=5.0, reversible=False)) == RiskLevel.CRITICAL
    assert c(_action(impact=5.0, confidence=0.4)) == RiskLevel.CRITICAL


def test_gen_setpoint_execution_changes_output():
    sim = GridSimulator()
    executor = ActionExecutor(sim)
    target_gen = next(g for g in sim.generators if g.bus_id == 8)
    before = target_gen.p_mech_mw

    decision = GridDecision(
        risk_level=RiskLevel.CONTROLLED,
        action=_action(action_type="GEN_SETPOINT", impact=30.0,
                       target="ri.city-grid.main.generator.8",
                       params={"delta_mw": 30.0}),
    )
    assert executor.execute(decision)
    assert decision.status == "EXECUTED"
    assert target_gen.p_mech_mw > before


def test_load_shed_execution_reduces_load():
    sim = GridSimulator()
    executor = ActionExecutor(sim)
    bus_id = 6
    before = sim._p_load[bus_id]

    decision = GridDecision(
        risk_level=RiskLevel.CONTROLLED,
        action=_action(action_type="LOAD_SHED", impact=-25.0,
                       target="ri.city-grid.main.load-bus.6",
                       params={"delta_mw": -25.0}),
    )
    assert executor.execute(decision)
    assert sim._p_load[bus_id] < before


def test_semi_mode_auto_executes_advisory():
    sim = GridSimulator()
    engine = AutonomousEngine(sim, ReasoningEngine("", demo_mode=True))
    engine.mode = AutonomousMode.SEMI

    decision = GridDecision(risk_level=RiskLevel.ADVISORY, action=_action(impact=5.0))
    engine._apply_mode_policy(decision)
    assert decision.status == "EXECUTED"


def test_semi_mode_holds_critical_for_approval():
    sim = GridSimulator()
    engine = AutonomousEngine(sim, ReasoningEngine("", demo_mode=True))
    engine.mode = AutonomousMode.SEMI

    decision = GridDecision(risk_level=RiskLevel.CRITICAL,
                            action=_action(impact=60.0))
    engine._apply_mode_policy(decision)
    assert decision.status == "PENDING"
    assert decision.expires_at is None  # critical needs explicit approval


def test_emergency_always_requires_approval_even_in_full_auto():
    sim = GridSimulator()
    engine = AutonomousEngine(sim, ReasoningEngine("", demo_mode=True))
    engine.mode = AutonomousMode.FULL_AUTO

    decision = GridDecision(risk_level=RiskLevel.EMERGENCY,
                            action=_action(action_type="ISLANDING", impact=5.0))
    engine._apply_mode_policy(decision)
    assert decision.status == "PENDING"
    assert decision.expires_at is None
