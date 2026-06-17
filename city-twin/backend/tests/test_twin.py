"""Tests for the classical multi-machine model and the digital-twin UKF loop."""

from __future__ import annotations

import numpy as np
import pytest

from physics.classical_model import ClassicalMultiMachine
from twin.digital_twin import DigitalTwin, TwinConfig
from twin.ukf import UnscentedKalmanFilter


# --- classical multi-machine model ----------------------------------------

@pytest.fixture(scope="module")
def model():
    return ClassicalMultiMachine.from_ieee9()


def test_model_starts_in_equilibrium(model):
    x0 = model.equilibrium_state()
    assert np.max(np.abs(model.derivatives(x0))) < 1e-9


def test_mechanical_power_matches_ieee9_generation(model):
    # IEEE-9 generation ≈ [0.72, 1.63, 0.85] pu (72/163/85 MW).
    assert model.Pm == pytest.approx([0.716, 1.630, 0.85], abs=0.05)


def test_perturbation_oscillates_in_electromechanical_band(model):
    x = model.equilibrium_state().copy()
    x[1] += 0.1
    dt, n = 0.001, 6000
    rel = np.empty(n)
    for k in range(n):
        x = model.step_rk4(x, dt)
        rel[k] = x[1] - x[0]
    rel -= rel.mean()
    crossings = [k * dt for k in range(1, n) if rel[k - 1] < 0 <= rel[k]]
    period = (crossings[-1] - crossings[0]) / (len(crossings) - 1)
    freq = 1.0 / period
    assert 0.5 < freq < 2.5, f"electromechanical mode out of band: {freq} Hz"


def test_energy_bounded_under_damping(model):
    x = model.equilibrium_state().copy()
    x[1] += 0.1
    amp0 = abs(x[1] - x[0] - (model.delta0[1] - model.delta0[0]))
    for _ in range(8000):
        x = model.step_rk4(x, 0.001)
    amp1 = abs(x[1] - x[0] - (model.delta0[1] - model.delta0[0]))
    assert amp1 < amp0, "damped oscillation should decay"


# --- UKF unit sanity -------------------------------------------------------

def test_ukf_denoises_constant_signal():
    rng = np.random.default_rng(0)
    ukf = UnscentedKalmanFilter(1, Q=np.array([[1e-6]]), R=np.array([[0.25]]))
    ukf.x = np.array([0.0]); ukf.P = np.array([[1.0]])
    true = 3.0
    for _ in range(200):
        ukf.predict(lambda x: x)
        ukf.update(np.array([true + rng.normal(0, 0.5)]), lambda x: x)
    assert abs(ukf.x[0] - true) < 0.1   # well inside the 0.5 noise std


# --- digital-twin synchronization -----------------------------------------

@pytest.fixture(scope="module")
def full_obs():
    return DigitalTwin(TwinConfig()).run(n_steps=800, anomaly_step=500)


def test_twin_tracks_and_denoises(full_obs):
    _, s = full_obs
    # Estimate is more accurate than the raw sensor noise.
    assert s.converged_angle_rmse < TwinConfig().meas_noise_angle


def test_twin_recovers_unmeasured_speeds(full_obs):
    _, s = full_obs
    assert s.converged_speed_rmse < 0.05, "unmeasured rotor speeds should be reconstructed"


def test_twin_is_statistically_consistent(full_obs):
    _, s = full_obs
    # NIS ≈ number of measurements (3) when the model fits — bracket generously.
    assert 1.0 < s.nis_baseline_mean < 8.0


def test_twin_detects_anomaly(full_obs):
    _, s = full_obs
    assert s.anomaly_detected
    assert s.nis_anomaly_peak > 10 * s.nis_baseline_mean


def test_partial_observability_still_tracks():
    _, s = DigitalTwin(TwinConfig(measured_machines=(0, 2))).run(n_steps=800)
    assert s.n_measured == 2
    assert s.converged_angle_rmse < 0.05
    assert s.converged_speed_rmse < 0.1
