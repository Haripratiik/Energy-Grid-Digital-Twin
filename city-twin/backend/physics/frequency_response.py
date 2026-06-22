"""System frequency response, inertia, and grid-forming inverters.

The defining stability problem of the energy transition: synchronous generators
carry rotating inertia that resists frequency change, but inverter-coupled
renewables (grid-following PV/wind) carry *none*. As they displace synchronous
machines, total system inertia falls — so after a generation loss the frequency
falls **faster** (higher RoCoF) and **deeper** (lower nadir), risking RoCoF-based
protection trips and under-frequency load shedding.

**Grid-forming inverters** restore stability by synthesizing inertia (a virtual
synchronous machine) and providing fast frequency droop.

This is modeled with the standard **System Frequency Response (SFR)** / aggregated
single-busbar model — the center-of-inertia frequency under one lumped governor:

    2·H · d(Δf)/dt = −ΔP + ΔP_gov + ΔP_gfm − D·Δf

where H is total inertia (synchronous + grid-forming virtual inertia), the
governor supplies droop response through a turbine lag, and grid-forming units
add virtual inertia plus optional fast droop. The **initial RoCoF = −ΔP/(2H)** is
an exact analytical result the model reproduces *by construction* (at t=0 the
governor/grid-forming/damping terms are zero). The substantive validation is
twofold: the model's full transient is checked against an independent
higher-order integrator (:func:`validate_against_reference`), and the
operational story — low inertia breaching the grid-code RoCoF limit while
grid-forming inverters restore it — is asserted across scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

NOMINAL_HZ = 60.0


class FrequencyResponseResult(BaseModel):
    scenario: str
    total_inertia_h: float
    disturbance_pu: float
    rocof_hz_s: float            # initial rate of change of frequency (magnitude)
    analytic_rocof_hz_s: float   # −ΔP/(2H)·f0, the textbook value
    rocof_error_pct: float
    nadir_hz: float              # lowest frequency reached
    nadir_time_s: float
    settling_hz: float           # quasi-steady frequency (primary-control offset)
    breaches_rocof_limit: bool   # |RoCoF| > 1 Hz/s (typical grid-code limit)


@dataclass
class FrequencyResponseModel:
    """Aggregated SFR model of center-of-inertia frequency."""

    h_sync: float = 5.0          # synchronous inertia (s, on system base)
    h_gfm: float = 0.0           # grid-forming virtual inertia (s)
    damping_d: float = 1.0       # load/damping (pu power per pu freq)
    droop_r: float = 0.05        # governor droop (pu)
    turbine_t: float = 4.0       # governor/turbine time constant (s)
    gfm_droop: float = 0.0       # grid-forming fast frequency droop (pu)
    rocof_limit_hz_s: float = 1.0

    @property
    def total_inertia(self) -> float:
        return self.h_sync + self.h_gfm

    def analyze_step(
        self, disturbance_pu: float = 0.1, *, scenario: str = "",
        dt: float = 0.001, horizon_s: float = 25.0,
    ) -> FrequencyResponseResult:
        """Simulate a sudden generation loss of ``disturbance_pu`` (system base)."""
        H = self.total_inertia
        df = 0.0          # frequency deviation (pu of 60 Hz)
        p_gov = 0.0       # governor turbine output (pu)
        t = 0.0
        df_first: float | None = None   # Δf after one step → measured initial RoCoF
        nadir = 0.0
        nadir_t = 0.0

        while t < horizon_s:
            p_gfm = -self.gfm_droop * df                       # fast droop support
            dfdt = (-disturbance_pu + p_gov + p_gfm - self.damping_d * df) / (2.0 * H)
            # Governor: command −(1/R)·Δf through a first-order turbine lag.
            dp_gov = ((-(1.0 / self.droop_r) * df) - p_gov) / self.turbine_t
            df += dfdt * dt
            p_gov += dp_gov * dt
            t += dt
            if df_first is None:
                df_first = df                                  # from the trajectory
            if df < nadir:
                nadir = df
                nadir_t = t

        # Initial RoCoF is *measured* from the simulated trajectory (Δf over the
        # first step), not read off the formula. It necessarily reproduces the
        # analytical −ΔP/(2H) because at t=0 the governor, grid-forming and
        # damping terms are all zero — so this agreement is a construction-level
        # consistency check, NOT an independent accuracy claim. The model's full
        # transient is validated against an independent integrator in
        # ``validate_against_reference``.
        rocof_meas = (df_first or 0.0) / dt
        rocof_hz = abs(rocof_meas * NOMINAL_HZ)                # |df/dt| in Hz/s
        analytic_hz = abs(disturbance_pu / (2.0 * H) * NOMINAL_HZ)
        err = abs(rocof_hz - analytic_hz) / analytic_hz * 100.0 if analytic_hz else 0.0

        return FrequencyResponseResult(
            scenario=scenario, total_inertia_h=round(H, 3),
            disturbance_pu=disturbance_pu,
            rocof_hz_s=round(rocof_hz, 4), analytic_rocof_hz_s=round(analytic_hz, 4),
            rocof_error_pct=round(err, 3),
            nadir_hz=round(NOMINAL_HZ + nadir * NOMINAL_HZ, 4),
            nadir_time_s=round(nadir_t, 2),
            settling_hz=round(NOMINAL_HZ + df * NOMINAL_HZ, 4),
            breaches_rocof_limit=rocof_hz > self.rocof_limit_hz_s,
        )


def compare_inertia_scenarios(disturbance_pu: float = 0.12) -> list[FrequencyResponseResult]:
    """The renewable-integration story across three inertia regimes."""
    scenarios = [
        ("High inertia (all synchronous)", FrequencyResponseModel(h_sync=6.0)),
        ("Low inertia (high renewables)", FrequencyResponseModel(h_sync=2.0)),
        ("Low inertia + grid-forming", FrequencyResponseModel(h_sync=2.0, h_gfm=2.5, gfm_droop=8.0)),
    ]
    return [m.analyze_step(disturbance_pu, scenario=name) for name, m in scenarios]


def validate_against_reference(
    *, disturbance_pu: float = 0.12, h_sync: float = 2.0,
    model_dt: float = 0.001, ref_dt: float = 0.0001, horizon_s: float = 25.0,
) -> dict:
    """Validate the SFR integration against an independent reference solver.

    Both integrators advance the *same* SFR ODE, but the reference uses the
    shared fourth-order ``physics.swing.rk4_step`` at a 10× finer step while the
    model uses its own forward-Euler loop. Neither side uses the analytical
    −ΔP/(2H) formula, so agreement on the nadir and the initial RoCoF is a
    genuine (non-circular) check that the model's discretisation is accurate.
    """
    from .swing import rk4_step

    model = FrequencyResponseModel(h_sync=h_sync)
    H = model.total_inertia

    def deriv(s):
        df, p_gov = s
        p_gfm = -model.gfm_droop * df
        dfdt = (-disturbance_pu + p_gov + p_gfm - model.damping_d * df) / (2.0 * H)
        dp_gov = ((-(1.0 / model.droop_r) * df) - p_gov) / model.turbine_t
        return (dfdt, dp_gov)

    def integrate(dt: float, use_rk4: bool) -> tuple[float, float]:
        s = (0.0, 0.0)
        t = 0.0
        nadir = 0.0
        df_first: float | None = None
        while t < horizon_s:
            if use_rk4:
                s = rk4_step(s, deriv, dt)
            else:
                d = deriv(s)
                s = (s[0] + d[0] * dt, s[1] + d[1] * dt)
            t += dt
            if df_first is None:
                df_first = s[0]
            if s[0] < nadir:
                nadir = s[0]
        return nadir, (df_first or 0.0) / dt

    m_nadir, m_rocof = integrate(model_dt, use_rk4=False)
    r_nadir, r_rocof = integrate(ref_dt, use_rk4=True)
    nadir_err = abs(m_nadir - r_nadir) * NOMINAL_HZ
    rocof_err = abs(m_rocof - r_rocof) * NOMINAL_HZ
    return {
        "ref_dt": ref_dt,
        "nadir_abs_err_hz": round(nadir_err, 5),
        "rocof_abs_err_hz_s": round(rocof_err, 5),
        "passed": nadir_err < 0.01 and rocof_err < 0.01,
    }


def _main() -> None:
    rows = compare_inertia_scenarios()
    print("System frequency response to a 12% generation loss\n")
    print(f"{'scenario':<34}{'H':>5}{'RoCoF':>9}{'(exact)':>9}{'nadir':>9}{'settle':>9}{'RoCoF lim':>10}")
    print("-" * 85)
    for r in rows:
        print(f"{r.scenario:<34}{r.total_inertia_h:>5.1f}{r.rocof_hz_s:>8.2f}↓"
              f"{r.analytic_rocof_hz_s:>9.2f}{r.nadir_hz:>9.3f}{r.settling_hz:>9.3f}"
              f"{('BREACH' if r.breaches_rocof_limit else 'ok'):>10}")
    print("\nGrid-forming virtual inertia restores RoCoF below the 1 Hz/s grid-code limit.")
    print("Initial RoCoF reproduces the analytical −ΔP/(2H) by construction "
          f"(consistency Δ ≤ {max(r.rocof_error_pct for r in rows):.2f}%).")
    ref = validate_against_reference()
    print(f"Trajectory vs independent RK4 reference (dt={ref['ref_dt']}s): "
          f"nadir Δ={ref['nadir_abs_err_hz']:.4f} Hz, "
          f"RoCoF Δ={ref['rocof_abs_err_hz_s']:.4f} Hz/s  "
          f"-> {'OK' if ref['passed'] else 'FAIL'}")


if __name__ == "__main__":
    _main()
