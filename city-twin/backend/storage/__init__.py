"""SQLite-backed persistence for telemetry, decisions, and evaluation runs.

The live app keeps working state in memory; this layer makes it durable and
queryable across restarts — telemetry history, the decision audit trail, and a
record of every controller-evaluation run. SQLite is deliberate: zero-ops,
embedded, and trivially upgradeable to Postgres/TimescaleDB later.
"""

from .store import GridStore

__all__ = ["GridStore"]
