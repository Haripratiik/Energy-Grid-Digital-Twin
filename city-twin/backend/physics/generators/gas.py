"""Gas turbine / peaker generator model -- fast ramp, first-order throttle lag."""

from __future__ import annotations

from .base import GeneratorModel

_THROTTLE_TIME_CONST_S = 2.0


class GasGenerator(GeneratorModel):

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self.throttle_pct: float = (
            (self.p_mech_mw / self.capacity_mw * 100.0)
            if self.capacity_mw > 0
            else 0.0
        )

    @property
    def gen_type(self) -> str:
        return "gas"

    def step(self, dt: float, grid_frequency_hz: float) -> None:
        if not self.online:
            return

        # Target throttle from current mechanical-power setpoint
        target_throttle = (
            (self.p_mech_mw / self.capacity_mw * 100.0)
            if self.capacity_mw > 0
            else 0.0
        )

        # First-order lag on throttle
        alpha = dt / _THROTTLE_TIME_CONST_S
        self.throttle_pct += alpha * (target_throttle - self.throttle_pct)
        self.throttle_pct = max(0.0, min(self.throttle_pct, 100.0))

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["throttle_pct"] = round(self.throttle_pct, 2)
        return d
