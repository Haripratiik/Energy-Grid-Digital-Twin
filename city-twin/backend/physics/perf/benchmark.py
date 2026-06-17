"""Scaling benchmark: LODF screening vs brute-force N-1, up to ~2900 buses.

Demonstrates the headline performance result — replacing N power-flow solves
with one vectorised matrix expression — and how it scales. Run:

    python -m physics.perf.benchmark
    python -m physics.perf.benchmark --jax     # also time a JAX-jitted screen
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandapower.networks as nw
from pydantic import BaseModel

from physics.lodf import DCSystem

_CASES = [
    ("IEEE-118", nw.case118),
    ("case300", nw.case300),
    ("case1354pegase", nw.case1354pegase),
    ("case2869pegase", nw.case2869pegase),
]


class BenchRow(BaseModel):
    case: str
    n_bus: int
    n_branch: int
    build_ms: float            # one-time PTDF/LODF construction
    lodf_screen_ms: float      # screen ALL contingencies (vectorised)
    bruteforce_ms: float       # N separate DC re-solves (projected for large cases)
    bruteforce_projected: bool
    speedup: float
    contingencies_per_s: float
    max_error_pu: float        # LODF vs brute force on the sampled outages


def _bruteforce_sample(dc: DCSystem, sample: int) -> tuple[float, float]:
    """Time brute-force re-solves on up to ``sample`` non-radial outages.

    Returns (mean ms per outage, max LODF-vs-bruteforce error over the sample).
    """
    F_lodf = dc.screen_all_line_outages()
    cols = [l for l in range(dc.L) if not dc.radial[l]][:sample]
    t = time.perf_counter()
    max_err = 0.0
    for l in cols:
        f_bf = dc.brute_force_outage(l)
        max_err = max(max_err, float(np.max(np.abs(F_lodf[:, l] - f_bf))))
    per_outage_ms = (time.perf_counter() - t) / max(len(cols), 1) * 1e3
    return per_outage_ms, max_err


def benchmark_case(label: str, loader, *, brute_sample: int = 250) -> BenchRow:
    net = loader()

    t = time.perf_counter()
    dc = DCSystem.from_pandapower(net)
    build_ms = (time.perf_counter() - t) * 1e3

    dc.screen_all_line_outages()                  # warm
    t = time.perf_counter()
    dc.screen_all_line_outages()
    lodf_ms = (time.perf_counter() - t) * 1e3

    per_outage_ms, max_err = _bruteforce_sample(dc, brute_sample)
    projected = dc.L > brute_sample
    bf_ms = per_outage_ms * dc.L                  # full brute-force (projected if sampled)

    speedup = bf_ms / lodf_ms if lodf_ms > 0 else float("inf")
    cps = dc.L / (lodf_ms / 1e3) if lodf_ms > 0 else float("inf")
    return BenchRow(
        case=label, n_bus=dc.n, n_branch=dc.L,
        build_ms=round(build_ms, 2), lodf_screen_ms=round(lodf_ms, 4),
        bruteforce_ms=round(bf_ms, 1), bruteforce_projected=projected,
        speedup=round(speedup, 1), contingencies_per_s=round(cps, 0),
        max_error_pu=max_err,
    )


def _jax_screen_time(dc: DCSystem) -> float:
    """Time a JAX-jitted screen (build + elementwise), if JAX is installed."""
    import jax
    import jax.numpy as jnp

    LODF = jnp.asarray(dc.LODF)
    f0 = jnp.asarray(dc.base_flow)

    @jax.jit
    def screen(LODF, f0):
        return f0[:, None] + LODF * f0[None, :]

    screen(LODF, f0).block_until_ready()          # compile
    t = time.perf_counter()
    for _ in range(50):
        screen(LODF, f0).block_until_ready()
    return (time.perf_counter() - t) / 50 * 1e3


def _print_table(rows: list[BenchRow]) -> None:
    print(f"\n{'case':<16}{'bus':>6}{'branch':>8}{'build(ms)':>11}"
          f"{'LODF(ms)':>10}{'brute(ms)':>11}{'speedup':>9}{'screen/s':>11}{'err':>10}")
    print("-" * 92)
    for r in rows:
        bf = f"{r.bruteforce_ms:.0f}{'*' if r.bruteforce_projected else ''}"
        print(f"{r.case:<16}{r.n_bus:>6}{r.n_branch:>8}{r.build_ms:>11.2f}"
              f"{r.lodf_screen_ms:>10.4f}{bf:>11}{r.speedup:>8.0f}x"
              f"{r.contingencies_per_s:>11.0f}{r.max_error_pu:>10.1e}")
    print("  (* brute-force time projected from a sample of outages)")


def main() -> None:
    ap = argparse.ArgumentParser(description="LODF N-1 screening scaling benchmark")
    ap.add_argument("--jax", action="store_true", help="also time a JAX-jitted screen")
    args = ap.parse_args()

    print("N-1 contingency screening: LODF (vectorised) vs brute-force re-solves")
    rows = [benchmark_case(lbl, fn) for lbl, fn in _CASES]
    _print_table(rows)
    print(f"\nLODF agrees with brute force to "
          f"{max(r.max_error_pu for r in rows):.1e} pu (machine precision).")

    if args.jax:
        print("\nJAX-jitted screen (per call):")
        for lbl, fn in _CASES:
            dc = DCSystem.from_pandapower(fn())
            try:
                jms = _jax_screen_time(dc)
                print(f"  {lbl:<16} {jms:.4f} ms  ({dc.L} contingencies)")
            except ImportError:
                print("  [jax not installed]")
                break


if __name__ == "__main__":
    main()
