"""Digital-twin demonstration:  python -m twin.demo

Runs the plant/twin synchronization loop and prints what a digital twin must do:
lock onto a noisy physical plant, reconstruct unmeasured states, stay consistent,
and flag when reality diverges from the model.
"""

from __future__ import annotations

from .digital_twin import DigitalTwin, TwinConfig


def _series(steps, every: int) -> None:
    print(f"  {'t(s)':>6}{'angleRMSE':>12}{'speedRMSE':>12}{'NIS':>10}{'':>4}")
    for s in steps[::every]:
        flag = "  <-- ANOMALY" if s.anomaly_active else ""
        print(f"  {s.t:>6.2f}{s.angle_rmse:>12.5f}{s.speed_rmse:>12.5f}{s.nis:>10.2f}{flag}")


def main() -> None:
    print("=" * 70)
    print("DIGITAL TWIN — UKF synchronization to a noisy physical plant")
    print("=" * 70)

    print("\n[1] Full observability (3 of 3 rotor angles sensed), anomaly at t=5s")
    twin = DigitalTwin(TwinConfig())
    steps, summary = twin.run(n_steps=800, anomaly_step=500)
    _series(steps, every=80)
    print(f"\n  initial angle RMSE : {summary.initial_angle_rmse} rad")
    print(f"  converged angle RMSE: {summary.converged_angle_rmse} rad "
          f"(sensor noise was {twin.cfg.meas_noise_angle} rad — filter denoises)")
    print(f"  unmeasured-speed RMSE: {summary.converged_speed_rmse} rad/s "
          f"(speeds are never measured — reconstructed from the model)")
    print(f"  NIS baseline {summary.nis_baseline_mean} (~#measurements ⇒ consistent), "
          f"peak {summary.nis_anomaly_peak} after anomaly")
    print(f"  anomaly detected: {summary.anomaly_detected}")

    print("\n[2] Partial observability (only 2 of 3 angles sensed)")
    twin2 = DigitalTwin(TwinConfig(measured_machines=(0, 2)))
    _, s2 = twin2.run(n_steps=800)
    print(f"  converged angle RMSE: {s2.converged_angle_rmse} rad  "
          f"speed RMSE: {s2.converged_speed_rmse} rad/s")
    print("  -> the twin still tracks the unsensed machine and all speeds.")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
