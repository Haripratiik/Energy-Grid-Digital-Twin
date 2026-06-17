"""Reproducible fault scenarios.

A :class:`Scenario` is a fully-specified, seeded experiment: a fixed disturbance
schedule applied to the grid over a fixed horizon. Given the same seed, the
stochastic generation (wind/solar) and the disturbance timing are identical, so
two controllers can be compared on *exactly* the same physical situation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from physics.fault_handler import FaultType


class ScenarioEvent(BaseModel):
    """A single disturbance applied at a scheduled simulation time."""

    at_s: float                       # sim-time (seconds) to apply the fault
    fault_type: FaultType
    target_rid: str = ""
    magnitude_mw: float = 0.0
    note: str = ""


class Scenario(BaseModel):
    """A seeded, time-boxed disturbance experiment."""

    id: str
    family: str                       # "gen_dropout" | "line_trip" | ...
    description: str = ""
    seed: int = 42
    settle_s: float = 3.0             # quiet warm-up before the first event
    duration_s: float = 30.0          # total horizon AFTER settle
    decision_interval_s: float = 2.0  # how often the controller is consulted
    events: list[ScenarioEvent] = Field(default_factory=list)

    @property
    def total_s(self) -> float:
        return self.settle_s + self.duration_s


# RID helpers (match physics.fault_handler parsing) -------------------------

def _line(i: int) -> str:
    return f"ri.city-grid.main.transmission-line.{i}"


def _trafo(i: int) -> str:
    return f"ri.city-grid.main.transformer.{i}"


def _gen(bus: int) -> str:
    return f"ri.city-grid.main.generator.{bus}"


def _load(bus: int) -> str:
    return f"ri.city-grid.main.load-bus.{bus}"


# ---------------------------------------------------------------------------
# Canonical scenario library — one per fault family from the research plan.
# ---------------------------------------------------------------------------

def scenario_library() -> dict[str, Scenario]:
    """Return the canonical set of named scenarios, keyed by id."""
    scenarios = [
        Scenario(
            id="gen_dropout_gas3",
            family="gen_dropout",
            description="Largest gas peaker (Bus 3, 280 MW) trips at t=3s.",
            seed=42,
            events=[ScenarioEvent(
                at_s=3.0, fault_type=FaultType.GEN_DROPOUT, target_rid=_gen(3),
                note="Gas CCGT trip — frequency deficit",
            )],
        ),
        Scenario(
            id="line_trip_central",
            family="line_trip",
            description="Heavily-loaded 132kV line 26 (Bus 24-25) trips at t=3s.",
            seed=7,
            events=[ScenarioEvent(
                at_s=3.0, fault_type=FaultType.LINE_TRIP, target_rid=_line(26),
                note="N-1 of a known weak line",
            )],
        ),
        Scenario(
            id="load_spike_industrial",
            family="load_spike",
            description="+100 MW load spike at Bus 6 (industrial north) at t=3s.",
            seed=13,
            events=[ScenarioEvent(
                at_s=3.0, fault_type=FaultType.LOAD_SPIKE, target_rid=_load(6),
                magnitude_mw=100.0, note="Sudden industrial demand surge",
            )],
        ),
        Scenario(
            id="trafo_trip_radial",
            family="trafo_trip",
            description="Distribution transformer 17 (Bus 24->64) trips at t=3s.",
            seed=21,
            events=[ScenarioEvent(
                at_s=3.0, fault_type=FaultType.TRAFO_TRIP, target_rid=_trafo(17),
                note="Worst single-element by N-1 severity",
            )],
        ),
        Scenario(
            id="compound_gen_then_line",
            family="compound",
            description="Gas peaker trips at t=3s, then line 26 trips at t=9s.",
            seed=99,
            duration_s=36.0,
            events=[
                ScenarioEvent(
                    at_s=3.0, fault_type=FaultType.GEN_DROPOUT, target_rid=_gen(3),
                    note="First contingency",
                ),
                ScenarioEvent(
                    at_s=9.0, fault_type=FaultType.LINE_TRIP, target_rid=_line(26),
                    note="Second contingency on a stressed grid",
                ),
            ],
        ),
        Scenario(
            id="renewable_volatility_load",
            family="renewable_volatility",
            description="High renewable variance (seed) plus a +80 MW spike at Bus 19.",
            seed=2024,
            events=[ScenarioEvent(
                at_s=5.0, fault_type=FaultType.LOAD_SPIKE, target_rid=_load(19),
                magnitude_mw=80.0, note="Demand surge under volatile renewables",
            )],
        ),
    ]
    return {s.id: s for s in scenarios}
