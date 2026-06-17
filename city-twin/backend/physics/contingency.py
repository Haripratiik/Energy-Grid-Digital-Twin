"""N-1 contingency analysis for the 80-bus city grid.

Real control rooms continuously ask the *security* question: "for every single
element that could fail right now, would the post-failure power flow violate any
limit?"  This module answers that for the live grid state.

Design
------
* **Fully decoupled & headless.**  The analyzer owns its *own* ``ACPowerFlow``
  network so it never mutates the live simulator's net (the two run on different
  threads).  Its only input is a :class:`GridState` snapshot, so the exact same
  code path is reusable offline for dataset generation / evaluation.
* **Two-stage screening for cost.**  Running full Newton-Raphson AC power flow
  for all ~124 single-element outages every cycle is too slow for the real-time
  loop.  We first *screen* every contingency with a fast linear DC power flow
  (thermal overloads only — DC has no voltage information), then *verify* the
  worst ``ac_verify_k`` screened cases plus every non-converging case with full
  AC to recover voltage violations.  This is standard utility practice.

The caller is expected to run :meth:`analyze` on a throttled cadence in a worker
thread, not inline in the 20 ms physics tick.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

import numpy as np
import pandapower as pp
from pydantic import BaseModel, Field

from .ac_powerflow import ACPowerFlow
from .network import BUSES, LINES, SLACK_BUS, TRANSFORMERS

if TYPE_CHECKING:
    from .swing import GridState

log = logging.getLogger(__name__)

# Operating limits (per-unit voltage band, % thermal loading).
V_MIN_PU = 0.90
V_MAX_PU = 1.10
THERMAL_LIMIT_PCT = 100.0

# Severity weights — tuned so a single collapse dominates any number of
# soft violations, and thermal overloads and voltage excursions are comparable.
W_NON_CONVERGED = 1000.0
W_THERMAL = 1.0      # per % over the thermal limit, summed across elements
W_VOLTAGE = 300.0    # per pu outside the band, summed across buses


class ContingencyKind(str, Enum):
    LINE = "LINE"
    TRANSFORMER = "TRANSFORMER"
    GENERATOR = "GENERATOR"


class ContingencyOutcome(str, Enum):
    SECURE = "SECURE"                  # no limit violated
    THERMAL_OVERLOAD = "THERMAL_OVERLOAD"
    VOLTAGE_VIOLATION = "VOLTAGE_VIOLATION"
    COLLAPSE = "COLLAPSE"              # power flow did not converge (islanding / voltage collapse)


class Violation(BaseModel):
    asset_rid: str
    kind: str          # "voltage" | "thermal"
    value: float       # vm_pu for voltage, loading_pct for thermal
    detail: str


class ContingencyResult(BaseModel):
    """Result of removing one element from the base case."""

    contingency_id: str            # e.g. "LINE-12" or "GEN-bus8"
    kind: ContingencyKind
    label: str                     # human-readable, e.g. "Line 12 (Bus 11→Bus 12, 132kV)"
    outcome: ContingencyOutcome
    severity: float
    converged: bool
    n_violations: int
    worst_voltage_pu: Optional[float] = None
    worst_loading_pct: Optional[float] = None
    violations: list[Violation] = Field(default_factory=list)


class ContingencyReport(BaseModel):
    base_secure: bool              # is the pre-contingency base case itself within limits?
    base_converged: bool
    n_screened: int
    n_ac_verified: int
    n_insecure: int                # contingencies with at least one violation or collapse
    worst: Optional[ContingencyResult] = None
    results: list[ContingencyResult] = Field(default_factory=list)


@dataclass
class _OperatingPoint:
    """The base case the contingency set is evaluated against."""

    gen_p_mw: dict[int, float]
    load_p_mw: dict[int, float]
    tripped_lines: set[int] = field(default_factory=set)
    tripped_trafos: set[int] = field(default_factory=set)


class ContingencyAnalyzer:
    """Runs N-1 contingency analysis against a snapshot of the grid."""

    def __init__(self, *, ac_verify_k: int = 12) -> None:
        # Private network — never shared with the live simulator.
        self._pf = ACPowerFlow()
        self._ac_verify_k = ac_verify_k

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, state: "GridState") -> ContingencyReport:
        """Run N-1 analysis against the operating point implied by ``state``."""
        op = self._operating_point(state)

        # --- base case ---------------------------------------------------
        base = self._pf.solve(
            gen_p_mw=op.gen_p_mw,
            load_p_mw=op.load_p_mw,
            tripped_lines=op.tripped_lines,
            tripped_trafos=op.tripped_trafos,
        )
        base_violations = self._collect_violations(base, op.tripped_lines, op.tripped_trafos)
        base_secure = base.converged and not base_violations

        candidates = self._candidates(op)

        # --- stage 1: DC screen (thermal) --------------------------------
        screen_scores = self._dc_screen(op, candidates)

        # --- stage 2: AC verify worst-K + every non-screenable case ------
        ranked = sorted(candidates, key=lambda c: screen_scores.get(c[0], 0.0), reverse=True)
        verify_set = {c[0] for c in ranked[: self._ac_verify_k]}
        # Always AC-verify generator outages (DC can't see their voltage impact).
        verify_set |= {cid for (cid, kind, _) in candidates if kind == ContingencyKind.GENERATOR}

        results: list[ContingencyResult] = []
        n_ac = 0
        for cid, kind, label in candidates:
            if cid in verify_set:
                results.append(self._ac_evaluate(op, cid, kind, label))
                n_ac += 1
            else:
                # Screened-only: DC found no overload → treat as secure.
                results.append(ContingencyResult(
                    contingency_id=cid,
                    kind=kind,
                    label=label,
                    outcome=ContingencyOutcome.SECURE,
                    severity=round(screen_scores.get(cid, 0.0) * W_THERMAL, 3),
                    converged=True,
                    n_violations=0,
                ))

        results.sort(key=lambda r: r.severity, reverse=True)
        insecure = [r for r in results if r.outcome != ContingencyOutcome.SECURE]

        return ContingencyReport(
            base_secure=base_secure,
            base_converged=base.converged,
            n_screened=len(candidates),
            n_ac_verified=n_ac,
            n_insecure=len(insecure),
            worst=results[0] if results and results[0].severity > 0 else None,
            results=results,
        )

    # ------------------------------------------------------------------
    # Operating point from live state
    # ------------------------------------------------------------------

    @staticmethod
    def _operating_point(state: "GridState") -> _OperatingPoint:
        gen_p = {
            g.bus_id: max(0.0, g.mechanical_power_mw)
            for g in state.generators
            if g.online
        }
        load_p = {b.id: b.power_load_mw for b in state.buses if b.power_load_mw > 0}

        tripped_lines: set[int] = set()
        for i, ln in enumerate(state.lines):
            if ln.tripped:
                tripped_lines.add(i)
        tripped_trafos: set[int] = set()
        for i, xf in enumerate(state.transformers):
            if xf.status == "tripped":
                tripped_trafos.add(i)

        return _OperatingPoint(gen_p, load_p, tripped_lines, tripped_trafos)

    # ------------------------------------------------------------------
    # Candidate enumeration
    # ------------------------------------------------------------------

    @staticmethod
    def _candidates(op: _OperatingPoint) -> list[tuple[str, ContingencyKind, str]]:
        """Every still-in-service element that could be the next single failure."""
        out: list[tuple[str, ContingencyKind, str]] = []

        for i, ln in enumerate(LINES):
            if i in op.tripped_lines:
                continue
            out.append((
                f"LINE-{i}", ContingencyKind.LINE,
                f"Line {i} (Bus {ln.from_bus}-Bus {ln.to_bus}, {ln.voltage_kv:.0f}kV)",
            ))

        for i, xf in enumerate(TRANSFORMERS):
            if i in op.tripped_trafos:
                continue
            out.append((
                f"TRAFO-{i}", ContingencyKind.TRANSFORMER,
                f"Transformer {i} (Bus {xf.from_bus}-Bus {xf.to_bus}, "
                f"{xf.from_kv:.0f}/{xf.to_kv:.0f}kV)",
            ))

        for bus_id in op.gen_p_mw:
            # The slack generator cannot be tripped in a single-slack model —
            # losing it is a different (re-dispatch) study, out of N-1 scope.
            if bus_id == SLACK_BUS:
                continue
            out.append((
                f"GEN-bus{bus_id}", ContingencyKind.GENERATOR,
                f"Generator at Bus {bus_id}",
            ))

        return out

    # ------------------------------------------------------------------
    # Stage 1 — fast DC screen
    # ------------------------------------------------------------------

    def _dc_screen(
        self,
        op: _OperatingPoint,
        candidates: list[tuple[str, ContingencyKind, str]],
    ) -> dict[str, float]:
        """Return a thermal-overload score per contingency from DC power flow.

        DC ignores voltage and reactive power, so it is fast but only flags
        thermal (MW) overloads — exactly what it's good for as a screen.
        Generator outages are not screened here (handled by mandatory AC verify).
        """
        scores: dict[str, float] = {}
        for cid, kind, _ in candidates:
            if kind == ContingencyKind.GENERATOR:
                continue
            tl = set(op.tripped_lines)
            tt = set(op.tripped_trafos)
            if kind == ContingencyKind.LINE:
                tl.add(int(cid.split("-")[1]))
            else:
                tt.add(int(cid.split("-")[1]))
            scores[cid] = self._dc_overload_score(op, tl, tt)
        return scores

    def _dc_overload_score(
        self,
        op: _OperatingPoint,
        tripped_lines: set[int],
        tripped_trafos: set[int],
    ) -> float:
        """Sum of thermal-limit excess (%) across all branches from a DC solve."""
        net = self._apply_topology(op, tripped_lines, tripped_trafos)
        try:
            pp.rundcpp(net)
        except Exception:
            # DC failed to solve → almost certainly islanded; flag as high.
            return 1e6
        score = 0.0
        if len(net.res_line):
            over = net.res_line.loading_percent.values - THERMAL_LIMIT_PCT
            score += float(np.clip(over, 0.0, None).sum())
        if len(net.res_trafo):
            over = net.res_trafo.loading_percent.values - THERMAL_LIMIT_PCT
            score += float(np.clip(over, 0.0, None).sum())
        return score

    # ------------------------------------------------------------------
    # Stage 2 — full AC verification of one contingency
    # ------------------------------------------------------------------

    def _ac_evaluate(
        self,
        op: _OperatingPoint,
        cid: str,
        kind: ContingencyKind,
        label: str,
    ) -> ContingencyResult:
        gen_p = dict(op.gen_p_mw)
        tl = set(op.tripped_lines)
        tt = set(op.tripped_trafos)
        if kind == ContingencyKind.LINE:
            tl.add(int(cid.split("-")[1]))
        elif kind == ContingencyKind.TRANSFORMER:
            tt.add(int(cid.split("-")[1]))
        else:  # GENERATOR
            gen_p.pop(int(cid.split("bus")[1]), None)

        res = self._pf.solve(gen_p_mw=gen_p, load_p_mw=op.load_p_mw,
                             tripped_lines=tl, tripped_trafos=tt)

        if not res.converged:
            return ContingencyResult(
                contingency_id=cid, kind=kind, label=label,
                outcome=ContingencyOutcome.COLLAPSE,
                severity=round(W_NON_CONVERGED, 3),
                converged=False, n_violations=1,
                violations=[Violation(
                    asset_rid=cid, kind="collapse", value=0.0,
                    detail="Power flow did not converge — likely islanding or voltage collapse",
                )],
            )

        violations = self._collect_violations(res, tl, tt)
        worst_v = self._worst_voltage(res)
        worst_l = self._worst_loading(res)
        severity = self._severity(res, tl, tt)

        if any(v.kind == "voltage" for v in violations):
            outcome = ContingencyOutcome.VOLTAGE_VIOLATION
        elif violations:
            outcome = ContingencyOutcome.THERMAL_OVERLOAD
        else:
            outcome = ContingencyOutcome.SECURE

        return ContingencyResult(
            contingency_id=cid, kind=kind, label=label,
            outcome=outcome, severity=round(severity, 3),
            converged=True, n_violations=len(violations),
            worst_voltage_pu=round(worst_v, 4) if worst_v is not None else None,
            worst_loading_pct=round(worst_l, 1) if worst_l is not None else None,
            violations=violations[:15],
        )

    # ------------------------------------------------------------------
    # Violation / severity helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_violations(res, tripped_lines: set[int], tripped_trafos: set[int]) -> list[Violation]:
        if not res.converged:
            return []
        out: list[Violation] = []
        for i, vm in enumerate(res.bus_vm_pu):
            if vm < V_MIN_PU or vm > V_MAX_PU:
                out.append(Violation(
                    asset_rid=f"ri.city-grid.main.bus.{BUSES[i].id}",
                    kind="voltage", value=round(float(vm), 4),
                    detail=f"Bus {BUSES[i].id} voltage {vm:.3f} pu outside [{V_MIN_PU}, {V_MAX_PU}]",
                ))
        for i, pct in enumerate(res.line_loading_pct):
            if i in tripped_lines:
                continue
            if pct > THERMAL_LIMIT_PCT:
                out.append(Violation(
                    asset_rid=f"ri.city-grid.main.transmission-line.{i}",
                    kind="thermal", value=round(float(pct), 1),
                    detail=f"Line {i} loaded to {pct:.0f}% of thermal limit",
                ))
        for i, pct in enumerate(res.trafo_loading_pct):
            if i in tripped_trafos:
                continue
            if pct > THERMAL_LIMIT_PCT:
                out.append(Violation(
                    asset_rid=f"ri.city-grid.main.transformer.{i}",
                    kind="thermal", value=round(float(pct), 1),
                    detail=f"Transformer {i} loaded to {pct:.0f}% of rating",
                ))
        return out

    @staticmethod
    def _severity(res, tripped_lines: set[int], tripped_trafos: set[int]) -> float:
        score = 0.0
        v_excess = 0.0
        for vm in res.bus_vm_pu:
            if vm < V_MIN_PU:
                v_excess += V_MIN_PU - vm
            elif vm > V_MAX_PU:
                v_excess += vm - V_MAX_PU
        score += W_VOLTAGE * v_excess

        thermal_excess = 0.0
        for i, pct in enumerate(res.line_loading_pct):
            if i not in tripped_lines and pct > THERMAL_LIMIT_PCT:
                thermal_excess += pct - THERMAL_LIMIT_PCT
        for i, pct in enumerate(res.trafo_loading_pct):
            if i not in tripped_trafos and pct > THERMAL_LIMIT_PCT:
                thermal_excess += pct - THERMAL_LIMIT_PCT
        score += W_THERMAL * thermal_excess
        return score

    @staticmethod
    def _worst_voltage(res) -> Optional[float]:
        if not len(res.bus_vm_pu):
            return None
        # Return the bus furthest from nominal (1.0 pu).
        idx = int(np.argmax(np.abs(res.bus_vm_pu - 1.0)))
        return float(res.bus_vm_pu[idx])

    @staticmethod
    def _worst_loading(res) -> Optional[float]:
        loadings = []
        if len(res.line_loading_pct):
            loadings.append(float(res.line_loading_pct.max()))
        if len(res.trafo_loading_pct):
            loadings.append(float(res.trafo_loading_pct.max()))
        return max(loadings) if loadings else None

    # ------------------------------------------------------------------
    # pandapower topology helper (mirrors ACPowerFlow.solve's outage handling)
    # ------------------------------------------------------------------

    def _apply_topology(self, op: _OperatingPoint, tripped_lines: set[int],
                        tripped_trafos: set[int]):
        """Set the private net's dispatch/load/topology for a DC screen."""
        net = self._pf._net
        for bid, (etype, pidx) in self._pf._pp_gen.items():
            tbl = net.gen if etype == "gen" else net.sgen
            if bid in op.gen_p_mw:
                tbl.at[pidx, "in_service"] = True
                tbl.at[pidx, "p_mw"] = op.gen_p_mw[bid]
            else:
                tbl.at[pidx, "in_service"] = False
        for bid, pidx in self._pf._pp_load.items():
            if bid in op.load_p_mw:
                net.load.at[pidx, "in_service"] = True
                net.load.at[pidx, "p_mw"] = op.load_p_mw[bid]
            else:
                net.load.at[pidx, "in_service"] = False
        net.line["in_service"] = True
        net.trafo["in_service"] = True
        for idx in tripped_lines:
            if 0 <= idx < len(net.line):
                net.line.at[idx, "in_service"] = False
        for idx in tripped_trafos:
            if 0 <= idx < len(net.trafo):
                net.trafo.at[idx, "in_service"] = False
        return net


