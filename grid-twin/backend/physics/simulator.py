"""
DC Power Flow & Swing-Equation Simulator
=========================================
Real-time transient-stability engine for the IEEE 9-bus test system.

Physics:
  - DC power flow via nodal susceptance (B-matrix) method
  - Swing equation for generator rotor dynamics (RK4 integration)
  - Proper coupling: generator bus angles from swing eq, non-gen angles
    from constrained network solve

All matrix algebra runs through JAX for GPU/TPU portability.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

import jax.numpy as jnp
import numpy as np
from pydantic import BaseModel, Field

from .ieee9bus import (
    BASE_MVA,
    BUS_INDEX,
    BUSES,
    GEN_BUS_IDS,
    GENERATORS,
    LINES,
    NUM_BUSES,
    NUM_GENERATORS,
    NUM_LINES,
    SLACK_BUS,
    SYSTEM_FREQ_HZ,
)

TWO_PI: float = 2.0 * math.pi
RK4_DT: float = 0.01
OVERLOAD_THRESHOLD: float = 0.80


# ---------------------------------------------------------------------------
# Pydantic v2 state models
# ---------------------------------------------------------------------------

class BusState(BaseModel):
    id: int
    voltage_angle_deg: float
    power_generation_mw: float
    power_load_mw: float
    status: str


class LineState(BaseModel):
    id: str
    flow_mw: float
    flow_pct_of_limit: float
    status: str
    tripped: bool


class GeneratorState(BaseModel):
    bus_id: int
    rotor_angle_deg: float
    rotor_speed_rad_s: float
    mechanical_power_mw: float
    electrical_power_mw: float
    online: bool


class GridState(BaseModel):
    sim_time_s: float
    wall_time: str
    system_frequency_hz: float
    total_generation_mw: float
    total_load_mw: float
    buses: list[BusState]
    lines: list[LineState]
    generators: list[GeneratorState]
    active_alerts: list = Field(default_factory=list)
    ontology_dirty: bool = False


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class GridSimulator:
    """Stateful transient-stability simulator for the IEEE 9-bus system."""

    def __init__(self) -> None:
        self._sim_time: float = 0.0
        self._step_count: int = 0

        self._theta = np.zeros(NUM_BUSES, dtype=np.float64)
        self._p_gen = np.array([b.p_gen_mw for b in BUSES], dtype=np.float64)
        self._p_load = np.array([b.p_load_mw for b in BUSES], dtype=np.float64)

        self._gen_delta = np.zeros(NUM_GENERATORS, dtype=np.float64)
        self._gen_omega = np.zeros(NUM_GENERATORS, dtype=np.float64)
        self._gen_pm = np.array([g.p_mech_mw for g in GENERATORS], dtype=np.float64)
        self._gen_pe = np.zeros(NUM_GENERATORS, dtype=np.float64)
        self._gen_online = np.ones(NUM_GENERATORS, dtype=bool)

        self._line_tripped = np.zeros(NUM_LINES, dtype=bool)

        # Index sets for the constrained power flow
        self._gen_bus_indices = np.array([BUS_INDEX[g.bus_id] for g in GENERATORS])
        self._non_gen_indices = np.array(
            [i for i in range(NUM_BUSES) if i not in self._gen_bus_indices]
        )

        # Build B-matrix and solve initial equilibrium
        self._B = self._build_B_matrix()
        self._solve_initial_equilibrium()

        # Cache nominal values for restore
        self._nominal_theta = self._theta.copy()
        self._nominal_p_gen = self._p_gen.copy()
        self._nominal_p_load = self._p_load.copy()
        self._nominal_gen_pm = self._gen_pm.copy()
        self._nominal_gen_pe = self._gen_pe.copy()
        self._nominal_gen_delta = self._gen_delta.copy()

    # ------------------------------------------------------------------
    # B-matrix construction
    # ------------------------------------------------------------------

    def _build_B_matrix(self) -> np.ndarray:
        """Build nodal susceptance matrix from active (non-tripped) lines."""
        B = np.zeros((NUM_BUSES, NUM_BUSES), dtype=np.float64)
        for idx, line in enumerate(LINES):
            if self._line_tripped[idx]:
                continue
            i = BUS_INDEX[line.from_bus]
            j = BUS_INDEX[line.to_bus]
            b = line.b_pu
            B[i, j] -= b
            B[j, i] -= b
            B[i, i] += b
            B[j, j] += b
        return B

    # ------------------------------------------------------------------
    # Initial DC power flow (standard slack-bus formulation)
    # ------------------------------------------------------------------

    def _solve_initial_equilibrium(self) -> None:
        """Standard DC power flow to establish equilibrium angles and P_e."""
        p_inject_pu = (self._p_gen - self._p_load) / BASE_MVA
        slack_idx = BUS_INDEX[SLACK_BUS]

        non_slack = [i for i in range(NUM_BUSES) if i != slack_idx]
        ns = np.array(non_slack)

        B_reduced = jnp.array(self._B[np.ix_(ns, ns)])
        P_reduced = jnp.array(p_inject_pu[ns])
        theta_reduced = np.array(jnp.linalg.solve(B_reduced, P_reduced))

        self._theta[:] = 0.0
        self._theta[ns] = theta_reduced

        # Set generator deltas to match their equilibrium bus angles
        for g_idx, gen in enumerate(GENERATORS):
            bus_idx = BUS_INDEX[gen.bus_id]
            self._gen_delta[g_idx] = self._theta[bus_idx]

        # Compute P_e at each generator and set P_m = P_e for equilibrium
        self._compute_gen_pe()
        self._gen_pm[:] = self._gen_pe.copy()

        # Update p_gen array to reflect actual generation
        for g_idx, gen in enumerate(GENERATORS):
            self._p_gen[BUS_INDEX[gen.bus_id]] = self._gen_pe[g_idx]

    # ------------------------------------------------------------------
    # Constrained network solve: gen angles fixed, solve for non-gen
    # ------------------------------------------------------------------

    def _solve_network_constrained(self) -> None:
        """
        Given generator bus angles (from swing eq), solve for non-gen bus
        angles using B_nn * theta_n = P_n - B_ng * theta_g.
        """
        # Set generator bus angles from rotor angles
        for g_idx, gen in enumerate(GENERATORS):
            if self._gen_online[g_idx]:
                self._theta[BUS_INDEX[gen.bus_id]] = self._gen_delta[g_idx]

        ng = self._non_gen_indices
        gg = self._gen_bus_indices

        if len(ng) == 0:
            return

        B_nn = self._B[np.ix_(ng, ng)]
        B_ng = self._B[np.ix_(ng, gg)]
        theta_g = self._theta[gg]

        p_inject_n = -self._p_load[ng] / BASE_MVA
        rhs = p_inject_n - B_ng @ theta_g

        try:
            theta_n = np.array(jnp.linalg.solve(jnp.array(B_nn), jnp.array(rhs)))
            if np.all(np.isfinite(theta_n)):
                self._theta[ng] = theta_n
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Compute P_e for each generator from line flows
    # ------------------------------------------------------------------

    def _compute_gen_pe(self) -> None:
        """Compute electrical power output of each generator from theta."""
        for g_idx, gen in enumerate(GENERATORS):
            if not self._gen_online[g_idx]:
                self._gen_pe[g_idx] = 0.0
                continue
            bus_idx = BUS_INDEX[gen.bus_id]
            p_inject_pu = 0.0
            for l_idx, line in enumerate(LINES):
                if self._line_tripped[l_idx]:
                    continue
                i = BUS_INDEX[line.from_bus]
                j = BUS_INDEX[line.to_bus]
                if i == bus_idx:
                    p_inject_pu += (self._theta[i] - self._theta[j]) / line.x_pu
                elif j == bus_idx:
                    p_inject_pu += (self._theta[j] - self._theta[i]) / line.x_pu

            pe_mw = p_inject_pu * BASE_MVA + self._p_load[bus_idx]
            self._gen_pe[g_idx] = pe_mw
            self._p_gen[bus_idx] = pe_mw

    # ------------------------------------------------------------------
    # Line flow computation
    # ------------------------------------------------------------------

    def _compute_line_flows(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (flow_mw, flow_pct, overloaded) arrays aligned to LINES."""
        flow_mw = np.zeros(NUM_LINES, dtype=np.float64)
        flow_pct = np.zeros(NUM_LINES, dtype=np.float64)
        overloaded = np.zeros(NUM_LINES, dtype=bool)

        for idx, line in enumerate(LINES):
            if self._line_tripped[idx]:
                continue
            i = BUS_INDEX[line.from_bus]
            j = BUS_INDEX[line.to_bus]
            flow_pu = (self._theta[i] - self._theta[j]) / line.x_pu
            mw = flow_pu * BASE_MVA
            pct = abs(mw) / line.limit_mw if line.limit_mw > 0 else 0.0
            flow_mw[idx] = mw
            flow_pct[idx] = pct
            overloaded[idx] = pct > OVERLOAD_THRESHOLD

        return flow_mw, flow_pct, overloaded

    # ------------------------------------------------------------------
    # Swing equation RHS
    # ------------------------------------------------------------------

    def _swing_derivatives(
        self, delta: np.ndarray, omega: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        d(delta)/dt = omega
        d(omega)/dt = (1/M_i) * (P_m_i - P_e_i - D_i * omega_i)
        """
        d_delta = omega.copy()
        d_omega = np.zeros(NUM_GENERATORS, dtype=np.float64)

        for g_idx, gen in enumerate(GENERATORS):
            if not self._gen_online[g_idx]:
                continue
            pm_pu = self._gen_pm[g_idx] / BASE_MVA
            pe_pu = self._gen_pe[g_idx] / BASE_MVA
            d_omega[g_idx] = (pm_pu - pe_pu - gen.damping_D * omega[g_idx]) / gen.inertia_M

        return d_delta, d_omega

    # ------------------------------------------------------------------
    # Full coupled step: swing eq + constrained network solve
    # ------------------------------------------------------------------

    def _coupled_derivatives(self, delta: np.ndarray, omega: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Evaluate swing eq RHS with proper network coupling."""
        saved_delta = self._gen_delta.copy()
        saved_theta = self._theta.copy()

        self._gen_delta[:] = delta
        self._solve_network_constrained()
        self._compute_gen_pe()
        result = self._swing_derivatives(delta, omega)

        self._gen_delta[:] = saved_delta
        self._theta[:] = saved_theta

        return result

    # ------------------------------------------------------------------
    # RK4 integration step
    # ------------------------------------------------------------------

    def step(self) -> Optional[GridState]:
        """
        Advance the simulation by one RK4 timestep (dt = 0.01 s).
        Returns a GridState snapshot every 10 steps (100 ms equivalent).
        """
        dt = RK4_DT
        delta = self._gen_delta.copy()
        omega = self._gen_omega.copy()

        k1_d, k1_w = self._coupled_derivatives(delta, omega)
        k2_d, k2_w = self._coupled_derivatives(delta + 0.5 * dt * k1_d, omega + 0.5 * dt * k1_w)
        k3_d, k3_w = self._coupled_derivatives(delta + 0.5 * dt * k2_d, omega + 0.5 * dt * k2_w)
        k4_d, k4_w = self._coupled_derivatives(delta + dt * k3_d, omega + dt * k3_w)

        self._gen_delta = delta + (dt / 6.0) * (k1_d + 2 * k2_d + 2 * k3_d + k4_d)
        self._gen_omega = omega + (dt / 6.0) * (k1_w + 2 * k2_w + 2 * k3_w + k4_w)

        # Clamp to prevent numerical divergence on extreme faults
        self._gen_delta = np.clip(self._gen_delta, -math.pi, math.pi)
        self._gen_omega = np.clip(self._gen_omega, -50.0, 50.0)

        # Final network update with new angles
        self._solve_network_constrained()
        self._compute_gen_pe()

        self._sim_time += dt
        self._step_count += 1

        if self._step_count % 10 == 0:
            return self.get_state()
        return None

    # ------------------------------------------------------------------
    # State snapshot
    # ------------------------------------------------------------------

    def get_state(self) -> GridState:
        flow_mw, flow_pct, overloaded = self._compute_line_flows()

        def _safe(v: float, default: float = 0.0) -> float:
            return v if np.isfinite(v) else default

        buses: list[BusState] = []
        for bus in BUSES:
            idx = BUS_INDEX[bus.id]
            buses.append(
                BusState(
                    id=bus.id,
                    voltage_angle_deg=round(_safe(math.degrees(self._theta[idx])), 4),
                    power_generation_mw=round(_safe(self._p_gen[idx]), 2),
                    power_load_mw=round(_safe(self._p_load[idx]), 2),
                    status="NOMINAL",
                )
            )

        lines: list[LineState] = []
        for l_idx, line in enumerate(LINES):
            tripped = bool(self._line_tripped[l_idx])
            if tripped:
                status = "TRIPPED"
            elif overloaded[l_idx]:
                status = "OVERLOADED"
            else:
                status = "NOMINAL"
            lines.append(
                LineState(
                    id=line.id,
                    flow_mw=round(_safe(float(flow_mw[l_idx])), 2),
                    flow_pct_of_limit=round(_safe(float(flow_pct[l_idx])), 4),
                    status=status,
                    tripped=tripped,
                )
            )

        generators: list[GeneratorState] = []
        for g_idx, gen in enumerate(GENERATORS):
            generators.append(
                GeneratorState(
                    bus_id=gen.bus_id,
                    rotor_angle_deg=round(_safe(math.degrees(self._gen_delta[g_idx])), 4),
                    rotor_speed_rad_s=round(_safe(float(self._gen_omega[g_idx])), 6),
                    mechanical_power_mw=round(_safe(float(self._gen_pm[g_idx])), 2),
                    electrical_power_mw=round(_safe(float(self._gen_pe[g_idx])), 2),
                    online=bool(self._gen_online[g_idx]),
                )
            )

        online_omegas = self._gen_omega[self._gen_online]
        mean_omega = float(np.mean(online_omegas)) if len(online_omegas) > 0 else 0.0
        if not np.isfinite(mean_omega):
            mean_omega = 0.0
        system_freq = SYSTEM_FREQ_HZ + mean_omega / TWO_PI

        total_gen = sum(g.electrical_power_mw for g in generators if g.online)
        total_load = float(np.sum(self._p_load))

        return GridState(
            sim_time_s=round(self._sim_time, 4),
            wall_time=datetime.now(timezone.utc).isoformat(),
            system_frequency_hz=round(system_freq, 4),
            total_generation_mw=round(total_gen, 2),
            total_load_mw=round(total_load, 2),
            buses=buses,
            lines=lines,
            generators=generators,
            active_alerts=[],
            ontology_dirty=False,
        )

    # ------------------------------------------------------------------
    # Fault injection interface
    # ------------------------------------------------------------------

    def trip_line(self, from_bus: int, to_bus: int) -> None:
        """Remove a transmission line from service."""
        for idx, line in enumerate(LINES):
            if (line.from_bus == from_bus and line.to_bus == to_bus) or (
                line.from_bus == to_bus and line.to_bus == from_bus
            ):
                self._line_tripped[idx] = True
                break
        self._B = self._build_B_matrix()
        self._solve_network_constrained()
        self._compute_gen_pe()

    def gen_dropout(self, bus_id: int) -> None:
        """Take a generator offline and redistribute its mechanical power."""
        for g_idx, gen in enumerate(GENERATORS):
            if gen.bus_id == bus_id:
                self._gen_online[g_idx] = False
                lost_pm = self._gen_pm[g_idx]
                self._gen_pm[g_idx] = 0.0
                self._gen_pe[g_idx] = 0.0
                self._p_gen[BUS_INDEX[bus_id]] = 0.0
                self._gen_omega[g_idx] = 0.0
                self._gen_delta[g_idx] = 0.0

                online_mask = self._gen_online.copy()
                total_inertia = sum(
                    GENERATORS[i].inertia_M for i in range(NUM_GENERATORS) if online_mask[i]
                )
                if total_inertia > 0:
                    for i in range(NUM_GENERATORS):
                        if online_mask[i]:
                            share = GENERATORS[i].inertia_M / total_inertia
                            self._gen_pm[i] += lost_pm * share
                break

        self._B = self._build_B_matrix()
        self._solve_network_constrained()
        self._compute_gen_pe()

    def load_spike(self, bus_id: int, magnitude_mw: float) -> None:
        """Increase demand at a load bus by the given MW amount."""
        idx = BUS_INDEX[bus_id]
        self._p_load[idx] += magnitude_mw
        self._solve_network_constrained()
        self._compute_gen_pe()

    def restore(self) -> None:
        """Reset all state to nominal initial conditions."""
        self._sim_time = 0.0
        self._step_count = 0
        self._theta[:] = self._nominal_theta.copy()
        self._p_gen[:] = self._nominal_p_gen.copy()
        self._p_load[:] = self._nominal_p_load.copy()
        self._gen_delta[:] = self._nominal_gen_delta.copy()
        self._gen_omega[:] = 0.0
        self._gen_pm[:] = self._nominal_gen_pm.copy()
        self._gen_pe[:] = self._nominal_gen_pe.copy()
        self._gen_online[:] = True
        self._line_tripped[:] = False
        self._B = self._build_B_matrix()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def sim_time(self) -> float:
        return self._sim_time

    @property
    def line_tripped(self) -> np.ndarray:
        return self._line_tripped

    @property
    def gen_online(self) -> np.ndarray:
        return self._gen_online
