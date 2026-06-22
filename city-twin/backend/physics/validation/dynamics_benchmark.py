"""Validate the swing-equation dynamics against analytical theory.

* **SMIB period** — a single machine against an infinite bus has a textbook
  small-signal oscillation frequency ω_n = √(K_s / M), where K_s is the
  synchronizing coefficient. We integrate the swing equation with the *exact
  same* RK4 integrator the live simulator uses (``physics.swing.rk4_step``) and
  confirm the measured oscillation period matches the analytical value to <2 %.

* **Governor response** — with turbine-governors enabled, primary frequency
  control must arrest and partially restore frequency after a generation loss,
  leaving a smaller steady-state deviation than the ungoverned machine.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from physics.network import NOMINAL_FREQ_HZ
from physics.swing import GridSimulator, rk4_step


class SMIBValidation(BaseModel):
    inertia_M: float
    synchronizing_coeff: float
    analytic_period_s: float
    simulated_period_s: float
    rel_error: float
    passed: bool


class GovernorValidation(BaseModel):
    disturbance: str
    freq_ungoverned_hz: float
    freq_governed_hz: float
    deviation_ungoverned_hz: float
    deviation_governed_hz: float
    improvement_ratio: float
    primary_response_mw: float    # total MW the governors picked up
    passed: bool


def validate_smib(
    *, M: float = 10.0, E: float = 1.05, V: float = 1.0, X: float = 0.5,
    Pm: float = 0.5, dt: float = 0.002, n_periods: int = 8,
) -> SMIBValidation:
    """Compare simulated vs analytical small-signal oscillation period."""
    sin_d0 = Pm * X / (E * V)
    delta0 = math.asin(sin_d0)
    Ks = (E * V / X) * math.cos(delta0)          # synchronizing coefficient (pu)
    omega_n = math.sqrt(Ks / M)
    T_analytic = 2.0 * math.pi / omega_n

    # Integrate the undamped swing equation with the *exact same* RK4 integrator
    # the live simulator uses (physics.swing.rk4_step), so this validates the
    # production integrator — not a throwaway loop. State y = (δ, ω):
    #   dδ/dt = ω,   M·dω/dt = Pm − Pe(δ)
    def _deriv(s):
        delta_, omega_ = s
        Pe = (E * V / X) * math.sin(delta_)
        return (omega_, (Pm - Pe) / M)

    delta = delta0 + 0.05                        # small perturbation
    omega = 0.0
    t = 0.0
    prev = delta - delta0
    crossings: list[float] = []
    while t < n_periods * T_analytic:
        delta, omega = rk4_step((delta, omega), _deriv, dt)
        t += dt
        cur = delta - delta0
        if prev < 0.0 <= cur:                    # upward zero crossing
            frac = -prev / (cur - prev)
            crossings.append(t - dt + frac * dt)
        prev = cur

    if len(crossings) >= 2:
        T_sim = (crossings[-1] - crossings[0]) / (len(crossings) - 1)
    else:
        T_sim = float("nan")
    rel_err = abs(T_sim - T_analytic) / T_analytic

    return SMIBValidation(
        inertia_M=M, synchronizing_coeff=round(Ks, 4),
        analytic_period_s=round(T_analytic, 4), simulated_period_s=round(T_sim, 4),
        rel_error=round(rel_err, 5), passed=rel_err < 0.02,
    )


def validate_governor(*, settle_ticks: int = 150, post_ticks: int = 2500) -> GovernorValidation:
    """Drop the largest non-slack generator; compare steady-state frequency
    deviation with and without turbine-governors."""
    import random

    def run(governor_enabled: bool) -> tuple[float, float]:
        random.seed(0)
        sim = GridSimulator(governor_enabled=governor_enabled)
        for _ in range(settle_ticks):
            sim.step()
        # Survivors = governed machines other than the one we will trip.
        def survivor_pm() -> float:
            return sum(g.p_mech_mw for g in sim.generators
                       if g.inertia_M > 0 and g.bus_id != 3)
        pm_before = survivor_pm()
        sim.gen_dropout(3)                       # lose the 280 MW gas peaker
        last = sim.get_state()
        for _ in range(post_ticks):
            s = sim.step()
            if s is not None:
                last = s
        # Primary response = extra MW the surviving governed machines picked up.
        return last.system_frequency_hz, survivor_pm() - pm_before

    f_no, _ = run(False)
    f_gov, response = run(True)
    dev_no = abs(f_no - NOMINAL_FREQ_HZ)
    dev_gov = abs(f_gov - NOMINAL_FREQ_HZ)
    ratio = dev_gov / dev_no if dev_no > 1e-9 else 0.0
    return GovernorValidation(
        disturbance="gen_dropout bus 3 (280 MW)",
        freq_ungoverned_hz=round(f_no, 4), freq_governed_hz=round(f_gov, 4),
        deviation_ungoverned_hz=round(dev_no, 5), deviation_governed_hz=round(dev_gov, 5),
        improvement_ratio=round(ratio, 3), primary_response_mw=round(response, 1),
        passed=dev_gov < dev_no and response > 0,
    )


if __name__ == "__main__":
    print("Swing-equation dynamics validation\n")
    smib = validate_smib()
    print("SMIB small-signal oscillation:")
    print(f"  K_s={smib.synchronizing_coeff}  analytic T={smib.analytic_period_s}s  "
          f"simulated T={smib.simulated_period_s}s  err={smib.rel_error*100:.3f}%  "
          f"{'OK' if smib.passed else 'FAIL'}")
    gov = validate_governor()
    print(f"\nGovernor primary frequency control ({gov.disturbance}):")
    print(f"  ungoverned f={gov.freq_ungoverned_hz}Hz (Δ={gov.deviation_ungoverned_hz})")
    print(f"  governed   f={gov.freq_governed_hz}Hz (Δ={gov.deviation_governed_hz})")
    print(f"  primary response: governors picked up {gov.primary_response_mw} MW")
    print(f"  deviation reduced to {gov.improvement_ratio*100:.0f}% of ungoverned  "
          f"{'OK' if gov.passed else 'FAIL'}")
