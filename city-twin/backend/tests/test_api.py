"""End-to-end tests for the FastAPI integration layer.

Exercises the actual HTTP endpoints (and, through the lifespan, the background
simulation loop + SSE broadcast wiring) — the layer the frontend talks to and
that was previously untested. Runs fully offline: no API key → demo mode, an
isolated temp SQLite db, and ambient demand disabled for stability.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    # Use tempfile directly (not pytest's tmp_path_factory) so the isolated
    # SQLite db doesn't depend on pytest's temp-root, which can hit permission
    # issues on some Windows setups.
    tmpdir = tempfile.mkdtemp(prefix="gridtwin_api_")
    os.environ["GRID_DB_PATH"] = os.path.join(tmpdir, "test.db")
    os.environ["GRID_AMBIENT"] = "0"          # keep the grid calm/deterministic
    os.environ["OPENAI_API_KEY"] = ""          # force reasoning demo mode (offline)

    import main  # imported lazily so the env vars above take effect first

    with TestClient(main.app) as c:            # runs lifespan → starts sim loop
        yield c
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert "sim_time_s" in body
    assert body["mode"] in ("SEMI", "FULL_AUTO")
    assert body["pending_decisions"] >= 0


def test_ontology_endpoint(client):
    r = client.get("/ontology")
    assert r.status_code == 200
    assert isinstance(r.json(), (dict, list))


def test_generators_endpoint(client):
    r = client.get("/generators")
    assert r.status_code == 200
    gens = r.json()
    # The 80-bus grid is configured with 12 generators.
    assert isinstance(gens, (list, dict))


def test_restore_endpoint(client):
    r = client.post("/restore")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_pending_decisions_is_a_list(client):
    r = client.get("/decisions/pending")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_mode_get_and_switch(client):
    assert client.get("/mode").json()["mode"] in ("SEMI", "FULL_AUTO")

    r = client.post("/mode", json={"mode": "FULL_AUTO"})
    assert r.status_code == 200
    assert r.json()["mode"] == "FULL_AUTO"
    assert client.get("/mode").json()["mode"] == "FULL_AUTO"

    # invalid mode is reported as an error, not a 500
    r = client.post("/mode", json={"mode": "NONSENSE"})
    assert r.status_code == 200
    assert r.json()["status"] == "error"

    client.post("/mode", json={"mode": "SEMI"})   # restore default


def test_fault_then_restore(client):
    """Injecting a line trip should be accepted and then recoverable."""
    r = client.post("/fault", json={
        "type": "LINE_TRIP",
        "target_rid": "ri.city-grid.main.transmission-line.3",
        "magnitude_mw": 0.0,
    })
    assert r.status_code == 200
    assert client.post("/restore").status_code == 200
