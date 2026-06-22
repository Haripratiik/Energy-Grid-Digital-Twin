"""Control policies evaluated by the harness.

Every controller implements one method, :meth:`decide`, mapping the current grid
state to a list of :class:`ProposedAction`. The harness applies them through the
production :class:`~decisions.action_executor.ActionExecutor`, so a controller's
actions take exactly the same code path as the live autonomous engine.

Three reference policies, in increasing sophistication:

* :class:`DoNothingController` — the baseline floor (passive dynamics only).
* :class:`GreedyRuleController` — deterministic power-balance heuristics: ramp
  spare generation to clear a deficit, shed load to clear an overload. The bar
  the LLM must beat to justify its cost.
* :class:`LLMController` — wraps the GPT-4o reasoning engine.
"""

from __future__ import annotations

import random
from collections import deque
from typing import TYPE_CHECKING, Optional, Protocol

from decisions.models import ProposedAction
from physics.network import LINES, NOMINAL_FREQ_HZ, SLACK_BUS, TRANSFORMERS

THERMAL_LIMIT_PCT = 100.0

if TYPE_CHECKING:
    from physics.swing import GridState
    from reasoning.engine import ReasoningEngine


def _downstream_pocket(
    branch_from: int, branch_to: int,
    tripped_lines: set[int], tripped_trafos: set[int],
) -> set[int]:
    """Buses reachable from ``branch_to`` once the (from,to) branch is removed.

    If the slack bus is *not* in the result, the branch radially feeds an
    isolated load pocket — shedding there directly relieves it. If the slack is
    reachable, the network is meshed and we fall back to a local neighbourhood.
    """
    adj: dict[int, list[int]] = {}
    for i, ln in enumerate(LINES):
        if i in tripped_lines:
            continue
        if {ln.from_bus, ln.to_bus} == {branch_from, branch_to}:
            continue
        adj.setdefault(ln.from_bus, []).append(ln.to_bus)
        adj.setdefault(ln.to_bus, []).append(ln.from_bus)
    for i, xf in enumerate(TRANSFORMERS):
        if i in tripped_trafos:
            continue
        if {xf.from_bus, xf.to_bus} == {branch_from, branch_to}:
            continue
        adj.setdefault(xf.from_bus, []).append(xf.to_bus)
        adj.setdefault(xf.to_bus, []).append(xf.from_bus)

    seen = {branch_to}
    q = deque([branch_to])
    while q:
        n = q.popleft()
        for m in adj.get(n, ()):
            if m not in seen:
                seen.add(m)
                q.append(m)
    return seen


def _adjacency(tripped_lines: set[int], tripped_trafos: set[int],
               exclude: Optional[tuple[int, int]] = None) -> dict[int, list[int]]:
    adj: dict[int, list[int]] = {}
    ex = set(exclude) if exclude else None
    for i, ln in enumerate(LINES):
        if i in tripped_lines or (ex and {ln.from_bus, ln.to_bus} == ex):
            continue
        adj.setdefault(ln.from_bus, []).append(ln.to_bus)
        adj.setdefault(ln.to_bus, []).append(ln.from_bus)
    for i, xf in enumerate(TRANSFORMERS):
        if i in tripped_trafos or (ex and {xf.from_bus, xf.to_bus} == ex):
            continue
        adj.setdefault(xf.from_bus, []).append(xf.to_bus)
        adj.setdefault(xf.to_bus, []).append(xf.from_bus)
    return adj


def _local_neighborhood(
    branch_from: int, branch_to: int, depth: int,
    tripped_lines: set[int], tripped_trafos: set[int],
) -> set[int]:
    """Buses within ``depth`` hops of either endpoint of the overloaded branch.

    Used for *meshed* overloads (no radial pocket): shedding electrically close
    to the constrained branch relieves its flow most per MW — a graph-distance
    approximation of line-outage sensitivity factors.
    """
    adj = _adjacency(tripped_lines, tripped_trafos, exclude=(branch_from, branch_to))
    seen = {branch_from, branch_to}
    frontier = {branch_from, branch_to}
    for _ in range(depth):
        nxt: set[int] = set()
        for n in frontier:
            for m in adj.get(n, ()):
                if m not in seen:
                    seen.add(m)
                    nxt.add(m)
        frontier = nxt
    return seen


class Controller(Protocol):
    name: str

    def decide(self, state: "GridState") -> list[ProposedAction]:
        ...


# ---------------------------------------------------------------------------

