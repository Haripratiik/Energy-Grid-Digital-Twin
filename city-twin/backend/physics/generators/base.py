"""Abstract base class for all generator models."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod


class GeneratorModel(ABC):
    """Base class encapsulating swing-equation state and common operations."""

    def __init__(
        self,
        bus_id: int,
        capacity_mw: float,
        inertia_M: float,
        damping_D: float,
        p_mech_mw: float,
        ramp_rate_mw_per_s: float,
    ) -> None:
        self.bus_id = bus_id
        self.capacity_mw = capacity_mw
        self.inertia_M = inertia_M
        self.damping_D = damping_D
        self.p_mech_mw = p_mech_mw
        self.p_electrical_mw = p_mech_mw
        self.ramp_rate_mw_per_s = ramp_rate_mw_per_s
        self.online = True
        self.rotor_angle_rad = 0.0
        self.rotor_speed_rad_s = 0.0
        self._initial_p_mech = p_mech_mw

    @property
    @abstractmethod
    def gen_type(self) -> str: ...

    @abstractmethod
    def step(self, dt: float, grid_frequency_hz: float) -> None:
        """Advance internal state by *dt* seconds."""
        ...

    def set_setpoint(self, target_mw: float) -> None:
        """Set new mechanical power target (clamped to capacity)."""
        self.p_mech_mw = max(0.0, min(target_mw, self.capacity_mw))

    def trip(self) -> float:
        """Take the generator offline.  Returns lost MW."""
        lost = self.p_mech_mw
        self.online = False
        self.p_mech_mw = 0.0
        self.p_electrical_mw = 0.0
        self.rotor_angle_rad = 0.0
        self.rotor_speed_rad_s = 0.0
        return lost

    def restore(self) -> None:
        """Restore to initial conditions."""
        self.online = True
        self.p_mech_mw = self._initial_p_mech
        self.p_electrical_mw = self._initial_p_mech
        self.rotor_angle_rad = 0.0
        self.rotor_speed_rad_s = 0.0

    def to_dict(self) -> dict:
        return {
            "bus_id": self.bus_id,
            "gen_type": self.gen_type,
            "capacity_mw": self.capacity_mw,
            "p_mech_mw": round(self.p_mech_mw, 2),
            "p_electrical_mw": round(self.p_electrical_mw, 2),
            "online": self.online,
            "rotor_angle_deg": round(math.degrees(self.rotor_angle_rad), 4),
            "rotor_speed_rad_s": round(self.rotor_speed_rad_s, 6),
            "inertia_M": self.inertia_M,
        }
