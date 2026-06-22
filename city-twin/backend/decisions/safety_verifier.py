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

import threading
from typing import TYPE_CHECKING, Optional

import numpy as np
from pydantic import BaseModel

from physics.ac_powerflow import ACPowerFlow

if TYPE_CHECKING:
    from physics.swing import GridState
    from .models import ProposedAction

V_MIN, V_MAX = 0.90, 1.10
THERMAL_PCT = 100.0
# The N-1 gate rejects an action that makes the worst single-contingency outcome
# materially worse — i.e. introduces a new near-collapse (severity jumps toward
# W_NON_CONVERGED). 100 is the empirically-validated floor: because the inline
# screen AC-verifies only the worst few contingencies, the pre/post "worst" are
# taken over slightly different subsets, and a tolerance below ~100 trips that
# screening noise on benign actions (research/verifier_eval.py measured 5%+
# false-rejects at 50, vs 0 false-accept / 0 false-reject at 100). A count-based
# gate fared far worse (>50% false-accept), so peak-severity @ 100 it is.
N1_SEV_TOLERANCE = 100.0


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
    # Second physics gate: does the action keep the grid N-1 secure (robust to
    # the *next* single failure), not just secure right now?
    n1_checked: bool = False
    n1_secure: bool = True
    n1_pre_insecure: int = 0
    n1_post_insecure: int = 0
    n1_worst: Optional[str] = None


def _parse_idx(rid: str) -> int:
    return int(rid.rsplit(".", 1)[-1])


