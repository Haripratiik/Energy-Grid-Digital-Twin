"""pandapower Newton-Raphson AC power-flow wrapper for the 80-bus city network.

Builds a pandapower ``pandapowerNet`` from the frozen dataclass topology in
:pymod:`network` and exposes a single :pymeth:`solve` entry-point that
accepts dynamic generator dispatches, load updates, and topological outages.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandapower as pp

from .network import (
    BASE_MVA,
    BUS_INDEX,
    BUSES,
    GENERATORS_CONFIG,
    LINES,
    NOMINAL_FREQ_HZ,
    NUM_BUSES,
    SLACK_BUS,
    TRANSFORMERS,
)

log = logging.getLogger(__name__)

_GEN_CFG_BY_BUS: dict[int, dict] = {g["bus_id"]: g for g in GENERATORS_CONFIG}


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ACResult:
    """Snapshot of a single AC power-flow solution."""

    bus_vm_pu: np.ndarray
    bus_va_deg: np.ndarray
    line_p_from_mw: np.ndarray
    line_loading_pct: np.ndarray
    trafo_loading_pct: np.ndarray
    total_loss_mw: float
    converged: bool


# ---------------------------------------------------------------------------
# Power-flow engine
# ---------------------------------------------------------------------------

class ACPowerFlow:
    """Build an 80-bus pandapower network and solve Newton-Raphson AC PF.

    The pandapower bus indices are created in the same order as the ``BUSES``
    tuple, so ``BUS_INDEX[bus_id]`` maps directly to the pandapower row index.
    """

    _DEFAULT_QP_RATIO = 0.30

    def __init__(self) -> None:
        self._pp_bus: dict[int, int] = {}
        self._pp_gen: dict[int, tuple[str, int]] = {}
        self._pp_load: dict[int, int] = {}
        self._load_qp_ratio: dict[int, float] = {}
        self._net = self._build_net()

    # ------------------------------------------------------------------
    # Network construction
    # ------------------------------------------------------------------

    def _build_net(self) -> pp.pandapowerNet:
        net = pp.create_empty_network(
            name="city-80bus", f_hz=float(NOMINAL_FREQ_HZ), sn_mva=float(BASE_MVA),
        )

        pp_bus: dict[int, int] = {}
        pp_gen: dict[int, tuple[str, int]] = {}
        pp_load: dict[int, int] = {}
        load_qp: dict[int, float] = {}

        # --- buses --------------------------------------------------------
        for bus in BUSES:
            pp_bus[bus.id] = pp.create_bus(
                net, vn_kv=bus.voltage_kv, name=bus.name,
            )

        # --- lines (per-unit on system base → physical) -------------------
        for line_def in LINES:
            z_base = line_def.voltage_kv ** 2 / BASE_MVA
            scale = 0.15 if line_def.voltage_kv <= 33.0 else (0.5 if line_def.voltage_kv <= 132.0 else 1.0)
            pp.create_line_from_parameters(
                net,
                from_bus=pp_bus[line_def.from_bus],
                to_bus=pp_bus[line_def.to_bus],
                length_km=1.0,
                r_ohm_per_km=line_def.r_pu * z_base * scale,
                x_ohm_per_km=line_def.x_pu * z_base * scale,
                c_nf_per_km=0.0,
                max_i_ka=line_def.limit_mw * 3.0 / (math.sqrt(3) * line_def.voltage_kv),
            )

        # --- transformers (per-unit values are on the transformer's own base)
        for xfmr in TRANSFORMERS:
            tap_pos = round((xfmr.tap_ratio - 1.0) * 100.0)
            sn_mva = xfmr.rating_mva * 1.5
            pp.create_transformer_from_parameters(
                net,
                hv_bus=pp_bus[xfmr.from_bus],
                lv_bus=pp_bus[xfmr.to_bus],
                sn_mva=sn_mva,
                vn_hv_kv=xfmr.from_kv,
                vn_lv_kv=xfmr.to_kv,
                vkr_percent=xfmr.r_pu * 100.0,
                vk_percent=math.hypot(xfmr.r_pu, xfmr.x_pu) * 100.0,
                pfe_kw=0.0,
                i0_percent=0.0,
                tap_side="hv",
                tap_neutral=0,
                tap_step_percent=1.0,
                tap_pos=tap_pos,
            )

        # --- generators ---------------------------------------------------
        for cfg in GENERATORS_CONFIG:
            bid = cfg["bus_id"]
            bus = BUSES[BUS_INDEX[bid]]
            pb = pp_bus[bid]

            if bid == SLACK_BUS:
                idx = pp.create_gen(
                    net, pb,
                    p_mw=cfg["p_mech_mw"],
                    vm_pu=bus.v_setpoint_pu,
                    slack=True,
                    name=f"gen_{cfg['gen_type']}_{bid}",
                )
                pp_gen[bid] = ("gen", idx)
            elif cfg["inertia_M"] > 0:
                idx = pp.create_gen(
                    net, pb,
                    p_mw=cfg["p_mech_mw"],
                    vm_pu=bus.v_setpoint_pu,
                    slack=False,
                    name=f"gen_{cfg['gen_type']}_{bid}",
                )
                pp_gen[bid] = ("gen", idx)
            else:
                idx = pp.create_sgen(
                    net, pb,
                    p_mw=cfg["p_mech_mw"],
                    q_mvar=0.0,
                    name=f"sgen_{cfg['gen_type']}_{bid}",
                )
                pp_gen[bid] = ("sgen", idx)

        # --- loads (one per bus so dynamic load_spike always has a target) -
        for bus in BUSES:
            idx = pp.create_load(
                net, pp_bus[bus.id],
                p_mw=bus.p_load_mw,
                q_mvar=bus.q_load_mvar,
                name=f"load_{bus.id}",
            )
            pp_load[bus.id] = idx
            if bus.p_load_mw > 0:
                load_qp[bus.id] = bus.q_load_mvar / bus.p_load_mw
            else:
                load_qp[bus.id] = self._DEFAULT_QP_RATIO

        # --- shunt capacitors at key 33kV buses for voltage support --------
        for bus in BUSES:
            if bus.voltage_kv <= 33.0 and bus.p_load_mw >= 20.0:
                pp.create_shunt(
                    net, pp_bus[bus.id],
                    q_mvar=-bus.q_load_mvar * 0.8,
                    p_mw=0.0,
                )

        self._pp_bus = pp_bus
        self._pp_gen = pp_gen
        self._pp_load = pp_load
        self._load_qp_ratio = load_qp
        return net

    # ------------------------------------------------------------------
    # Solver
    # ------------------------------------------------------------------

    def solve(
        self,
        gen_p_mw: dict[int, float] | None = None,
        load_p_mw: dict[int, float] | None = None,
        tripped_lines: set[int] | None = None,
        tripped_trafos: set[int] | None = None,
    ) -> ACResult:
        """Run Newton-Raphson AC power flow with optional dynamic overrides.

        Parameters
        ----------
        gen_p_mw:
            Bus-id → active-power dispatch (MW).  Generators whose bus_id is
            **not** present are taken out of service.
        load_p_mw:
            Bus-id → active-power demand (MW).  Reactive power is computed
            from the original Q/P ratio to maintain the power factor.  Loads
            whose bus_id is **not** present are deactivated.
        tripped_lines:
            Set of line indices (into ``LINES``) to mark out-of-service.
        tripped_trafos:
            Set of transformer indices (into ``TRANSFORMERS``) to mark
            out-of-service.
        """
        net = self._net

        # Generator dispatch -----------------------------------------------
        if gen_p_mw is not None:
            for bid, (etype, pidx) in self._pp_gen.items():
                tbl = net.gen if etype == "gen" else net.sgen
                if bid in gen_p_mw:
                    tbl.at[pidx, "in_service"] = True
                    tbl.at[pidx, "p_mw"] = gen_p_mw[bid]
                else:
                    tbl.at[pidx, "in_service"] = False

        # Load update (maintain power factor) ------------------------------
        if load_p_mw is not None:
            for bid, pidx in self._pp_load.items():
                if bid in load_p_mw:
                    p = load_p_mw[bid]
                    net.load.at[pidx, "in_service"] = True
                    net.load.at[pidx, "p_mw"] = p
                    net.load.at[pidx, "q_mvar"] = (
                        p * self._load_qp_ratio.get(bid, self._DEFAULT_QP_RATIO)
                    )
                else:
                    net.load.at[pidx, "in_service"] = False

        # Topological outages ----------------------------------------------
        net.line["in_service"] = True
        net.trafo["in_service"] = True
        if tripped_lines:
            for idx in tripped_lines:
                if 0 <= idx < len(net.line):
                    net.line.at[idx, "in_service"] = False
        if tripped_trafos:
            for idx in tripped_trafos:
                if 0 <= idx < len(net.trafo):
                    net.trafo.at[idx, "in_service"] = False

        # Newton-Raphson solve (with fallback strategies) --------------------
        converged = False
        for algo, init, max_iter in [
            ("nr", "dc", 30),
            ("nr", "flat", 60),
            ("iwamoto_nr", "flat", 100),
            ("gs", "flat", 3000),
        ]:
            try:
                pp.runpp(net, algorithm=algo, init=init,
                         max_iteration=max_iter, enforce_q_lims=False)
                converged = True
                break
            except Exception:
                continue
        if not converged:
            log.warning("AC power flow did not converge with any solver")
            return self._non_converged_result()

        return ACResult(
            bus_vm_pu=net.res_bus.vm_pu.values.copy(),
            bus_va_deg=net.res_bus.va_degree.values.copy(),
            line_p_from_mw=net.res_line.p_from_mw.values.copy(),
            line_loading_pct=net.res_line.loading_percent.values.copy(),
            trafo_loading_pct=net.res_trafo.loading_percent.values.copy(),
            total_loss_mw=float(
                net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()
            ),
            converged=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _non_converged_result(self) -> ACResult:
        return ACResult(
            bus_vm_pu=np.ones(NUM_BUSES),
            bus_va_deg=np.zeros(NUM_BUSES),
            line_p_from_mw=np.zeros(len(LINES)),
            line_loading_pct=np.zeros(len(LINES)),
            trafo_loading_pct=np.zeros(len(TRANSFORMERS)),
            total_loss_mw=0.0,
            converged=False,
        )

    def reset(self) -> None:
        """Rebuild the network from scratch."""
        self._net = self._build_net()
