"""Physics safety verification for proposed control actions.

"AI proposes, physics guarantees safety." Before any action — whether from the
LLM reasoning engine, the rule-based autonomous engine, or a learned controller —
is executed on the grid, it is re-checked here: the action's effect is applied to
a *copy* of the operating point and the AC power flow is re-solved. The action is
rejected if it fails to converge (voltage collapse / islanding) or makes the grid
*less* secure (introduces or worsens limit violations).

The learned/heuristic layer provides speed and proposals; this deterministic
power-flow check provides the safety guarantee, on its own decoupled solver so it
never perturbs the live simulator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from physics.ac_powerflow import ACPowerFlow
from physics.network import BUSES, LINES, TRANSFORMERS

if TYPE_CHECKING:
    from physics.swing import GridState
    from .models import ProposedAction

V_MIN, V_MAX = 0.90, 1.10
THERMAL_PCT = 100.0


class VerificationResult(BaseModel):
    safe: bool
    reason: str
    converged: bool
    pre_severity: float
    post_severity: float
    pre_violations: int
    post_violations: int
    worst_voltage_pu: Optional[float] = None
    worst_loading_pct: Optional[float] = None


def _parse_idx(rid: str) -> int:
    return int(rid.rsplit(".", 1)[-1])


class SafetyVerifier:
    """Re-solves AC power flow to confirm a proposed action keeps the grid secure."""

    def __init__(self) -> None:
        self._pf = ACPowerFlow()        # private, decoupled from the live sim

    # -- operating point from live state ----------------------------------

    @staticmethod
    def _operating_point(state: "GridState"):
        gen_p = {g.bus_id: max(0.0, g.mechanical_power_mw)
                 for g in state.generators if g.online}
        load_p = {b.id: b.power_load_mw for b in state.buses if b.power_load_mw > 0}
        tl = {i for i, ln in enumerate(state.lines) if ln.tripped}
        tt = {i for i, xf in enumerate(state.transformers) if xf.status == "tripped"}
        return gen_p, load_p, tl, tt

    def _apply_action(self, action: "ProposedAction", gen_p, load_p, tl, tt):
        """Return a NEW operating point with the action applied (copies)."""
        gen_p, load_p, tl, tt = dict(gen_p), dict(load_p), set(tl), set(tt)
        a = action.action_type
        params = action.parameters or {}
        try:
            if a == "GEN_SETPOINT":
                bus = _parse_idx(action.target_rid)
                if "target_mw" in params:
                    gen_p[bus] = max(0.0, float(params["target_mw"]))
                else:
                    delta = float(params.get("delta_mw", action.estimated_impact_mw or 0.0))
                    gen_p[bus] = max(0.0, gen_p.get(bus, 0.0) + delta)
            elif a == "LOAD_SHED":
                bus = _parse_idx(action.target_rid)
                shed = abs(float(params.get("delta_mw", action.estimated_impact_mw or 0.0)))
                if bus in load_p:
                    load_p[bus] = max(0.0, load_p[bus] - shed)
            elif a in ("LINE_SWITCH", "ISLANDING"):
                tl.add(_parse_idx(action.target_rid))
            elif a == "TRANSFORMER_TAP":
                tt.add(_parse_idx(action.target_rid))
        except (ValueError, KeyError):
            pass
        return gen_p, load_p, tl, tt

    # -- security scoring --------------------------------------------------

    def _score(self, gen_p, load_p, tl, tt):
        res = self._pf.solve(gen_p_mw=gen_p, load_p_mw=load_p,
                             tripped_lines=tl, tripped_trafos=tt)
        if not res.converged:
            return False, 1e6, 1, None, None
        severity, n_viol = 0.0, 0
        worst_v = 1.0
        for vm in res.bus_vm_pu:
            if vm < V_MIN:
                severity += (V_MIN - vm) * 300.0
                n_viol += 1
            elif vm > V_MAX:
                severity += (vm - V_MAX) * 300.0
                n_viol += 1
            if abs(vm - 1.0) > abs(worst_v - 1.0):
                worst_v = float(vm)
        worst_load = 0.0
        for i, pct in enumerate(res.line_loading_pct):
            if i not in tl:
                worst_load = max(worst_load, float(pct))
                if pct > THERMAL_PCT:
                    severity += pct - THERMAL_PCT
                    n_viol += 1
        for i, pct in enumerate(res.trafo_loading_pct):
            if i not in tt:
                worst_load = max(worst_load, float(pct))
                if pct > THERMAL_PCT:
                    severity += pct - THERMAL_PCT
                    n_viol += 1
        return True, severity, n_viol, worst_v, worst_load

    # -- public API --------------------------------------------------------

    def verify(self, state: "GridState", action: "ProposedAction",
               *, tolerance: float = 1.0) -> VerificationResult:
        """Check that ``action`` keeps the grid secure relative to the current state."""
        gen_p, load_p, tl, tt = self._operating_point(state)
        pre_ok, pre_sev, pre_n, _, _ = self._score(gen_p, load_p, tl, tt)

        g2, l2, tl2, tt2 = self._apply_action(action, gen_p, load_p, tl, tt)
        post_ok, post_sev, post_n, worst_v, worst_load = self._score(g2, l2, tl2, tt2)

        if not post_ok:
            return VerificationResult(
                safe=False, reason="Post-action power flow did not converge — "
                "likely voltage collapse or islanding.",
                converged=False, pre_severity=round(pre_sev, 2), post_severity=1e6,
                pre_violations=pre_n, post_violations=post_n,
            )
        if post_sev > pre_sev + tolerance:
            reason = (f"Action worsens security (severity {pre_sev:.1f} → {post_sev:.1f}); "
                      f"{post_n} post-action violations.")
            safe = False
        else:
            reason = (f"Verified: grid stays secure (severity {pre_sev:.1f} → {post_sev:.1f}, "
                      f"{post_n} violations).")
            safe = True
        return VerificationResult(
            safe=safe, reason=reason, converged=True,
            pre_severity=round(pre_sev, 2), post_severity=round(post_sev, 2),
            pre_violations=pre_n, post_violations=post_n,
            worst_voltage_pu=round(worst_v, 4) if worst_v is not None else None,
            worst_loading_pct=round(worst_load, 1) if worst_load is not None else None,
        )
