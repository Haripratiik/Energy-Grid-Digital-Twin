"""Tests for WLS state estimation and bad-data detection."""

from __future__ import annotations

import pandapower.networks as nw
import pytest

from physics.lodf import DCSystem
from physics.state_estimation import DCStateEstimator


@pytest.fixture(scope="module")
def est14():
    return DCStateEstimator(DCSystem.from_pandapower(nw.case14()))


@pytest.fixture(scope="module")
def est118():
    return DCStateEstimator(DCSystem.from_pandapower(nw.case118()))


def test_measurement_set_is_redundant(est14):
    assert est14.n_meas > est14.ns          # more measurements than states
    assert est14.n_meas / est14.ns > 1.5


def test_recovers_state_under_noise(est118):
    z, sigma = est118.simulate_measurements(noise_pu=0.02, seed=3)
    r = est118.estimate(z, sigma)
    # Estimated angles are close to truth, well under the radian scale.
    assert r.angle_rmse_rad < 0.05


def test_redundancy_denoises_flows(est118):
    """A redundant estimate is more accurate than the raw measurements."""
    z, sigma = est118.simulate_measurements(noise_pu=0.02, seed=3)
    r = est118.estimate(z, sigma)
    assert r.flow_rmse_pu < r.measurement_noise_pu


def test_clean_measurements_pass_chi2(est118):
    z, sigma = est118.simulate_measurements(noise_pu=0.02, seed=3)
    r = est118.estimate(z, sigma)
    assert not r.bad_data_detected
    assert r.objective_j < r.chi2_threshold
    assert r.flagged_measurement is None


def test_detects_gross_error(est118):
    z, sigma = est118.simulate_measurements(noise_pu=0.02, seed=3, bad_index=50, bad_error_pu=0.6)
    r = est118.estimate(z, sigma)
    assert r.bad_data_detected
    assert r.objective_j > r.chi2_threshold


def test_localizes_gross_error(est118):
    bad_idx = 77
    z, sigma = est118.simulate_measurements(noise_pu=0.02, seed=5, bad_index=bad_idx, bad_error_pu=0.6)
    r = est118.estimate(z, sigma)
    assert r.flagged_measurement == bad_idx
    assert r.max_normalized_residual > 3.0


def test_works_on_small_system(est14):
    z, sigma = est14.simulate_measurements(noise_pu=0.01, seed=0)
    r = est14.estimate(z, sigma)
    assert not r.bad_data_detected
    assert r.angle_rmse_rad < 0.05
