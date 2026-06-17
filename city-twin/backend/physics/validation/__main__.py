"""Run the full physics validation report:  python -m physics.validation"""

from __future__ import annotations

from .powerflow_benchmark import validate_powerflow, _print_table
from .dynamics_benchmark import validate_smib, validate_governor


def main() -> None:
    print("=" * 78)
    print("PHYSICS VALIDATION REPORT")
    print("=" * 78)

    print("\n[1] AC power flow vs IEEE benchmark systems")
    pf = validate_powerflow()
    _print_table(pf)
    print(f"  -> {sum(r.passed for r in pf)}/{len(pf)} cases passed")

    print("\n[2] Swing-equation small-signal dynamics (single-machine-infinite-bus)")
    smib = validate_smib()
    print(f"  K_s={smib.synchronizing_coeff}  analytic T={smib.analytic_period_s}s  "
          f"simulated T={smib.simulated_period_s}s  error={smib.rel_error*100:.3f}%  "
          f"-> {'PASS' if smib.passed else 'FAIL'}")

    print("\n[3] Turbine-governor primary frequency control")
    gov = validate_governor()
    print(f"  {gov.disturbance}: Δf {gov.deviation_ungoverned_hz} Hz -> "
          f"{gov.deviation_governed_hz} Hz; governors picked up "
          f"{gov.primary_response_mw} MW  -> {'PASS' if gov.passed else 'FAIL'}")

    all_pass = all(r.passed for r in pf) and smib.passed and gov.passed
    print("\n" + "=" * 78)
    print(f"OVERALL: {'ALL VALIDATIONS PASSED' if all_pass else 'SOME VALIDATIONS FAILED'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