class DoNothingController:
    """Takes no action — establishes the passive-dynamics baseline."""

    name = "do_nothing"

    def decide(self, state: "GridState") -> list[ProposedAction]:
        return []


# ---------------------------------------------------------------------------

class GreedyRuleController:
    """Deterministic rule-based policy.

    Priorities each decision cycle:
      1. If the grid is under-generating (load > generation beyond a deadband),
         ramp up online generators with spare headroom to close the deficit —
         largest headroom first, mirroring the "add generation before shedding
         load" operating doctrine.
      2. If a branch is thermally overloaded, shed load at the largest load bus
         to relieve it (last resort).
    """

    name = "greedy_rule"

    def __init__(self, deadband_mw: float = 8.0, shed_chunk_mw: float = 25.0) -> None:
        self.deadband_mw = deadband_mw
        self.shed_chunk_mw = shed_chunk_mw

    def decide(self, state: "GridState") -> list[ProposedAction]:
        actions: list[ProposedAction] = []

        deficit = state.total_load_mw - state.total_generation_mw
        freq_low = state.system_frequency_hz < NOMINAL_FREQ_HZ - 0.05

        if deficit > self.deadband_mw or freq_low:
            actions += self._ramp_generation(state, max(deficit, 0.0))

        # Relieve the worst thermal/voltage overload by shedding in its pocket.
        worst = self._worst_overload(state)
        if worst is not None:
            actions += self._shed_in_pocket(state, worst)

        return actions

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _headroom(g) -> float:
        return max(0.0, g.capacity_mw - g.electrical_power_mw)

    def _ramp_generation(self, state: "GridState", deficit_mw: float) -> list[ProposedAction]:
        candidates = sorted(
            (g for g in state.generators if g.online and self._headroom(g) > 1.0),
            key=self._headroom, reverse=True,
        )
        actions: list[ProposedAction] = []
        # Cover the deficit plus a small margin; spread across up to 3 units.
        remaining = max(deficit_mw, self.deadband_mw) * 1.05
        for g in candidates[:3]:
            if remaining <= 0:
                break
            delta = min(self._headroom(g), remaining)
            if delta < 1.0:
                continue
            remaining -= delta
            actions.append(ProposedAction(
                action_type="GEN_SETPOINT",
                target_rid=f"ri.city-grid.main.generator.{g.bus_id}",
                parameters={"delta_mw": round(delta, 1)},
                rationale=f"Ramp {g.gen_type} at Bus {g.bus_id} +{delta:.0f} MW to close deficit",
                confidence=0.9,
                estimated_impact_mw=round(delta, 1),
                reversible=True,
            ))
        return actions

    @staticmethod
    def _worst_overload(state: "GridState") -> Optional[tuple[int, int, float]]:
        """Most-overloaded in-service branch as (from_bus, to_bus, loading_pct)."""
        best: Optional[tuple[int, int, float]] = None
        for i, ln in enumerate(state.lines):
            if ln.tripped:
                continue
            pct = ln.flow_pct_of_limit * 100.0
            if pct > THERMAL_LIMIT_PCT and (best is None or pct > best[2]):
                best = (LINES[i].from_bus, LINES[i].to_bus, pct)
        for xf in state.transformers:
            if xf.status == "tripped":
                continue
            if xf.loading_pct > THERMAL_LIMIT_PCT and (best is None or xf.loading_pct > best[2]):
                best = (xf.from_bus, xf.to_bus, xf.loading_pct)
        return best

    def _shed_in_pocket(
        self, state: "GridState", worst: tuple[int, int, float],
    ) -> list[ProposedAction]:
        """Shed load in the electrical pocket fed by the overloaded branch."""
        from_bus, to_bus, pct = worst
        tripped_lines = {i for i, ln in enumerate(state.lines) if ln.tripped}
        tripped_trafos = {i for i, xf in enumerate(state.transformers)
                          if xf.status == "tripped"}
        pocket = _downstream_pocket(from_bus, to_bus, tripped_lines, tripped_trafos)
        if SLACK_BUS in pocket:
            other = _downstream_pocket(to_bus, from_bus, tripped_lines, tripped_trafos)
            if SLACK_BUS not in other:
                # The other side is the genuinely-radial pocket.
                pocket = other
            else:
                # Fully meshed: shed in a tight neighbourhood of the branch.
                pocket = _local_neighborhood(from_bus, to_bus, 2,
                                             tripped_lines, tripped_trafos)

        load_buses = sorted(
            (b for b in state.buses if b.power_load_mw > 0 and b.id in pocket),
            key=lambda b: b.power_load_mw, reverse=True,
        )
        if not load_buses:
            return []

        # Size the shed to the overload: roughly the excess fraction of the
        # pocket's load, capped per cycle so we converge rather than overshoot.
        target = load_buses[0]
        excess_frac = min((pct - THERMAL_LIMIT_PCT) / 100.0, 1.0)
        shed = min(self.shed_chunk_mw, target.power_load_mw,
                   max(5.0, excess_frac * target.power_load_mw))
        return [ProposedAction(
            action_type="LOAD_SHED",
            target_rid=f"ri.city-grid.main.load-bus.{target.id}",
            parameters={"delta_mw": -round(shed, 1)},
            rationale=f"Shed {shed:.0f} MW at Bus {target.id} (pocket of "
                      f"{from_bus}-{to_bus} at {pct:.0f}%)",
            confidence=0.8,
            estimated_impact_mw=-round(shed, 1),
            reversible=True,
        )]


