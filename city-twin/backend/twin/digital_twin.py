"""The digital-twin synchronization loop.

A **physical plant** (ground-truth multi-machine dynamics + process noise) is
never directly observed. A **twin** receives only noisy, partial angle
measurements (PMU-like) and tracks the plant's full dynamic state — rotor angles
*and* unmeasured speeds — with an Unscented Kalman Filter whose process model is
the same swing dynamics. The loop demonstrates the three things a digital twin
must do: synchronize from a wrong initial guess, stay locked through transients,
and detect when reality diverges from the model.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel

from physics.classical_model import ClassicalMultiMachine
from .ukf import UnscentedKalmanFilter


@dataclass
class TwinConfig:
    dt: float = 0.01                      # estimator/sensor step (s)
    process_noise_omega: float = 4e-3     # plant unmodeled disturbance on speed (rad/s)
    meas_noise_angle: float = 0.01        # PMU-grade angle noise (rad, ~0.6°)
    measured_machines: tuple[int, ...] = (0, 1, 2)   # which rotor angles are sensed
    init_angle_error: float = 0.20        # how wrong the twin starts (rad)
    excite_perturbation: float = 0.20     # initial plant disturbance (rad)
    seed: int = 0


class TwinStep(BaseModel):
    t: float
    angle_rmse: float       # twin angle estimate vs plant truth
    speed_rmse: float       # twin speed estimate vs plant truth (UNMEASURED)
    nis: float              # normalized innovation squared (anomaly score)
    anomaly_active: bool


class TwinSummary(BaseModel):
    n_steps: int
    n_measured: int
    n_states: int
    converged_angle_rmse: float    # mean RMSE after lock-in
    converged_speed_rmse: float
    initial_angle_rmse: float
    nis_baseline_mean: float       # NIS before any anomaly
    nis_anomaly_peak: float        # peak NIS after anomaly
    anomaly_detected: bool


class DigitalTwin:
    def __init__(self, cfg: TwinConfig | None = None) -> None:
        self.cfg = cfg or TwinConfig()
        self.plant = ClassicalMultiMachine.from_ieee9()
        self.twin_model = copy.deepcopy(self.plant)     # twin's belief of the dynamics
        self.m = self.plant.m
        self.rng = np.random.default_rng(self.cfg.seed)

        # Ground-truth plant state, perturbed to excite an oscillation.
        self.x_true = self.plant.equilibrium_state().copy()
        self.x_true[1] += self.cfg.excite_perturbation

        n = 2 * self.m
        q = np.full(n, 1e-8)
        q[self.m:] = self.cfg.process_noise_omega ** 2
        self.meas_idx = np.array(self.cfg.measured_machines, dtype=int)
        R = np.eye(len(self.meas_idx)) * self.cfg.meas_noise_angle ** 2
        self.ukf = UnscentedKalmanFilter(n, np.diag(q), R)

        # Twin starts at equilibrium with a deliberate angle error.
        x0 = self.plant.equilibrium_state().copy()
        x0[: self.m] += self.cfg.init_angle_error
        self.ukf.x = x0
        self.ukf.P = np.eye(n) * 0.5

        self._t = 0.0
        self._anomaly = False

    def _h(self, x: np.ndarray) -> np.ndarray:
        return x[self.meas_idx]                          # measured rotor angles

    def inject_anomaly(self, machine: int = 1, delta_pm: float = 0.4) -> None:
        """Reality diverges from the twin's model: a step in plant mechanical
        power the twin does not know about (e.g. a governor/prime-mover event)."""
        self.plant.Pm = self.plant.Pm.copy()
        self.plant.Pm[machine] += delta_pm
        self._anomaly = True

    def step(self) -> TwinStep:
        dt = self.cfg.dt
        # 1. advance the physical plant (truth) + process noise on speeds
        self.x_true = self.plant.step_rk4(self.x_true, dt)
        self.x_true[self.m:] += self.rng.normal(0, self.cfg.process_noise_omega, self.m)
        # 2. sensors: noisy, partial angle measurements
        z = self._h(self.x_true) + self.rng.normal(0, self.cfg.meas_noise_angle, len(self.meas_idx))
        # 3. twin: UKF predict (model) + update (measurement)
        self.ukf.predict(lambda x: self.twin_model.step_rk4(x, dt))
        innovation = self.ukf.update(z, self._h)
        nis = self.ukf.normalized_innovation_sq(innovation)

        self._t += dt
        est = self.ukf.x
        ang_rmse = float(np.sqrt(np.mean((est[: self.m] - self.x_true[: self.m]) ** 2)))
        spd_rmse = float(np.sqrt(np.mean((est[self.m:] - self.x_true[self.m:]) ** 2)))
        return TwinStep(t=round(self._t, 4), angle_rmse=ang_rmse, speed_rmse=spd_rmse,
                        nis=nis, anomaly_active=self._anomaly)

    def run(self, n_steps: int = 800, anomaly_step: int | None = None) -> tuple[list[TwinStep], TwinSummary]:
        steps: list[TwinStep] = []
        for k in range(n_steps):
            if anomaly_step is not None and k == anomaly_step:
                self.inject_anomaly()
            steps.append(self.step())

        lock = max(1, n_steps // 5)            # allow the filter to converge
        pre = [s for s in steps if not s.anomaly_active]
        post = [s for s in steps if s.anomaly_active]
        nis_baseline = float(np.mean([s.nis for s in pre[lock:]])) if len(pre) > lock else float(np.mean([s.nis for s in pre]))
        nis_peak = float(max((s.nis for s in post), default=0.0))

        return steps, TwinSummary(
            n_steps=n_steps, n_measured=len(self.meas_idx), n_states=2 * self.m,
            converged_angle_rmse=round(float(np.mean([s.angle_rmse for s in pre[lock:]])), 5),
            converged_speed_rmse=round(float(np.mean([s.speed_rmse for s in pre[lock:]])), 5),
            initial_angle_rmse=round(steps[0].angle_rmse, 5),
            nis_baseline_mean=round(nis_baseline, 3),
            nis_anomaly_peak=round(nis_peak, 3),
            anomaly_detected=(nis_peak > 5.0 * max(nis_baseline, 1e-6)) if post else False,
        )
