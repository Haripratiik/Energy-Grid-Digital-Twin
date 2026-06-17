"""Fast N-1 contingency screening via PTDF / LODF distribution factors.

Brute-force N-1 screening re-solves a power flow for every single-element
outage — O(N) linear solves. The linearized (DC) alternative precomputes two
sensitivity matrices once:

* **PTDF** (Power Transfer Distribution Factors) — how a bus injection
  distributes across branches.
* **LODF** (Line Outage Distribution Factors) — how the flow on the outaged
  branch redistributes to every other branch.

Then *all* single-branch-outage flows follow from a single vectorised operation

    F_post = f₀[:, None] + LODF · diag(f₀)          (every column = one outage)

turning N power-flow solves into one matrix expression. This is the standard
control-room screening technique and it scales to thousands of buses.

LODF is *exact* for the DC model — it agrees with brute-force re-solves to
machine precision (validated in the tests).
"""

from __future__ import annotations

import numpy as np
import pandapower as pp
from pydantic import BaseModel

# pypower ppc column indices (avoid importing pypower constants).
_BUS_I, _BUS_TYPE, _PD = 0, 1, 2
_BR_F, _BR_T, _BR_X = 0, 1, 3
_GEN_BUS, _GEN_PG = 0, 1
_REF = 3


class ScreeningResult(BaseModel):
    n_branches: int
    n_valid_contingencies: int     # excludes outages that island the network
    n_radial: int
    worst_branch_outage: int
    worst_resulting_flow_pu: float


class DCSystem:
    """DC network with precomputed PTDF/LODF for instant N-1 line screening."""

    def __init__(self, n_bus, f_idx, t_idx, b_branch, slack, injections, base_mva):
        self.n = n_bus
        self.f = np.asarray(f_idx)
        self.t = np.asarray(t_idx)
        self.b = np.asarray(b_branch, dtype=float)
        self.L = len(self.b)
        self.slack = slack
        self.base_mva = base_mva
        self.P = np.asarray(injections, dtype=float)
        self._build()

    def _build(self) -> None:
        L, n = self.L, self.n
        A = np.zeros((L, n))
        A[np.arange(L), self.f] = 1.0
        A[np.arange(L), self.t] = -1.0
        self.A = A

        B = A.T @ (self.b[:, None] * A)
        keep = [i for i in range(n) if i != self.slack]
        self._keep = keep
        Bri = np.linalg.inv(B[np.ix_(keep, keep)])

        # PTDF (L x n): branch flow sensitivity to bus injection (slack reference).
        PTDF = np.zeros((L, n))
        PTDF[:, keep] = self.b[:, None] * (A[:, keep] @ Bri)
        self.PTDF = PTDF

        # LODF (L x L): LODF[k, l] = redistribution onto k when l is outaged.
        d = PTDF[:, self.f] - PTDF[:, self.t]      # d[k, l]
        self._denom = 1.0 - np.diag(d)             # ~0 ⇒ outage islands the network
        self.radial = np.abs(self._denom) < 1e-9
        denom_safe = np.where(self.radial, 1.0, self._denom)
        LODF = d / denom_safe[None, :]
        np.fill_diagonal(LODF, -1.0)
        LODF[:, self.radial] = 0.0                 # undefined for radial outages
        self.LODF = LODF

        # Base-case DC flows (pu).
        theta = np.zeros(n)
        theta[keep] = Bri @ self.P[keep]
        self.base_flow = self.b * (A @ theta)

    # -- screening ---------------------------------------------------------

    def screen_all_line_outages(self) -> np.ndarray:
        """Post-contingency branch flows for *every* single-branch outage.

        Returns an (L, L) array; column ``l`` holds the flows on all branches
        after branch ``l`` is removed. One vectorised matrix expression.
        """
        f0 = self.base_flow
        return f0[:, None] + self.LODF * f0[None, :]

    def brute_force_outage(self, l: int) -> np.ndarray:
        """Re-solve DC with branch ``l`` removed (reference for validation).

        Radial outages island the network (singular reduced B); they aren't a
        flow-redistribution contingency, so we return the base flows for them.
        """
        if self.radial[l]:
            return self.base_flow.copy()
        b = self.b.copy()
        b[l] = 0.0
        B = self.A.T @ (b[:, None] * self.A)
        keep = self._keep
        theta = np.zeros(self.n)
        theta[keep] = np.linalg.solve(B[np.ix_(keep, keep)], self.P[keep])
        return b * (self.A @ theta)

    def screening_summary(self) -> ScreeningResult:
        F = self.screen_all_line_outages()
        valid = ~self.radial
        # Worst resulting flow ignores the outaged branch's own (zero) flow.
        Fmag = np.abs(F).copy()
        Fmag[np.arange(self.L), np.arange(self.L)] = 0.0
        Fmag[:, self.radial] = 0.0
        worst_per_outage = Fmag.max(axis=0)
        worst = int(np.argmax(worst_per_outage))
        return ScreeningResult(
            n_branches=self.L,
            n_valid_contingencies=int(valid.sum()),
            n_radial=int(self.radial.sum()),
            worst_branch_outage=worst,
            worst_resulting_flow_pu=round(float(worst_per_outage[worst]), 4),
        )

    # -- construction ------------------------------------------------------

    @classmethod
    def from_pandapower(cls, net) -> "DCSystem":
        pp.rundcpp(net)
        ppc = net._ppc
        bus = ppc["bus"].real
        br = ppc["branch"].real
        gen = ppc["gen"].real

        busnum = bus[:, _BUS_I].astype(int)
        idx = {b: i for i, b in enumerate(busnum)}
        n = len(busnum)
        base = net.sn_mva

        f = np.array([idx[int(row[_BR_F])] for row in br])
        t = np.array([idx[int(row[_BR_T])] for row in br])
        b = 1.0 / br[:, _BR_X]
        slack = int(np.where(bus[:, _BUS_TYPE] == _REF)[0][0])

        P = np.zeros(n)
        for g in gen:
            P[idx[int(g[_GEN_BUS])]] += g[_GEN_PG] / base
        P -= bus[:, _PD] / base

        return cls(n, f, t, b, slack, P, base)
