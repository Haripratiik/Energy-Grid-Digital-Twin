"""Tests for PTDF/LODF fast N-1 contingency screening."""

from __future__ import annotations

import time

import numpy as np
import pandapower.networks as nw
import pytest

from physics.lodf import DCSystem


@pytest.fixture(scope="module")
def dc14():
    return DCSystem.from_pandapower(nw.case14())


@pytest.fixture(scope="module")
def dc118():
    return DCSystem.from_pandapower(nw.case118())


def test_lodf_matches_bruteforce_exactly(dc14):
    """LODF is exact for the DC model — agrees with re-solves to machine eps."""
    F = dc14.screen_all_line_outages()
    for l in range(dc14.L):
        if dc14.radial[l]:
            continue
        assert np.max(np.abs(F[:, l] - dc14.brute_force_outage(l))) < 1e-9


def test_lodf_matches_bruteforce_large(dc118):
    F = dc118.screen_all_line_outages()
    max_err = 0.0
    for l in range(dc118.L):
        if dc118.radial[l]:
            continue
        max_err = max(max_err, np.max(np.abs(F[:, l] - dc118.brute_force_outage(l))))
    assert max_err < 1e-8


def test_lodf_diagonal_is_minus_one(dc14):
    # Outaging a branch removes its own flow: LODF[l, l] = -1.
    assert np.allclose(np.diag(dc14.LODF)[~dc14.radial], -1.0)


def test_screen_shape_and_summary(dc118):
    F = dc118.screen_all_line_outages()
    assert F.shape == (dc118.L, dc118.L)
    s = dc118.screening_summary()
    assert s.n_branches == dc118.L
    assert s.n_valid_contingencies + s.n_radial == dc118.L
    assert s.worst_resulting_flow_pu > 0


def test_base_flow_conserves_at_buses(dc14):
    # Net branch flow into each non-slack bus equals its injection (DC KCL).
    inflow = dc14.A.T @ dc14.base_flow
    keep = [i for i in range(dc14.n) if i != dc14.slack]
    assert np.allclose(inflow[keep], dc14.P[keep], atol=1e-9)


def test_vectorised_screen_is_faster_than_bruteforce(dc118):
    """The whole point: one matrix op beats N solves by a wide margin."""
    dc118.screen_all_line_outages()              # warm

    reps = 50
    t = time.perf_counter()
    for _ in range(reps):
        dc118.screen_all_line_outages()
    lodf_per = (time.perf_counter() - t) / reps

    t = time.perf_counter()
    for l in range(dc118.L):                     # all N brute-force solves
        dc118.brute_force_outage(l)
    brute_all = time.perf_counter() - t

    # One full vectorised screen must be far cheaper than N re-solves.
    assert lodf_per < brute_all / 10.0
