"""Wind generator model — stochastic wind via Ornstein-Uhlenbeck, power curve."""

from __future__ import annotations

import math
import random

from .base import GeneratorModel

# Ornstein-Uhlenbeck parameters for wind speed
_OU_THETA = 0.05         # mean-reversion rate  (1/s)
_OU_MU = 9.0             # long-run mean wind speed  (m/s)
_OU_SIGMA = 1.5          # volatility  (m/s·√s)

# Turbine power-curve breakpoints
_CUT_IN = 3.0            # m/s
_RATED_LOW = 12.0         # m/s — start of rated region
_RATED_HIGH = 25.0        # m/s — cut-out
_PITCH_RATE_DEG_PER_S = 5.0


class WindGenerator(GeneratorModel):

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self.wind_speed_m_s: float = _OU_MU
        self.blade_pitch_deg: float = 0.0
        self._curtailment_target_mw: float = self.capacity_mw

    @property
    def gen_type(self) -> str:
        return "wind"

    def _power_curve(self, ws: float) -> float:
        """Available MW from the turbine power curve (before curtailment)."""
        if ws < _CUT_IN or ws > _RATED_HIGH:
            return 0.0
        if ws >= _RATED_LOW:
            return self.capacity_mw
        # Linear ramp between cut-in and rated
        return self.capacity_mw * (ws - _CUT_IN) / (_RATED_LOW - _CUT_IN)

    def set_curtailment(self, max_mw: float) -> None:
        """Limit output below available wind power (e.g. for grid balancing)."""
        self._curtailment_target_mw = max(0.0, min(max_mw, self.capacity_mw))

    def step(self, dt: float, grid_frequency_hz: float) -> None:
        if not self.online:
            return

        # Evolve wind speed via Ornstein-Uhlenbeck process
        dw = (
            _OU_THETA * (_OU_MU - self.wind_speed_m_s) * dt
            + _OU_SIGMA * math.sqrt(dt) * random.gauss(0, 1)
        )
        self.wind_speed_m_s = max(0.0, self.wind_speed_m_s + dw)

        # Compute available power
        available_mw = self._power_curve(self.wind_speed_m_s)
        target_mw = min(available_mw, self._curtailment_target_mw)

        # Fast electronic ramp
        max_delta = self.ramp_rate_mw_per_s * dt
        error = target_mw - self.p_electrical_mw
        delta = max(-max_delta, min(error, max_delta))
        self.p_electrical_mw += delta
        self.p_electrical_mw = max(0.0, min(self.p_electrical_mw, self.capacity_mw))
        self.p_mech_mw = self.p_electrical_mw  # inverter-coupled

        # Blade pitch tracks curtailment: higher pitch ↔ more curtailment
        if available_mw > 0:
            desired_pitch = max(0.0, (1.0 - target_mw / available_mw) * 30.0)
        else:
            desired_pitch = 0.0
        pitch_delta = max(
            -_PITCH_RATE_DEG_PER_S * dt,
            min(desired_pitch - self.blade_pitch_deg, _PITCH_RATE_DEG_PER_S * dt),
        )
        self.blade_pitch_deg += pitch_delta
        self.blade_pitch_deg = max(0.0, min(self.blade_pitch_deg, 90.0))

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["wind_speed_m_s"] = round(self.wind_speed_m_s, 2)
        d["blade_pitch_deg"] = round(self.blade_pitch_deg, 2)
        return d
