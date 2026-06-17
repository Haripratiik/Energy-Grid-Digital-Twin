"""Physics validation tests — benchmark power flow and analytical dynamics."""

from __future__ import annotations

import math

import pytest

from physics.validation.powerflow_benchmark import validate_powerflow
from physics.validation.dynamics_benchmark import validate_governor, validate_smib


# --- AC power flow vs IEEE benchmarks -------------------------------------

@pytest.fixture(scope="module")
def pf_results():
    return validate_powerflow()


def test_all_ieee_cases_validate(pf_results):
    assert pf_results, "no cases run"
    for r in pf_results:
        assert r.passed, f"{r.case} failed validation"


def test_independent_solvers_agree(pf_results):
    """Newton-Raphson and fast-decoupled converge to the same voltages."""
    for r in pf_results:
        assert r.max_dvm_pu < 1e-6, f"{r.case} Vm disagreement {r.max_dvm_pu}"
        assert r.max_dva_deg < 1e-4, f"{r.case} Va disagreement {r.max_dva_deg}"


def test_power_is_conserved(pf_results):
    for r in pf_results:
        assert r.conservation_residual_mw < 1e-3, f"{r.case} not conserving power"


def test_losses_match_published_values(pf_results):
    """Where a reference loss is known, the computed loss must match it."""
    checked = [r for r in pf_results if r.published_loss_mw is not None]
    assert checked, "expected at least one referenced case"
    for r in checked:
        assert r.loss_error_mw is not None and r.loss_error_mw < 2.5, (
            f"{r.case} loss {r.total_loss_mw} vs published {r.published_loss_mw}"
        )


# --- swing dynamics vs analytical theory ----------------------------------

def test_smib_oscillation_matches_analytic_eigenvalue():
    r = validate_smib()
    assert r.passed
    assert r.rel_error < 0.02, f"period error {r.rel_error}"


def test_smib_period_scales_with_sqrt_inertia():
    """ω_n = √(K_s/M) ⇒ doubling inertia scales the period by √2."""
    base = validate_smib(M=10.0)
    heavy = validate_smib(M=20.0)
    ratio = heavy.simulated_period_s / base.simulated_period_s
    assert ratio == pytest.approx(math.sqrt(2), rel=0.02)


def test_governor_provides_primary_frequency_response():
    r = validate_governor(post_ticks=1500)
    assert r.passed
    assert r.primary_response_mw > 0, "governors should pick up load"
    assert r.deviation_governed_hz < r.deviation_ungoverned_hz
