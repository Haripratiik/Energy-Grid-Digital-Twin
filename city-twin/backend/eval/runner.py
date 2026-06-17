"""Deterministic headless rollout driver.

Drives a fresh :class:`GridSimulator` through a :class:`Scenario` under a single
:class:`Controller`, applies the controller's actions through the production
``ActionExecutor``, summarises every emitted state, and reduces the run to
:class:`RolloutMetrics`. Given a scenario seed, the run is fully reproducible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from decisions.models import GridDecision, ProposedAction
from decisions.action_executor import ActionExecutor
from decisions.risk_classifier import RiskClassifier
from physics.fault_handler import FaultHandler, FaultRequest
from physics.swing import GridSimulator, GridState

from .controllers import Controller
from .metrics import RolloutMetrics, StepSummary, compute_metrics
from .scenario import Scenario
from .trajectory import TrajectoryRecorder

_EMIT_DT_S = GridSimulator.RK4_DT * GridSimulator.EMIT_EVERY  # 0.1 s


@dataclass
class RolloutResult:
    metrics: RolloutMetrics
    steps: list[StepSummary]
    action_log: list[dict] = field(default_factory=list)
    trajectory: Optional[TrajectoryRecorder] = None


def _summarize(state: GridState, shed_cumulative: float) -> StepSummary:
    max_line = 0.0
    for ln in state.lines:
        if not ln.tripped:
            max_line = max(max_line, ln.flow_pct_of_limit * 100.0)
    max_trafo = max((xf.loading_pct for xf in state.transformers
                     if xf.status != "tripped"), default=0.0)
    max_vdev = max((abs(b.voltage_magnitude_pu - 1.0) for b in state.buses), default=0.0)

    n_viol = (
        sum(1 for ln in state.lines if ln.flow_pct_of_limit > 1.0 and not ln.tripped)
        + sum(1 for xf in state.transformers
              if xf.loading_pct > 100.0 and xf.status != "tripped")
        + sum(1 for b in state.buses if abs(b.voltage_magnitude_pu - 1.0) > 0.10)
    )
    return StepSummary(
        sim_time_s=state.sim_time_s,
        frequency_hz=state.system_frequency_hz,
        total_generation_mw=state.total_generation_mw,
        total_load_mw=state.total_load_mw,
        max_line_loading_pct=round(max(max_line, max_trafo), 2),
        max_voltage_dev_pu=round(max_vdev, 4),
        n_violations=n_viol,
        shed_mw_cumulative=round(shed_cumulative, 2),
        secure=(n_viol == 0),
    )


def run_scenario(
    scenario: Scenario,
    controller: Controller,
    *,
    record_trajectory: bool = False,
    protection_enabled: bool = False,
) -> RolloutResult:
    """Run one (scenario, controller) rollout deterministically.

    With ``protection_enabled``, overloaded branches auto-trip on an inverse-time
    characteristic, so an unaddressed overload can cascade — the regime where a
    proactive controller's value is largest.
    """
    random.seed(scenario.seed)

    sim = GridSimulator(protection_enabled=protection_enabled)
    fault_handler = FaultHandler(sim)
    executor = ActionExecutor(sim)

    pending_events = sorted(scenario.events, key=lambda e: e.at_s)
    event_idx = 0
    fault_start_s = pending_events[0].at_s if pending_events else scenario.settle_s

    recorder = (
        TrajectoryRecorder(scenario.id, controller.name, scenario.seed)
        if record_trajectory else None
    )

    steps: list[StepSummary] = []
    action_log: list[dict] = []
    shed_cumulative = 0.0
    n_actions = 0
    last_decision_t = -1e9

    while sim.sim_time < scenario.total_s:
        # Apply any scheduled faults whose time has arrived.
        while event_idx < len(pending_events) and sim.sim_time >= pending_events[event_idx].at_s:
            ev = pending_events[event_idx]
            fault_handler.apply(FaultRequest(
                type=ev.fault_type, target_rid=ev.target_rid, magnitude_mw=ev.magnitude_mw,
            ))
            event_idx += 1

        state = sim.step()
        if state is None:
            continue

        # Consult the controller on its decision cadence (after settle).
        actions_this_step: list[ProposedAction] = []
        if (state.sim_time_s >= scenario.settle_s
                and state.sim_time_s - last_decision_t >= scenario.decision_interval_s):
            last_decision_t = state.sim_time_s
            proposed = controller.decide(state)
            for pa in proposed:
                decision = GridDecision(risk_level=RiskClassifier.classify(pa), action=pa)
                if executor.execute(decision):
                    n_actions += 1
                    actions_this_step.append(pa)
                    if pa.action_type == "LOAD_SHED":
                        shed_cumulative += abs(pa.parameters.get("delta_mw", 0.0))
            if actions_this_step:
                action_log.append({
                    "sim_time_s": round(state.sim_time_s, 2),
                    "actions": [a.model_dump() for a in actions_this_step],
                })

        steps.append(_summarize(state, shed_cumulative))
        if recorder is not None:
            recorder.record(state, actions_this_step)

    metrics = compute_metrics(
        controller.name, scenario.id, steps, _EMIT_DT_S, n_actions, fault_start_s,
    )
    return RolloutResult(metrics=metrics, steps=steps,
                         action_log=action_log, trajectory=recorder)
