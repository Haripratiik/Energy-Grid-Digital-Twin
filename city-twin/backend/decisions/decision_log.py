from __future__ import annotations
from collections import deque
from typing import Optional
from .models import GridDecision

MAX_LOG_SIZE = 500


class DecisionLog:
    """Append-only audit trail of all grid decisions."""

    def __init__(self):
        self._log: deque[GridDecision] = deque(maxlen=MAX_LOG_SIZE)
        self._index: dict[str, GridDecision] = {}  # id -> decision for O(1) lookup

    def record(self, decision: GridDecision) -> None:
        self._log.append(decision)
        self._index[decision.id] = decision
        if len(self._index) > MAX_LOG_SIZE * 2:
            live_ids = {d.id for d in self._log}
            self._index = {k: v for k, v in self._index.items() if k in live_ids}

    def get(self, decision_id: str) -> Optional[GridDecision]:
        return self._index.get(decision_id)

    def get_pending(self) -> list[GridDecision]:
        return [d for d in self._log if d.status == "PENDING"]

    def get_all(self, limit: int = 100) -> list[GridDecision]:
        items = list(self._log)
        return items[-limit:]

    def clear(self) -> None:
        self._log.clear()
        self._index.clear()
