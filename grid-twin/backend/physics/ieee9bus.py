"""
IEEE 9-Bus Test System Constants
================================
Standard WSCC 3-machine, 9-bus test network used for transient stability
and power flow studies. All impedances are in per-unit on a 100 MVA base.

Reference: P.M. Anderson & A.A. Fouad, "Power System Control and Stability"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

BASE_MVA: Final[float] = 100.0
SLACK_BUS: Final[int] = 1
SYSTEM_FREQ_HZ: Final[float] = 60.0


@dataclass(frozen=True, slots=True)
class Bus:
    id: int
    name: str
    bus_type: str  # "slack" | "gen" | "load" | "junction"
    p_gen_mw: float = 0.0
    p_load_mw: float = 0.0
    v_setpoint_pu: float = 1.0


@dataclass(frozen=True, slots=True)
class Line:
    from_bus: int
    to_bus: int
    r_pu: float
    x_pu: float
    limit_mw: float

    @property
    def id(self) -> str:
        return f"{self.from_bus}-{self.to_bus}"

    @property
    def b_pu(self) -> float:
        """Series susceptance (1/X) used in DC power flow."""
        return 1.0 / self.x_pu


@dataclass(frozen=True, slots=True)
class Generator:
    bus_id: int
    p_max_mw: float
    inertia_M: float
    damping_D: float
    p_mech_mw: float  # initial mechanical power setpoint


BUSES: Final[tuple[Bus, ...]] = (
    Bus(1, "Gen-1 (Slack)", "slack", p_gen_mw=247.0),
    Bus(2, "Gen-2",         "gen",   p_gen_mw=163.0),
    Bus(3, "Gen-3",         "gen",   p_gen_mw=85.0),
    Bus(4, "Junc-4",        "junction"),
    Bus(5, "Load-5",        "load",  p_load_mw=125.0),
    Bus(6, "Load-6",        "load",  p_load_mw=90.0),
    Bus(7, "Junc-7",        "junction"),
    Bus(8, "Load-8",        "load",  p_load_mw=100.0),
    Bus(9, "Junc-9",        "junction"),
)

LINES: Final[tuple[Line, ...]] = (
    Line(1, 4, r_pu=0.0000, x_pu=0.0576, limit_mw=250.0),
    Line(4, 5, r_pu=0.0170, x_pu=0.0920, limit_mw=150.0),
    Line(5, 6, r_pu=0.0390, x_pu=0.1700, limit_mw=150.0),
    Line(3, 6, r_pu=0.0000, x_pu=0.0586, limit_mw=250.0),
    Line(6, 7, r_pu=0.0119, x_pu=0.1008, limit_mw=150.0),
    Line(7, 8, r_pu=0.0085, x_pu=0.0720, limit_mw=150.0),
    Line(8, 2, r_pu=0.0000, x_pu=0.0625, limit_mw=250.0),
    Line(8, 9, r_pu=0.0320, x_pu=0.1610, limit_mw=150.0),
    Line(9, 4, r_pu=0.0100, x_pu=0.0850, limit_mw=150.0),
)

GENERATORS: Final[tuple[Generator, ...]] = (
    Generator(bus_id=1, p_max_mw=247.0, inertia_M=10.0, damping_D=1.0, p_mech_mw=247.0),
    Generator(bus_id=2, p_max_mw=163.0, inertia_M=6.0,  damping_D=1.0, p_mech_mw=163.0),
    Generator(bus_id=3, p_max_mw=85.0,  inertia_M=3.0,  damping_D=1.0, p_mech_mw=85.0),
)

BUS_INDEX: Final[dict[int, int]] = {bus.id: idx for idx, bus in enumerate(BUSES)}
NUM_BUSES: Final[int] = len(BUSES)
NUM_LINES: Final[int] = len(LINES)
NUM_GENERATORS: Final[int] = len(GENERATORS)
GEN_BUS_IDS: Final[tuple[int, ...]] = tuple(g.bus_id for g in GENERATORS)
