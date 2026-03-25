"""Nuclear generator model -- high inertia, very slow ramp, base-load unit."""

from __future__ import annotations

from .base import GeneratorModel

_COOLANT_BASE_C = 290.0
_COOLANT_COEFF_C_PER_MW = 0.02
_COOLANT_TIME_CONST_S = 120.0


class NuclearGenerator(GeneratorModel):

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self.coolant_temp_c: float = (
            _COOLANT_BASE_C + _COOLANT_COEFF_C_PER_MW * self.p_electrical_mw
        )

    @property
    def gen_type(self) -> str:
        return "nuclear"

    def step(self, dt: float, grid_frequency_hz: float) -> None:
        if not self.online:
            return

        # Coolant temperature tracks electrical output (first-order lag)
        target_temp = _COOLANT_BASE_C + _COOLANT_COEFF_C_PER_MW * self.p_electrical_mw
        alpha = dt / _COOLANT_TIME_CONST_S
        self.coolant_temp_c += alpha * (target_temp - self.coolant_temp_c)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["coolant_temp_c"] = round(self.coolant_temp_c, 2)
        return d