# ---------------------------------------------------------------------------
# Headless CLI — `python -m physics.contingency`
# ---------------------------------------------------------------------------

def _main() -> None:
    """Run one N-1 sweep against the nominal equilibrium state and print it."""
    import time as _time

    from .swing import GridSimulator

    sim = GridSimulator()
    # Let the system settle a moment so the snapshot is a realistic operating point.
    for _ in range(25):
        sim.step()
    state = sim.get_state()

    analyzer = ContingencyAnalyzer()
    t0 = _time.perf_counter()
    report = analyzer.analyze(state)
    dt = _time.perf_counter() - t0

    print(f"N-1 sweep: {report.n_screened} contingencies, "
          f"{report.n_ac_verified} AC-verified, in {dt * 1000:.0f} ms")
    print(f"Base case secure: {report.base_secure} (converged={report.base_converged})")
    print(f"Insecure contingencies: {report.n_insecure}")
    print()
    print(f"{'rank':>4}  {'contingency':<14} {'outcome':<18} {'severity':>9}  detail")
    for i, r in enumerate(report.results[:15], 1):
        worst = ""
        if r.worst_voltage_pu is not None:
            worst = f"V={r.worst_voltage_pu:.3f}pu"
        if r.worst_loading_pct is not None:
            worst += f" load={r.worst_loading_pct:.0f}%"
        print(f"{i:>4}  {r.contingency_id:<14} {r.outcome.value:<18} "
              f"{r.severity:>9.1f}  {r.label}  {worst}")


if __name__ == "__main__":
    _main()
