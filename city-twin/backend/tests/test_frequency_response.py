"""Tests for system frequency response, inertia, and grid-forming inverters."""

from __future__ import annotations

import pytest

from physics.frequency_response import (
    FrequencyResponseModel,
    compare_inertia_scenarios,
)


def test_initial_rocof_matches_analytic():
    """Initial RoCoF must equal the textbook −ΔP/(2H)·f₀."""
    for h in (2.0, 4.0, 6.0):
        r = FrequencyResponseModel(h_sync=h).analyze_step(0.1)
        assert r.rocof_error_pct < 1.0


def test_lower_inertia_gives_steeper_rocof_and_deeper_nadir():
    high = FrequencyResponseModel(h_sync=6.0).analyze_step(0.12)
    low = FrequencyResponseModel(h_sync=2.0).analyze_step(0.12)
    assert low.rocof_hz_s > high.rocof_hz_s
    assert low.nadir_hz < high.nadir_hz


def test_low_inertia_breaches_rocof_limit():
    low = FrequencyResponseModel(h_sync=2.0).analyze_step(0.12)
    high = FrequencyResponseModel(h_sync=6.0).analyze_step(0.12)
    assert low.breaches_rocof_limit
    assert not high.breaches_rocof_limit


def test_grid_forming_restores_stability():
    """Virtual inertia + fast droop cut RoCoF and lift the nadir."""
    low = FrequencyResponseModel(h_sync=2.0).analyze_step(0.12)
    gfm = FrequencyResponseModel(h_sync=2.0, h_gfm=2.5, gfm_droop=8.0).analyze_step(0.12)
    assert gfm.rocof_hz_s < low.rocof_hz_s
    assert gfm.nadir_hz > low.nadir_hz
    assert not gfm.breaches_rocof_limit


def test_governor_recovers_from_nadir():
    r = FrequencyResponseModel(h_sync=4.0).analyze_step(0.1)
    # Primary control lifts frequency back up from the nadir toward a droop offset.
    assert r.settling_hz > r.nadir_hz
    assert r.settling_hz < 60.0          # but a steady-state offset remains


def test_compare_scenarios_shape():
    rows = compare_inertia_scenarios()
    assert len(rows) == 3
    # The grid-forming scenario has the most total inertia of the three.
    assert rows[2].total_inertia_h > rows[1].total_inertia_h
