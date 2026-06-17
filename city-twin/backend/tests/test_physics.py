"""Physics sanity tests: power flow, frequency dynamics, energy balance, restore.

These pin the simulator's qualitative behaviour so a refactor that breaks the
physics is caught immediately, without asserting exact numeric values that
legitimately drift with model tuning.
"""

from __future__ import annotations

import random

import pytest

from physics.ac_powerflow import ACPowerFlow
from physics.network import GENERATORS_CONFIG, NOMINAL_FREQ_HZ, SLACK_BUS
from physics.swing import GridSimulator


def _steps(sim: GridSimulator, n: int):
    state = None
    for _ in range(n):
        s = sim.step()
        if s is not None:
            state = s
    return state


def test_powerflow_converges_at_nominal():
    pf = ACPowerFlow()
    gen_p = {g["bus_id"]: g["p_mech_mw"] for g in GENERATORS_CONFIG}
    from physics.network import BUSES
    load_p = {b.id: b.p_load_mw for b in BUSES if b.p_load_mw > 0}
    res = pf.solve(gen_p_mw=gen_p, load_p_mw=load_p)
    assert res.converged
    # All bus voltages should be within a sane band at the nominal operating point.
    assert res.bus_vm_pu.min() > 0.85
    assert res.bus_vm_pu.max() < 1.15


def test_initial_frequency_near_nominal():
    random.seed(0)
    sim = GridSimulator()
    state = _steps(sim, 25)
    assert abs(state.system_frequency_hz - NOMINAL_FREQ_HZ) < 0.5


def test_gen_dropout_reduces_frequency():
    random.seed(0)
    sim = GridSimulator()
    base = _steps(sim, 25)
    base_freq = base.system_frequency_hz

    # Trip the large gas peaker and let the swing dynamics respond.
    sim.gen_dropout(3)
    after = _steps(sim, 150)
    assert after.system_frequency_hz < base_freq, "frequency should fall after losing generation"


def test_energy_balance_holds():
    random.seed(0)
    sim = GridSimulator()
    state = _steps(sim, 25)
    # Generation must cover load plus network losses (power balance).
    imbalance = state.total_generation_mw - (state.total_load_mw + state.total_loss_mw)
    assert abs(imbalance) < 0.05 * state.total_load_mw


def test_restore_recovers_after_fault():
    random.seed(0)
    sim = GridSimulator()
    _steps(sim, 10)
    sim.gen_dropout(3)
    sim.trip_line(26)
    _steps(sim, 50)

    sim.restore()
    state = _steps(sim, 25)
    assert all(g.online for g in sim.generators)
    assert abs(state.system_frequency_hz - NOMINAL_FREQ_HZ) < 0.5


def test_slack_bus_generator_present():
    sim = GridSimulator()
    slack = [g for g in sim.generators if g.bus_id == SLACK_BUS]
    assert slack and slack[0].online
