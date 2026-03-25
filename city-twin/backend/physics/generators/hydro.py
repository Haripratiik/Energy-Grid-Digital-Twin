"""Hydro generator model -- fast governor response, reservoir tracking."""

from __future__ import annotations

from .base import GeneratorModel

_RESERVOIR_DEPLETION_PCT_PER_MWH = 0.0002
_WATER_FLOW_COEFF = 0.12
_GOVERNOR_GAIN = 25.0
_NOMINAL_FREQ_HZ = 60.0


class HydroGenerator(GeneratorModel):

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self.reservoir_level_pct: float = 75.0
        self.water_flow_m3_s: float = _WATER_FLOW_COEFF * self.p_electrical_mw

    @property
    def gen_type(self) -> str:
        return "hydro"

    def step(self, dt: float, grid_frequency_hz: float) -> None:
        if not self.online:
            return

        # Governor: adjust p_mech to counteract frequency deviation
        freq_error_hz = grid_frequency_hz - _NOMINAL_FREQ_HZ
        governor_adj = -_GOVERNOR_GAIN * freq_error_hz
        target_mw = self._initial_p_mech + governor_adj

        max_delta = self.ramp_rate_mw_per_s * dt
        error = target_mw - self.p_mech_mw
        delta = max(-max_delta, min(error, max_delta))
        self.p_mech_mw += delta
        self.p_mech_mw = max(0.0, min(self.p_mech_mw, self.capacity_mw))

        # Reservoir depletion
        energy_mwh = self.p_electrical_mw * (dt / 3600.0)
        self.reservoir_level_pct -= _RESERVOIR_DEPLETION_PCT_PER_MWH * energy_mwh
        self.reservoir_level_pct = max(0.0, min(self.reservoir_level_pct, 100.0))

        self.water_flow_m3_s = _WATER_FLOW_COEFF * self.p_electrical_mw

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["reservoir_level_pct"] = round(self.reservoir_level_pct, 4)
        d["water_flow_m3_s"] = round(self.water_flow_m3_s, 2)
        return d
