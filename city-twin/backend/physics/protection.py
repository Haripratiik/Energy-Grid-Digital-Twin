"""Overload protection with inverse-time tripping — the engine of cascades.

Real grids don't sit at 150% loading: protective relays trip overloaded
elements, and *that* trip can overload neighbours, which trip in turn — a
cascading failure. This module models that mechanism so cascades emerge from
the physics instead of being scripted.

Characteristic
--------------
Each branch carries an inverse-time overcurrent relay: the further past its
limit it runs, the faster it trips. We accumulate a per-element "trip credit"
of ``dt / t_trip(loading)`` each cycle and trip when it reaches 1.0; the credit
decays when loading falls back under pickup (relay reset). The trip-time curve

    t_trip = base_time / (loading_ratio - 1)        for loading_ratio > pickup

resembles an IEC very-inverse characteristic: e.g. with ``base_time = 4 s`` a
branch at 110% trips in ~40 s, at 150% in ~8 s, at 200% in ~4 s, at 300% in 2 s.
A transient overload that clears quickly never trips.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class ProtectionEvent:
    sim_time_s: float
    kind: str          # "line" | "transformer"
    index: int
    loading_pct: float


@dataclass
class ProtectionSystem:
    pickup_ratio: float = 1.05     # trip only genuine overloads (>105% of limit)
    base_time_s: float = 4.0       # time-dial: trip time at 200% loading
    reset_rate: float = 0.5        # credit decay per second when below pickup

    _credit_line: dict[int, float] = field(default_factory=dict)
    _credit_trafo: dict[int, float] = field(default_factory=dict)
    events: list[ProtectionEvent] = field(default_factory=list)

    def trip_time_s(self, loading_pct: float) -> float:
        ratio = loading_pct / 100.0
        if ratio <= self.pickup_ratio:
            return math.inf
        return self.base_time_s / (ratio - 1.0)

    def reset(self) -> None:
        self._credit_line.clear()
        self._credit_trafo.clear()
        self.events.clear()

    def update(
        self,
        line_loading_pct,
        trafo_loading_pct,
        dt_s: float,
        tripped_lines: set[int],
        tripped_trafos: set[int],
        sim_time_s: float = 0.0,
    ) -> tuple[set[int], set[int]]:
        """Advance every relay by ``dt_s`` and return newly-tripped indices."""
        new_lines = self._step_group(
            line_loading_pct, dt_s, tripped_lines, self._credit_line,
            "line", sim_time_s,
        )
        new_trafos = self._step_group(
            trafo_loading_pct, dt_s, tripped_trafos, self._credit_trafo,
            "transformer", sim_time_s,
        )
        return new_lines, new_trafos

    def _step_group(
        self, loadings, dt_s, tripped, credit, kind, sim_time_s,
    ) -> set[int]:
        newly: set[int] = set()
        for i, pct in enumerate(loadings):
            if i in tripped:
                credit.pop(i, None)
                continue
            c = credit.get(i, 0.0)
            tt = self.trip_time_s(float(pct))
            if math.isinf(tt):
                c = max(0.0, c - self.reset_rate * dt_s)
            else:
                c += dt_s / tt
            if c >= 1.0:
                newly.add(i)
                self.events.append(ProtectionEvent(
                    sim_time_s=round(sim_time_s, 2), kind=kind, index=i,
                    loading_pct=round(float(pct), 1),
                ))
                credit.pop(i, None)
            elif c <= 0.0:
                credit.pop(i, None)       # fully reset — no lingering state
            else:
                credit[i] = c
        return newly
