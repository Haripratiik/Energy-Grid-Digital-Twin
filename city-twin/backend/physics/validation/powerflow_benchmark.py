"""Validate AC power flow against the standard IEEE benchmark systems.

For each case we establish correctness three independent ways:

1. **Cross-solver agreement** — Newton-Raphson and fast-decoupled (two
   mathematically independent algorithms) must converge to the *same* bus
   voltages. Since the power-flow solution near flat start is unique, agreement
   to ~1e-8 proves the solution is the correct one.
2. **Nodal power conservation** — total generation must equal total load plus
   network losses to numerical precision.
3. **Published loss reference** — total active-power losses must match the
   literature value for the case (where well-established).
"""

from __future__ import annotations

import numpy as np
import pandapower as pp
import pandapower.networks as nw
from pydantic import BaseModel

# (loader, label, n_bus, published total active loss MW or None, tolerance MW)
_CASES = [
    (nw.case9, "IEEE-9", 9, 4.95, 0.15),
    (nw.case14, "IEEE-14", 14, 13.39, 0.25),
    (nw.case30, "IEEE-30", 30, None, None),
    (nw.case57, "IEEE-57", 57, None, None),
    (nw.case118, "IEEE-118", 118, 133.0, 2.5),
]


class PowerFlowValidation(BaseModel):
    case: str
    n_bus: int
    converged: bool
    max_dvm_pu: float          # NR vs fast-decoupled, voltage magnitude
    max_dva_deg: float         # NR vs fast-decoupled, voltage angle
    conservation_residual_mw: float
    total_loss_mw: float
    published_loss_mw: float | None
    loss_error_mw: float | None
    passed: bool


def _solve(net, algorithm: str):
    pp.runpp(net, algorithm=algorithm, calculate_voltage_angles=True)
    return net.res_bus.vm_pu.values.copy(), net.res_bus.va_degree.values.copy()


def validate_powerflow(
    *, vm_tol: float = 1e-6, va_tol: float = 1e-4, cons_tol: float = 1e-4,
) -> list[PowerFlowValidation]:
    results: list[PowerFlowValidation] = []
    for loader, label, n_bus, pub_loss, loss_tol in _CASES:
        net = loader()
        vm_nr, va_nr = _solve(net, "nr")
        converged = bool(net["converged"])

        net2 = loader()
        vm_fd, va_fd = _solve(net2, "fdbx")

        max_dvm = float(np.max(np.abs(vm_nr - vm_fd)))
        max_dva = float(np.max(np.abs(va_nr - va_fd)))

        gen = (net.res_gen.p_mw.sum() + net.res_ext_grid.p_mw.sum()
               + net.res_sgen.p_mw.sum())
        load = net.res_load.p_mw.sum()
        loss = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum())
        conservation = float(abs(gen - load - loss))

        loss_err = None if pub_loss is None else abs(loss - pub_loss)

        passed = (
            converged
            and max_dvm < vm_tol and max_dva < va_tol
            and conservation < cons_tol
            and (loss_err is None or loss_err < loss_tol)
        )
        results.append(PowerFlowValidation(
            case=label, n_bus=n_bus, converged=converged,
            max_dvm_pu=max_dvm, max_dva_deg=max_dva,
            conservation_residual_mw=conservation, total_loss_mw=round(loss, 3),
            published_loss_mw=pub_loss,
            loss_error_mw=None if loss_err is None else round(loss_err, 3),
            passed=passed,
        ))
    return results


def _print_table(results: list[PowerFlowValidation]) -> None:
    print(f"\n{'case':<10}{'bus':>5}{'NRvsFD dVm':>13}{'dVa(deg)':>11}"
          f"{'conserv(MW)':>13}{'loss(MW)':>10}{'pub(MW)':>9}{'pass':>6}")
    print("-" * 77)
    for r in results:
        pub = "-" if r.published_loss_mw is None else f"{r.published_loss_mw:.1f}"
        print(f"{r.case:<10}{r.n_bus:>5}{r.max_dvm_pu:>13.2e}{r.max_dva_deg:>11.2e}"
              f"{r.conservation_residual_mw:>13.2e}{r.total_loss_mw:>10.2f}{pub:>9}"
              f"{('OK' if r.passed else 'FAIL'):>6}")


if __name__ == "__main__":
    res = validate_powerflow()
    print("AC power-flow validation against IEEE benchmark systems")
    _print_table(res)
    print(f"\n{sum(r.passed for r in res)}/{len(res)} cases passed.")