class SafetyVerifier:
    """Re-solves AC power flow to confirm a proposed action keeps the grid secure."""

    def __init__(self) -> None:
        self._pf = ACPowerFlow()        # private, decoupled from the live sim
        self._n1 = None                 # N-1 analyzer, created on first use
        # verify() mutates the private pandapower net in place and pp.runpp
        # releases the GIL, so concurrent calls (e.g. /verify-action on a worker
        # thread while the engine verifies on the loop) would corrupt the solve.
        self._lock = threading.Lock()

    def _n1_analyzer(self):
        if self._n1 is None:
            from physics.contingency import ContingencyAnalyzer
            self._n1 = ContingencyAnalyzer(ac_verify_k=8)
        return self._n1

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
        """Return ``(applied, gen_p, load_p, tl, tt)`` with the action applied to copies.

        ``applied`` is ``False`` when the action cannot actually be modelled —
        an unknown action type, or a malformed target RID / parameters. The
        caller then **fails closed** rather than certifying as "safe" an action
        the verifier never evaluated (a silent no-op used to read as secure).
        """
        gen_p, load_p, tl, tt = dict(gen_p), dict(load_p), set(tl), set(tt)
        a = action.action_type
        params = action.parameters or {}
        try:
            if a == "GEN_SETPOINT":
                bus = _parse_idx(action.target_rid)
                # Mirror ActionExecutor's target resolution exactly so the verifier
                # checks the action that will actually run (not a different one).
                if "target_mw" in params:
                    target = float(params["target_mw"])
                elif "delta_mw" in params:
                    target = gen_p.get(bus, 0.0) + float(params["delta_mw"])
                else:
                    target = gen_p.get(bus, 0.0) + abs(float(action.estimated_impact_mw or 20.0))
                gen_p[bus] = max(0.0, target)
            elif a == "LOAD_SHED":
                bus = _parse_idx(action.target_rid)
                # Nothing to shed at a bus with no load — the verifier would model a
                # no-op, but the executor still injects (negative load). Fail closed.
                if bus not in load_p:
                    return False, gen_p, load_p, tl, tt
                shed = abs(float(params.get("delta_mw", action.estimated_impact_mw or 0.0)))
                load_p[bus] = max(0.0, load_p[bus] - shed)
            elif a in ("LINE_SWITCH", "ISLANDING"):
                tl.add(_parse_idx(action.target_rid))
            elif a == "TRANSFORMER_TAP":
                tt.add(_parse_idx(action.target_rid))
            else:
                return False, gen_p, load_p, tl, tt
        except (ValueError, KeyError, TypeError):
            return False, gen_p, load_p, tl, tt
        return True, gen_p, load_p, tl, tt

    # -- security scoring --------------------------------------------------

    def _score(self, gen_p, load_p, tl, tt):
        res = self._pf.solve(gen_p_mw=gen_p, load_p_mw=load_p,
                             tripped_lines=tl, tripped_trafos=tt)
        # Treat a non-converged OR NaN/inf solution as a collapse: every threshold
        # comparison below is False for NaN, so an islanded/garbage result would
        # otherwise score 0 severity / 0 violations and pass as perfectly secure.
        if not res.converged or not (
            np.all(np.isfinite(res.bus_vm_pu))
            and np.all(np.isfinite(res.line_loading_pct))
            and np.all(np.isfinite(res.trafo_loading_pct))
        ):
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
               *, tolerance: float = 1.0, check_n1: bool = False) -> VerificationResult:
        """Check that ``action`` keeps the grid secure relative to the current state.

        Two physics gates: (1) the post-action AC power flow must converge and not
        be materially less secure than now; (2) optionally, the action must not
        leave the grid *more* exposed to the next single failure (N-1).

        Serialised per verifier instance — the private pandapower net is mutated
        in place, so concurrent calls must not interleave.
        """
        with self._lock:
            return self._verify(state, action, tolerance=tolerance, check_n1=check_n1)

    def _verify(self, state: "GridState", action: "ProposedAction",
                *, tolerance: float, check_n1: bool) -> VerificationResult:
        gen_p, load_p, tl, tt = self._operating_point(state)
        pre_ok, pre_sev, pre_n, _, _ = self._score(gen_p, load_p, tl, tt)

        applied, g2, l2, tl2, tt2 = self._apply_action(action, gen_p, load_p, tl, tt)
        if not applied:
            return VerificationResult(
                safe=False,
                reason=(f"Action '{action.action_type}' on {action.target_rid} could not "
                        "be modelled by the verifier — rejected (fail-closed)."),
                converged=pre_ok, pre_severity=round(pre_sev, 2),
                post_severity=round(pre_sev, 2),
                pre_violations=pre_n, post_violations=pre_n,
            )
        post_ok, post_sev, post_n, worst_v, worst_load = self._score(g2, l2, tl2, tt2)

        if not post_ok:
            return VerificationResult(
                safe=False, reason="Post-action power flow did not converge — "
                "likely voltage collapse or islanding.",
                converged=False, pre_severity=round(pre_sev, 2), post_severity=1e6,
                pre_violations=pre_n, post_violations=post_n,
            )

        base_safe = post_sev <= pre_sev + tolerance

        # -- second gate: N-1 security of the post-action grid ----------------
        n1 = dict(n1_checked=False, n1_secure=True, n1_pre_insecure=0,
                  n1_post_insecure=0, n1_worst=None)
        if check_n1:
            try:
                pre_ins, pre_worst_sev, _ = self._n1_analyzer().screen_operating_point(
                    gen_p, load_p, tl, tt)
                post_ins, post_worst_sev, post_worst = self._n1_analyzer().screen_operating_point(
                    g2, l2, tl2, tt2)
                # Gate on the worst single-contingency severity only. A count-based
                # gate (post_insecure > pre_insecure) was measured to be unreliable
                # here: it needs to see *every* contingency, but this inline screen
                # AC-verifies only the worst few, so it undercounts and waves through
                # >50% of unsafe actions (see research/verifier_eval.py). The worst-
                # severity jump, by contrast, is screening-robust — a new near-collapse
                # ranks top in the DC screen and is always AC-verified.
                n1_secure = post_worst_sev <= pre_worst_sev + N1_SEV_TOLERANCE
                n1 = dict(n1_checked=True, n1_secure=n1_secure,
                          n1_pre_insecure=pre_ins, n1_post_insecure=post_ins,
                          n1_worst=post_worst if not n1_secure else None)
            except Exception:  # noqa: BLE001 — N-1 is a best-effort second gate
                n1["n1_checked"] = False

        safe = base_safe and n1["n1_secure"]
        steady = f"steady-state severity {pre_sev:.1f} → {post_sev:.1f}"
        if not base_safe:
            reason = f"Rejected: action worsens security ({steady}; {post_n} violations)."
        elif not n1["n1_secure"]:
            extra = f" (worst: loss of {n1['n1_worst']})" if n1["n1_worst"] else ""
            reason = (f"Rejected: action leaves the grid N-1 insecure — "
                      f"{n1['n1_post_insecure']} exposed contingencies{extra}. {steady}.")
        elif n1["n1_checked"]:
            reason = f"Verified secure: {steady}; N-1 secure ({n1['n1_post_insecure']} exposed)."
        else:
            reason = f"Verified secure: {steady}; {post_n} violations."

        return VerificationResult(
            safe=safe, reason=reason, converged=True,
            pre_severity=round(pre_sev, 2), post_severity=round(post_sev, 2),
            pre_violations=pre_n, post_violations=post_n,
            worst_voltage_pu=round(worst_v, 4) if worst_v is not None else None,
            worst_loading_pct=round(worst_load, 1) if worst_load is not None else None,
            **n1,
        )
