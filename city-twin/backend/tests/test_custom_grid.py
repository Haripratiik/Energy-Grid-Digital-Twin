"""Tests for the user-built ("custom") grid simulator.

Locks in two correctness/honesty properties that previously broke:
  1. A grid that does not fully solve (e.g. a bus islanded from any source,
     which pandapower returns as NaN even on a "converged" run) must NOT be
     reported as healthy — the bus carries no voltage and an UNKNOWN status.
  2. The result must be JSON-serialisable the way Starlette serialises it
     (allow_nan=False) — a stray NaN used to surface as an HTTP 500.
"""

from __future__ import annotations

import json

from physics.custom_grid import CustomGridSpec, simulate_custom_grid

# Statuses the ontology layer (GridAsset) accepts — the custom ontology must
# never emit a value outside this set (UNKNOWN has to be mapped before it does).
_VALID_ONT_STATUS = {"NOMINAL", "DEGRADED", "OVERLOADED", "TRIPPED", "CRITICAL"}


def _spec(buses, lines):
    return CustomGridSpec.model_validate({"buses": buses, "lines": lines})


def _starlette_safe(result: dict) -> None:
    """Mirror Starlette's JSONResponse, which forbids NaN/Infinity."""
    json.dumps(result, allow_nan=False)


def test_simple_grid_converges():
    result = simulate_custom_grid(_spec(
        [{"id": 1, "voltage_kv": 230, "gen_mw": 250, "is_slack": True},
         {"id": 2, "voltage_kv": 132, "load_mw": 120}],
        [{"from_id": 1, "to_id": 2}],
    ))
    assert result["converged"] is True
    for b in result["buses"]:
        assert b["vm_pu"] is not None
        assert 0.5 < b["vm_pu"] < 1.5
        assert b["status"] in {"NOMINAL", "DEGRADED", "CRITICAL"}
    _starlette_safe(result)


def test_overloaded_grid_is_flagged_not_nominal():
    # Heavy load behind a single line → low voltage + overloaded branch.
    result = simulate_custom_grid(_spec(
        [{"id": 1, "voltage_kv": 230, "gen_mw": 250, "is_slack": True},
         {"id": 2, "voltage_kv": 132, "load_mw": 120},
         {"id": 3, "voltage_kv": 132, "load_mw": 300}],
        [{"from_id": 1, "to_id": 2}, {"from_id": 2, "to_id": 3}],
    ))
    assert result["converged"] is True
    assert any(line["status"] == "OVERLOADED" for line in result["lines"])
    assert any(bus["status"] in {"DEGRADED", "CRITICAL"} for bus in result["buses"])
    _starlette_safe(result)


def test_isolated_bus_is_unknown_not_healthy():
    # Bus 2 has load but no line back to a source → no voltage solution there.
    result = simulate_custom_grid(_spec(
        [{"id": 1, "voltage_kv": 230, "gen_mw": 50, "is_slack": True},
         {"id": 2, "voltage_kv": 230, "load_mw": 100}],
        [],
    ))
    by_id = {b["id"]: b for b in result["buses"]}
    # The islanded bus must be honest: no voltage, UNKNOWN — never NOMINAL/1.0pu.
    assert by_id[2]["vm_pu"] is None
    assert by_id[2]["status"] == "UNKNOWN"
    # And the whole payload must serialise without a NaN (was a 500 before).
    _starlette_safe(result)


def test_ontology_status_is_always_valid_vocabulary():
    # UNKNOWN buses must be mapped to a status the GridAsset model accepts.
    result = simulate_custom_grid(_spec(
        [{"id": 1, "voltage_kv": 230, "gen_mw": 50, "is_slack": True},
         {"id": 2, "voltage_kv": 230, "load_mw": 100}],
        [],
    ))
    for node in result["ontology"]["nodes"]:
        assert node["status"] in _VALID_ONT_STATUS
    _starlette_safe(result["ontology"])


def test_empty_spec_is_handled():
    result = simulate_custom_grid(_spec([], []))
    assert result["converged"] is False
    assert result["buses"] == []
    assert result["ontology"]["nodes"] == []
    _starlette_safe(result)
