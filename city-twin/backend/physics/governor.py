"""Turbine-governor primary frequency control.

Each synchronous machine carries a speed governor: when system frequency drops,
the governor opens the turbine valve to raise mechanical power (and vice-versa),
following a proportional **droop** characteristic with a first-order turbine lag.

    Pm_command = Pm_ref − (1/R) · (Δf / f_nominal) · P_rated
    dPm/dt     = (Pm_command − Pm) / T_turbine

This is *primary* frequency control — it arrests and partially restores frequency
after a disturbance but, by design, leaves a steady-state offset set by the
aggregate droop (removing that offset is the job of secondary control / AGC, or
of the operator/AI dispatch layer). Droop ``R = 0.05`` means a 5 % frequency
deviation drives 100 % power change — the standard governor setting.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TurbineGovernor:
    droop: float = 0.05          # R — per-unit speed regulation
    time_const_s: float = 4.0    # turbine first-order lag
    f_nominal: float = 60.0

    def step(self, gen, system_freq_hz: float, dt: float) -> None:
        """Advance one machine's governed mechanical power by ``dt`` seconds."""
        if not gen.online or gen.inertia_M <= 0:
            return  # only synchronous machines have governors here
        df_pu = (system_freq_hz - self.f_nominal) / self.f_nominal
        command = gen._initial_p_mech - (1.0 / self.droop) * df_pu * gen.capacity_mw
        command = max(0.0, min(command, gen.capacity_mw))
        gen.p_mech_mw += (command - gen.p_mech_mw) * min(1.0, dt / self.time_const_s)
