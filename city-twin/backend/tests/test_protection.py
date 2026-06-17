"""Tests for inverse-time overload protection and emergent cascades."""

from __future__ import annotations

import math
import random

import pytest

from physics.protection import ProtectionSystem
from physics.swing import GridSimulator


# --- inverse-time characteristic ------------------------------------------

def test_trip_time_is_inverse_in_overload():
    p = ProtectionSystem(base_time_s=4.0, pickup_ratio=1.05)
    # Below pickup: never trips.
    assert math.isinf(p.trip_time_s(100.0))
    assert math.isinf(p.trip_time_s(104.0))
    # Heavier overload trips faster.
    t150 = p.trip_time_s(150.0)
    t200 = p.trip_time_s(200.0)
    t300 = p.trip_time_s(300.0)
    assert t150 > t200 > t300 > 0
    assert t200 == pytest.approx(4.0, rel=1e-6)   # base_time at 200%


def test_sustained_overload_trips_after_expected_delay():
    p = ProtectionSystem(base_time_s=4.0)
    dt = 0.1
    # 200% loading => trip_time 4 s => ~40 cycles of 0.1 s.
    tripped_at = None
    for step in range(1, 80):
        new_lines, _ = p.update([200.0], [], dt, set(), set(), sim_time_s=step * dt)
        if new_lines:
            tripped_at = step * dt
            break
    assert tripped_at is not None
    assert tripped_at == pytest.approx(4.0, abs=0.2)


def test_transient_overload_does_not_trip():
    p = ProtectionSystem(base_time_s=4.0)
    dt = 0.1
    # 2 s of overload (half the trip time) then it clears for a while.
    for _ in range(20):
        assert not p.update([200.0], [], dt, set(), set())[0]
    for _ in range(40):
        new_lines, _ = p.update([90.0], [], dt, set(), set())  # back to normal
        assert not new_lines
    # Credit must have decayed back to zero (relay reset).
    assert not p._credit_line


# --- emergent behaviour in the full simulator -----------------------------

def test_simulator_protection_disabled_by_default():
    sim = GridSimulator()
    assert sim._protection is None


def test_protection_trips_a_sustained_overload_in_simulator():
    random.seed(21)
    sim = GridSimulator(protection_enabled=True)
    # Trafo 17 trip drives a downstream branch to ~155% — a sustained overload.
    sim.trip_transformer(17)
    for _ in range(700):   # ~14 s, longer than the inverse-time delay at 155%
        sim.step()
    assert sim._protection.events, "relay should have tripped the overloaded branch"
    ev = sim._protection.events[0]
    assert ev.loading_pct > 105.0
    # The element it tripped is now out of service.
    if ev.kind == "line":
        assert ev.index in sim._tripped_lines
    else:
        assert ev.index in sim._tripped_trafos


def test_cascade_multiple_elements_trip_from_one_fault():
    """A stressed corridor with fast relays should cascade past the seed fault."""
    random.seed(7)
    sim = GridSimulator(protection_enabled=True)
    # Speed the relays so the cascade completes within the test horizon.
    sim._protection = ProtectionSystem(base_time_s=1.0, pickup_ratio=1.03)
    sim.trip_transformer(17)        # seed contingency
    sim.load_spike(64, 20.0)        # stress the downstream pocket further
    for _ in range(900):            # ~18 s
        sim.step()
    total_tripped = len(sim._tripped_lines) + len(sim._tripped_trafos)
    # Seed fault was 1 element; protection must have added at least one more.
    assert len(sim._protection.events) >= 1
    assert total_tripped >= 2