# ---------------------------------------------------------------------------

class ExploratoryController:
    """Randomised exploration policy for **dataset generation** (not comparison).

    Reactive controllers (do-nothing, greedy) almost never act in nominal
    conditions, so a dataset built from them is ~99% no-op — an action-conditioned
    world model has nothing to learn the *effect of interventions* from. This
    controller deliberately perturbs the grid every decision cycle with a random
    valid action (a generator setpoint nudge or a load shed of random magnitude
    and location), so the recorded trajectories densely cover
    ``(state, action) → next-state`` transitions across the action space.

    It owns a private RNG seeded at construction, so it is reproducible *and*
    does not perturb the global RNG stream the physics stochasticity uses — two
    runs with the same scenario seed see identical wind/solar regardless of the
    controller's draws.
    """

    name = "exploratory"

    def __init__(self, *, epsilon: float = 1.0, seed: int = 0,
                 max_gen_delta_mw: float = 60.0, max_shed_mw: float = 40.0) -> None:
        self.epsilon = epsilon
        self.max_gen_delta_mw = max_gen_delta_mw
        self.max_shed_mw = max_shed_mw
        self._rng = random.Random(seed)

    def decide(self, state: "GridState") -> list[ProposedAction]:
        if self._rng.random() > self.epsilon:
            return []
        # Bias toward generator setpoints (the continuous control), with load
        # shedding mixed in for coverage of the demand side.
        if self._rng.random() < 0.6:
            online = [g for g in state.generators if g.online]
            if not online:
                return []
            g = self._rng.choice(online)
            delta = self._rng.uniform(-self.max_gen_delta_mw, self.max_gen_delta_mw)
            return [ProposedAction(
                action_type="GEN_SETPOINT",
                target_rid=f"ri.city-grid.main.generator.{g.bus_id}",
                parameters={"delta_mw": round(delta, 1)},
                rationale="exploratory setpoint perturbation (dataset generation)",
                confidence=0.5, estimated_impact_mw=round(delta, 1), reversible=True,
            )]
        load_buses = [b for b in state.buses if b.power_load_mw > 5.0]
        if not load_buses:
            return []
        b = self._rng.choice(load_buses)
        shed = self._rng.uniform(5.0, min(self.max_shed_mw, b.power_load_mw))
        return [ProposedAction(
            action_type="LOAD_SHED",
            target_rid=f"ri.city-grid.main.load-bus.{b.id}",
            parameters={"delta_mw": -round(shed, 1)},
            rationale="exploratory load shed (dataset generation)",
            confidence=0.5, estimated_impact_mw=-round(shed, 1), reversible=True,
        )]


# ---------------------------------------------------------------------------

class LLMController:
    """Wraps the GPT-4o reasoning engine as a control policy.

    Non-deterministic and network-dependent; falls back to cached demo actions
    when no API key is configured. Excluded from determinism tests.
    """

    name = "llm"

    def __init__(self, engine: "ReasoningEngine") -> None:
        self._engine = engine

    def decide(self, state: "GridState") -> list[ProposedAction]:
        result = self._engine.analyze(state, None, "MANUAL", None)
        actions: list[ProposedAction] = []
        for a in result.proposed_actions:
            data = {k: v for k, v in a.items() if k != "risk_level"}
            try:
                actions.append(ProposedAction(**data))
            except Exception:
                continue
        return actions
