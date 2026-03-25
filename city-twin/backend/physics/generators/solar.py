"""Solar generator model — diurnal irradiance + cloud transients."""

from __future__ import annotations

import math
import random

from .base import GeneratorModel

_CLOUD_DECAY = 0.10           # 1/s — cloud-factor mean-reversion speed
_CLOUD_SIGMA = 0.08           # volatility of cloud multiplicative factor
_CLOUD_FLOOR = 0.2            # minimum cloud factor (very heavy overcast)
_IRRADIANCE_PEAK_W_M2 = 1000  # solar noon irradiance


class SolarGenerator(GeneratorModel):

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self.hour_of_day: float = 12.0  # initialised at solar noon
        self.cloud_factor: float = 1.0  # 1.0 = clear sky
        self.irradiance_w_m2: float = float(_IRRADIANCE_PEAK_W_M2)

    @property
    def gen_type(self) -> str:
        return "solar"

    @staticmethod
    def _diurnal_curve(hour: float) -> float:
        """Sinusoidal irradiance envelope: sunrise ≈ 06:00, sunset ≈ 18:00."""
        if hour < 6.0 or hour > 18.0:
            return 0.0
        return math.sin(math.pi * (hour - 6.0) / 12.0)

    def set_hour(self, hour: float) -> None:
        self.hour_of_day = hour % 24.0

    def step(self, dt: float, grid_frequency_hz: float) -> None:
        if not self.online:
            return

        # Advance time-of-day
        self.hour_of_day = (self.hour_of_day + dt / 3600.0) % 24.0

        # Diurnal envelope
        envelope = self._diurnal_curve(self.hour_of_day)

        # Cloud transients — Ornstein-Uhlenbeck around 1.0
        dcf = (
            _CLOUD_DECAY * (1.0 - self.cloud_factor) * dt
            + _CLOUD_SIGMA * math.sqrt(dt) * random.gauss(0, 1)
        )
        self.cloud_factor += dcf
        self.cloud_factor = max(_CLOUD_FLOOR, min(self.cloud_factor, 1.0))

        # Effective irradiance
        self.irradiance_w_m2 = _IRRADIANCE_PEAK_W_M2 * envelope * self.cloud_factor

        # Power output proportional to irradiance
        available_mw = self.capacity_mw * (self.irradiance_w_m2 / _IRRADIANCE_PEAK_W_M2)

        # Fast electronic ramp
        max_delta = self.ramp_rate_mw_per_s * dt
        error = available_mw - self.p_electrical_mw
        delta = max(-max_delta, min(error, max_delta))
        self.p_electrical_mw += delta
        self.p_electrical_mw = max(0.0, min(self.p_electrical_mw, self.capacity_mw))
        self.p_mech_mw = self.p_electrical_mw  # inverter-coupled

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["hour_of_day"] = round(self.hour_of_day, 4)
        d["irradiance_w_m2"] = round(self.irradiance_w_m2, 1)
        d["cloud_factor"] = round(self.cloud_factor, 4)
        return d
