"""Extended swing-equation simulator coupling rotor dynamics with AC power flow.

Each simulation tick:
1. RK4-steps every synchronous generator's rotor angle / speed via the
   classical swing equation (``M · dω/dt = Pm − Pe − D · ω``).
2. Steps non-inertia (inverter-coupled) generators for their stochastic
   processes (wind, solar).
3. Periodically re-solves the full Newton-Raphson AC power flow and
   synchronises electrical power and bus angles back to the generators.
4. Emits a :class:`GridState` snapshot every ``EMIT_EVERY`` ticks.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from .ac_powerflow import ACPowerFlow, ACResult
from .generators.base import GeneratorModel
from .generators.gas import GasGenerator
from .generators.hydro import HydroGenerator
from .generators.nuclear import NuclearGenerator
from .generators.solar import SolarGenerator
from .generators.wind import WindGenerator
from .network import (
    BASE_MVA,
    BUS_INDEX,
    BUSES,
    GENERATORS_CONFIG,
    LINES,
    NOMINAL_FREQ_HZ,
    TRANSFORMERS,
)


# ---------------------------------------------------------------------------
# Pydantic state models
# ---------------------------------------------------------------------------

class BusState(BaseModel):
    id: int
    voltage_angle_deg: float
    voltage_magnitude_pu: float
    power_generation_mw: float
    power_load_mw: float
    voltage_kv: float
    status: str


class LineState(BaseModel):
    id: str
    flow_mw: float
    flow_pct_of_limit: float
    status: str
    tripped: bool
    voltage_kv: float


class TransformerState(BaseModel):
    id: str
    loading_pct: float
    from_bus: int
    to_bus: int
    status: str


class GeneratorState(BaseModel):
    bus_id: int
    gen_type: str
    rotor_angle_deg: float
    rotor_speed_rad_s: float
    mechanical_power_mw: float
    electrical_power_mw: float
    capacity_mw: float
    online: bool
    extra: dict = Field(default_factory=dict)


class GridState(BaseModel):
    sim_time_s: float
    wall_time: str
    system_frequency_hz: float
    total_generation_mw: float
    total_load_mw: float
    total_loss_mw: float
    buses: list[BusState]
    lines: list[LineState]
    transformers: list[TransformerState]
    generators: list[GeneratorState]
    active_alerts: list = Field(default_factory=list)
    ontology_dirty: bool = False


# ---------------------------------------------------------------------------
# Generator class look-up
# ---------------------------------------------------------------------------

_GEN_TYPE_MAP: dict[str, type[GeneratorModel]] = {
    "nuclear": NuclearGenerator,
    "hydro": HydroGenerator,
    "wind": WindGenerator,
    "solar": SolarGenerator,
    "gas": GasGenerator,
}

# Keys already present on GeneratorState — stripped from the ``extra`` dict
_CORE_GEN_KEYS = frozenset({
    "bus_id", "gen_type", "capacity_mw", "online",
    "p_mech_mw", "p_electrical_mw", "rotor_angle_deg",
    "rotor_speed_rad_s", "inertia_M",
})


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class GridSimulator:
    """Real-time-ish electromechanical simulator for the 80-bus city grid."""

    RK4_DT = 0.02       # 20 ms per tick
    EMIT_EVERY = 5       # emit state every 5 ticks → 100 ms wall-clock

    def __init__(self) -> None:
        self._sim_time: float = 0.0
        self._step_count: int = 0
        self._powerflow = ACPowerFlow()

        # Instantiate generator models from the network config
        self._generators: list[GeneratorModel] = []
        for cfg in GENERATORS_CONFIG:
            cls = _GEN_TYPE_MAP[cfg["gen_type"]]
            self._generators.append(
                cls(
                    bus_id=cfg["bus_id"],
                    capacity_mw=cfg["capacity_mw"],
                    inertia_M=cfg["inertia_M"],
                    damping_D=cfg["damping_D"],
                    p_mech_mw=cfg["p_mech_mw"],
                    ramp_rate_mw_per_s=cfg["ramp_rate_mw_per_s"],
                )
            )

        self._p_load: dict[int, float] = {b.id: b.p_load_mw for b in BUSES}
        self._tripped_lines: set[int] = set()
        self._tripped_trafos: set[int] = set()

        # Initial power flow to establish equilibrium
        self._last_ac_result: Optional[ACResult] = None
        self._solve_and_sync()

        # Set Pm = Pe so each generator starts in equilibrium
        for gen in self._generators:
            gen.p_mech_mw = gen.p_electrical_mw
            gen._initial_p_mech = gen.p_electrical_mw

    # ------------------------------------------------------------------
    # AC power-flow coupling
    # ------------------------------------------------------------------

    def _solve_and_sync(self) -> None:
        """Run AC power flow and sync Pe / delta back to generators."""
        gen_p = {g.bus_id: g.p_mech_mw for g in self._generators if g.online}
        load_p = {bid: p for bid, p in self._p_load.items() if p > 0}

        result = self._powerflow.solve(
            gen_p_mw=gen_p,
            load_p_mw=load_p,
            tripped_lines=self._tripped_lines,
            tripped_trafos=self._tripped_trafos,
        )
        self._last_ac_result = result

        if result.converged:
            net = self._powerflow._net
            pp_gen = self._powerflow._pp_gen
            for gen in self._generators:
                if gen.online:
                    bus_idx = BUS_INDEX[gen.bus_id]
                    gen.rotor_angle_rad = math.radians(
                        result.bus_va_deg[bus_idx]
                    )
                    info = pp_gen.get(gen.bus_id)
                    if info:
                        etype, pidx = info
                        if etype == "gen":
                            gen.p_electrical_mw = max(
                                0.0, float(net.res_gen.at[pidx, "p_mw"])
                            )
                        else:
                            gen.p_electrical_mw = max(
                                0.0, float(net.res_sgen.at[pidx, "p_mw"])
                            )
                    else:
                        gen.p_electrical_mw = max(0.0, gen.p_mech_mw)

    # ------------------------------------------------------------------
    # Swing equation integration
    # ------------------------------------------------------------------

    def _swing_step(self, dt: float) -> None:
        """One integration step of the swing equation for all generators."""
        # Synchronous generators (inertia > 0)
        for gen in self._generators:
            if not gen.online or gen.inertia_M <= 0:
                continue

            freq = self._system_frequency()
            gen.step(dt, freq)

            pm_pu = gen.p_mech_mw / BASE_MVA
            pe_pu = gen.p_electrical_mw / BASE_MVA
            dw = (
                (pm_pu - pe_pu - gen.damping_D * gen.rotor_speed_rad_s)
                / gen.inertia_M
            )
            gen.rotor_speed_rad_s += dw * dt
            gen.rotor_angle_rad += gen.rotor_speed_rad_s * dt

            gen.rotor_angle_rad = max(-math.pi, min(math.pi, gen.rotor_angle_rad))
            gen.rotor_speed_rad_s = max(-50.0, min(50.0, gen.rotor_speed_rad_s))

        # Inverter-coupled generators (wind, solar — inertia == 0)
        freq = self._system_frequency()
        for gen in self._generators:
            if gen.online and gen.inertia_M <= 0:
                gen.step(dt, freq)

    def _system_frequency(self) -> float:
        """Inertia-weighted mean frequency across all online synchronous machines."""
        online = [g for g in self._generators if g.online and g.inertia_M > 0]
        if not online:
            return NOMINAL_FREQ_HZ
        total_M = sum(g.inertia_M for g in online)
        if total_M <= 0:
            return NOMINAL_FREQ_HZ
        weighted_omega = sum(g.rotor_speed_rad_s * g.inertia_M for g in online)
        return NOMINAL_FREQ_HZ + weighted_omega / (2.0 * math.pi * total_M)

    # ------------------------------------------------------------------
    # Main tick
    # ------------------------------------------------------------------

    def step(self) -> Optional[GridState]:
        """Advance the simulation by one RK4_DT tick.

        Returns a :class:`GridState` snapshot every ``EMIT_EVERY`` ticks,
        ``None`` otherwise.
        """
        self._swing_step(self.RK4_DT)
        self._sim_time += self.RK4_DT
        self._step_count += 1

        if self._step_count % self.EMIT_EVERY == 0:
            self._solve_and_sync()
            return self.get_state()
        return None

    # ------------------------------------------------------------------
    # State snapshot
    # ------------------------------------------------------------------

    def get_state(self) -> GridState:
        """Build the complete grid state from the last AC result + generators."""
        ac = self._last_ac_result
        has_ac = ac is not None and ac.converged

        # Per-bus generation totals
        gen_by_bus: dict[int, float] = {}
        for g in self._generators:
            if g.online:
                gen_by_bus[g.bus_id] = (
                    gen_by_bus.get(g.bus_id, 0.0) + g.p_electrical_mw
                )

        # --- buses --------------------------------------------------------
        buses: list[BusState] = []
        for i, bus in enumerate(BUSES):
            vm = ac.bus_vm_pu[i] if has_ac else 1.0
            va = ac.bus_va_deg[i] if has_ac else 0.0
            v_dev = abs(vm - 1.0)
            if v_dev > 0.10:
                status = "critical"
            elif v_dev > 0.05:
                status = "warning"
            else:
                status = "normal"
            buses.append(BusState(
                id=bus.id,
                voltage_angle_deg=round(va, 4),
                voltage_magnitude_pu=round(vm, 4),
                power_generation_mw=round(gen_by_bus.get(bus.id, 0.0), 2),
                power_load_mw=round(self._p_load.get(bus.id, 0.0), 2),
                voltage_kv=bus.voltage_kv,
                status=status,
            ))

        # --- lines --------------------------------------------------------
        lines: list[LineState] = []
        for i, ln in enumerate(LINES):
            flow = abs(ac.line_p_from_mw[i]) if has_ac else 0.0
            loading_frac = (ac.line_loading_pct[i] / 100.0) if has_ac else 0.0
            tripped = i in self._tripped_lines
            if tripped:
                status = "tripped"
            elif loading_frac > 0.90:
                status = "critical"
            elif loading_frac > 0.70:
                status = "warning"
            else:
                status = "normal"
            lines.append(LineState(
                id=f"ri.city-grid.main.transmission-line.{i}",
                flow_mw=round(flow, 2),
                flow_pct_of_limit=round(min(loading_frac, 9.99), 4),
                status=status,
                tripped=tripped,
                voltage_kv=ln.voltage_kv,
            ))

        # --- transformers -------------------------------------------------
        transformers: list[TransformerState] = []
        for i, xf in enumerate(TRANSFORMERS):
            loading = ac.trafo_loading_pct[i] if has_ac else 0.0
            tripped = i in self._tripped_trafos
            if tripped:
                status = "tripped"
            elif loading > 90.0:
                status = "critical"
            elif loading > 70.0:
                status = "warning"
            else:
                status = "normal"
            transformers.append(TransformerState(
                id=f"ri.city-grid.main.transformer.{i}",
                loading_pct=round(loading, 2),
                from_bus=xf.from_bus,
                to_bus=xf.to_bus,
                status=status,
            ))

        # --- generators ---------------------------------------------------
        generators: list[GeneratorState] = []
        for gen in self._generators:
            d = gen.to_dict()
            extra = {k: v for k, v in d.items() if k not in _CORE_GEN_KEYS}
            generators.append(GeneratorState(
                bus_id=gen.bus_id,
                gen_type=gen.gen_type,
                rotor_angle_deg=round(math.degrees(gen.rotor_angle_rad), 4),
                rotor_speed_rad_s=round(gen.rotor_speed_rad_s, 6),
                mechanical_power_mw=round(gen.p_mech_mw, 2),
                electrical_power_mw=round(gen.p_electrical_mw, 2),
                capacity_mw=gen.capacity_mw,
                online=gen.online,
                extra=extra,
            ))

        # --- aggregates ---------------------------------------------------
        freq = self._system_frequency()
        total_gen = sum(g.p_electrical_mw for g in self._generators if g.online)
        total_load = sum(self._p_load.values())
        total_loss = ac.total_loss_mw if has_ac else 0.0

        # --- alerts -------------------------------------------------------
        alerts: list[dict] = self._build_alerts(freq, has_ac, ac)

        ontology_dirty = bool(
            self._tripped_lines
            or self._tripped_trafos
            or any(not g.online for g in self._generators)
        )

        return GridState(
            sim_time_s=round(self._sim_time, 4),
            wall_time=datetime.now(timezone.utc).isoformat(),
            system_frequency_hz=round(freq, 4),
            total_generation_mw=round(total_gen, 2),
            total_load_mw=round(total_load, 2),
            total_loss_mw=round(total_loss, 2),
            buses=buses,
            lines=lines,
            transformers=transformers,
            generators=generators,
            active_alerts=alerts,
            ontology_dirty=ontology_dirty,
        )

    def _build_alerts(
        self,
        freq: float,
        has_ac: bool,
        ac: Optional[ACResult],
    ) -> list[dict]:
        alerts: list[dict] = []

        # Frequency
        if freq < 49.5:
            alerts.append({"level": "critical", "msg": f"Under-frequency: {freq:.2f} Hz"})
        elif freq < 49.8:
            alerts.append({"level": "warning", "msg": f"Low frequency: {freq:.2f} Hz"})
        if freq > 50.5:
            alerts.append({"level": "critical", "msg": f"Over-frequency: {freq:.2f} Hz"})
        elif freq > 50.2:
            alerts.append({"level": "warning", "msg": f"High frequency: {freq:.2f} Hz"})

        # Tripped elements
        for idx in sorted(self._tripped_lines):
            alerts.append({"level": "warning", "msg": f"Line {idx} tripped"})
        for idx in sorted(self._tripped_trafos):
            alerts.append({"level": "warning", "msg": f"Transformer {idx} tripped"})

        # Overloads
        if has_ac and ac is not None:
            for i in range(len(LINES)):
                if ac.line_loading_pct[i] > 90.0 and i not in self._tripped_lines:
                    alerts.append({
                        "level": "critical",
                        "msg": f"Line {i} overloaded: {ac.line_loading_pct[i]:.1f}%",
                    })
            for i in range(len(TRANSFORMERS)):
                if ac.trafo_loading_pct[i] > 90.0 and i not in self._tripped_trafos:
                    alerts.append({
                        "level": "critical",
                        "msg": f"Transformer {i} overloaded: {ac.trafo_loading_pct[i]:.1f}%",
                    })

        # Offline generators
        for gen in self._generators:
            if not gen.online:
                alerts.append({
                    "level": "warning",
                    "msg": f"Generator at bus {gen.bus_id} ({gen.gen_type}) offline",
                })

        # Convergence failure
        if not has_ac:
            alerts.append({"level": "critical", "msg": "Power flow did not converge"})

        return alerts

    # ------------------------------------------------------------------
    # Fault injection
    # ------------------------------------------------------------------

    def trip_line(self, line_idx: int) -> None:
        if 0 <= line_idx < len(LINES):
            self._tripped_lines.add(line_idx)

    def trip_transformer(self, trafo_idx: int) -> None:
        if 0 <= trafo_idx < len(TRANSFORMERS):
            self._tripped_trafos.add(trafo_idx)

    def gen_dropout(self, bus_id: int) -> None:
        for gen in self._generators:
            if gen.bus_id == bus_id and gen.online:
                gen.trip()

    def load_spike(self, bus_id: int, magnitude_mw: float) -> None:
        if bus_id in self._p_load:
            self._p_load[bus_id] += magnitude_mw

    def set_gen_setpoint(self, bus_id: int, target_mw: float) -> None:
        for gen in self._generators:
            if gen.bus_id == bus_id:
                gen.set_setpoint(target_mw)

    def restore(self) -> None:
        """Reset every element back to its initial conditions."""
        self._tripped_lines.clear()
        self._tripped_trafos.clear()
        self._p_load = {b.id: b.p_load_mw for b in BUSES}
        for gen in self._generators:
            gen.restore()
        self._powerflow.reset()
        self._solve_and_sync()
        for gen in self._generators:
            gen.p_mech_mw = gen.p_electrical_mw
            gen._initial_p_mech = gen.p_electrical_mw

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sim_time(self) -> float:
        return self._sim_time

    @property
    def generators(self) -> list[GeneratorModel]:
        return self._generators
