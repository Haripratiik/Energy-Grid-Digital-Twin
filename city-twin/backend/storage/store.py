"""SQLite store for telemetry, decisions, and evaluation runs.

Thread-safe (a single connection guarded by a lock) so the FastAPI event loop
and its worker threads can all write. Schema is created on first open and is
forward-compatible via ``CREATE TABLE IF NOT EXISTS``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from physics.swing import GridState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               TEXT    NOT NULL,
    wall_ts              REAL    NOT NULL,
    sim_time_s           REAL    NOT NULL,
    frequency_hz         REAL    NOT NULL,
    total_generation_mw  REAL    NOT NULL,
    total_load_mw        REAL    NOT NULL,
    total_loss_mw        REAL    NOT NULL,
    n_violations         INTEGER NOT NULL,
    max_line_loading_pct REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_run ON telemetry(run_id, sim_time_s);

CREATE TABLE IF NOT EXISTS decisions (
    id                   TEXT PRIMARY KEY,
    wall_ts              REAL NOT NULL,
    risk_level           TEXT,
    action_type          TEXT,
    target_rid           TEXT,
    status               TEXT,
    executed_by          TEXT,
    estimated_impact_mw  REAL,
    rationale            TEXT,
    raw_json             TEXT
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(wall_ts);

CREATE TABLE IF NOT EXISTS eval_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wall_ts         REAL NOT NULL,
    scenario_id     TEXT NOT NULL,
    controller      TEXT NOT NULL,
    seed            INTEGER,
    cost            REAL,
    load_shed_mw    REAL,
    max_freq_dev_hz REAL,
    final_secure    INTEGER,
    metrics_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_eval_scenario ON eval_runs(scenario_id);
"""


def _count_violations(state: "GridState") -> tuple[int, float]:
    max_line = 0.0
    n = 0
    for ln in state.lines:
        if ln.tripped:
            continue
        pct = ln.flow_pct_of_limit * 100.0
        max_line = max(max_line, pct)
        if pct > 100.0:
            n += 1
    for xf in state.transformers:
        if xf.status == "tripped":
            continue
        max_line = max(max_line, xf.loading_pct)
        if xf.loading_pct > 100.0:
            n += 1
    for b in state.buses:
        if abs(b.voltage_magnitude_pu - 1.0) > 0.10:
            n += 1
    return n, round(max_line, 2)


class GridStore:
    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # -- writes -------------------------------------------------------------

    def record_telemetry(self, state: "GridState", run_id: str = "live") -> None:
        n_viol, max_line = _count_violations(state)
        with self._lock:
            self._conn.execute(
                "INSERT INTO telemetry (run_id, wall_ts, sim_time_s, frequency_hz, "
                "total_generation_mw, total_load_mw, total_loss_mw, n_violations, "
                "max_line_loading_pct) VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, time.time(), state.sim_time_s, state.system_frequency_hz,
                 state.total_generation_mw, state.total_load_mw, state.total_loss_mw,
                 n_viol, max_line),
            )
            self._conn.commit()

    def record_decision(self, decision: dict[str, Any]) -> None:
        """Upsert a decision (status changes over its lifetime)."""
        action = decision.get("action", {}) or {}
        with self._lock:
            self._conn.execute(
                "INSERT INTO decisions (id, wall_ts, risk_level, action_type, "
                "target_rid, status, executed_by, estimated_impact_mw, rationale, raw_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
                "executed_by=excluded.executed_by, raw_json=excluded.raw_json",
                (decision.get("id"), time.time(), decision.get("risk_level"),
                 action.get("action_type"), action.get("target_rid"),
                 decision.get("status"), decision.get("executed_by"),
                 action.get("estimated_impact_mw"), action.get("rationale"),
                 json.dumps(decision, default=str)),
            )
            self._conn.commit()

    def record_eval_run(self, metrics: dict[str, Any], seed: Optional[int] = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO eval_runs (wall_ts, scenario_id, controller, seed, cost, "
                "load_shed_mw, max_freq_dev_hz, final_secure, metrics_json) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (time.time(), metrics.get("scenario_id"), metrics.get("controller"),
                 seed, metrics.get("cost"), metrics.get("load_shed_mw"),
                 metrics.get("max_freq_dev_hz"), int(bool(metrics.get("final_secure"))),
                 json.dumps(metrics, default=str)),
            )
            self._conn.commit()

    # -- reads --------------------------------------------------------------

    def telemetry_history(self, run_id: str = "live", limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM telemetry WHERE run_id=? ORDER BY id DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def decision_history(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM decisions ORDER BY wall_ts DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def eval_runs(self, scenario_id: Optional[str] = None, limit: int = 200) -> list[dict]:
        with self._lock:
            if scenario_id:
                rows = self._conn.execute(
                    "SELECT * FROM eval_runs WHERE scenario_id=? ORDER BY wall_ts DESC LIMIT ?",
                    (scenario_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM eval_runs ORDER BY wall_ts DESC LIMIT ?", (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                t: self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("telemetry", "decisions", "eval_runs")
            }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
