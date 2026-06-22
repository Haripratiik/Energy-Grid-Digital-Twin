"""Smoke tests for the real Georgia (OSM) grid build + ontology.

The build reads a bundled GeoJSON, snaps line endpoints to substations, takes
the largest connected component, and runs a DC power flow. These tests assert
the contract the frontend /real-grid and /real-grid/ontology endpoints rely on.
"""

from __future__ import annotations

import json

from physics.real_grid import build_real_grid, build_real_ontology

_VALID_ONT_STATUS = {"NOMINAL", "DEGRADED", "OVERLOADED", "TRIPPED", "CRITICAL"}


def test_real_grid_builds_connected_topology():
    grid = build_real_grid()
    assert grid.n_buses > 0
    assert grid.n_lines > 0
    assert grid.n_buses == len(grid.buses)
    assert grid.n_lines == len(grid.lines)
    # Every bus carries real coordinates and a voltage class.
    for bus in grid.buses:
        assert -90 <= bus.lat <= 90
        assert -180 <= bus.lon <= 180
        assert bus.voltage_kv > 0
    # At least one source feeds the network, and lines carry a loading figure.
    assert any(bus.is_source for bus in grid.buses)
    assert all(line.loading_pct >= 0 for line in grid.lines)


def test_real_ontology_is_valid_and_serialisable():
    ont = build_real_ontology()
    assert len(ont["nodes"]) > 0
    for node in ont["nodes"]:
        assert node["status"] in _VALID_ONT_STATUS
    # Mirror Starlette's JSONResponse (no NaN/Infinity allowed).
    json.dumps(ont, allow_nan=False)
