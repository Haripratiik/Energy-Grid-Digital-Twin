"""
Fault Injection Handler
=======================
Translates incoming fault requests (from the API / Ontology layer) into
concrete simulator mutations.  Each fault type maps to a specific physical
perturbation on the IEEE 9-bus network.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .simulator import GridSimulator

logger = logging.getLogger(__name__)


class FaultType(str, Enum):
    LINE_TRIP = "LINE_TRIP"
    GEN_DROPOUT = "GEN_DROPOUT"
    LOAD_SPIKE = "LOAD_SPIKE"
    RESTORE = "RESTORE"


class FaultRequest(BaseModel):
    type: FaultType
    target_rid: str = Field(
        ...,
        description=(
            "Resource identifier (RID) for the target asset, e.g. "
            "'ri.grid-asset.main.transmission-line.5-6' or "
            "'ri.grid-asset.main.generator.2'"
        ),
    )
    magnitude_mw: float = 0.0


_LINE_PATTERN = re.compile(r"(\d+)-(\d+)$")
_BUS_PATTERN = re.compile(r"(\d+)$")


def _extract_line_buses(rid: str) -> tuple[int, int]:
    """Parse 'from-to' bus IDs from the tail of a transmission-line RID."""
    tail = rid.rsplit(".", maxsplit=1)[-1]
    m = _LINE_PATTERN.match(tail)
    if not m:
        raise ValueError(f"Cannot parse line bus pair from RID: {rid}")
    return int(m.group(1)), int(m.group(2))


def _extract_bus_id(rid: str) -> int:
    """Parse a single bus ID from the tail of a generator or load RID."""
    tail = rid.rsplit(".", maxsplit=1)[-1]
    m = _BUS_PATTERN.match(tail)
    if not m:
        raise ValueError(f"Cannot parse bus ID from RID: {rid}")
    return int(m.group(1))


class FaultHandler:
    """Applies fault requests to a running GridSimulator instance."""

    def __init__(self, simulator: GridSimulator) -> None:
        self._sim = simulator

    def apply(self, request: FaultRequest) -> str:
        """
        Dispatch a fault request to the appropriate simulator method.

        Returns a human-readable status message.
        """
        handler = _DISPATCH.get(request.type)
        if handler is None:
            raise ValueError(f"Unknown fault type: {request.type}")
        return handler(self, request)

    # ------------------------------------------------------------------
    # Individual fault handlers
    # ------------------------------------------------------------------

    def _handle_line_trip(self, req: FaultRequest) -> str:
        from_bus, to_bus = _extract_line_buses(req.target_rid)
        logger.info("LINE_TRIP: tripping line %d-%d", from_bus, to_bus)
        self._sim.trip_line(from_bus, to_bus)
        return f"Line {from_bus}-{to_bus} tripped"

    def _handle_gen_dropout(self, req: FaultRequest) -> str:
        bus_id = _extract_bus_id(req.target_rid)
        logger.info("GEN_DROPOUT: generator at bus %d going offline", bus_id)
        self._sim.gen_dropout(bus_id)
        return f"Generator at bus {bus_id} offline; power redistributed"

    def _handle_load_spike(self, req: FaultRequest) -> str:
        bus_id = _extract_bus_id(req.target_rid)
        mag = req.magnitude_mw
        logger.info("LOAD_SPIKE: +%.1f MW at bus %d", mag, bus_id)
        self._sim.load_spike(bus_id, mag)
        return f"Load at bus {bus_id} increased by {mag:.1f} MW"

    def _handle_restore(self, _req: FaultRequest) -> str:
        logger.info("RESTORE: resetting simulation to nominal state")
        self._sim.restore()
        return "System restored to nominal conditions"


_DISPATCH: dict[FaultType, callable] = {
    FaultType.LINE_TRIP: FaultHandler._handle_line_trip,
    FaultType.GEN_DROPOUT: FaultHandler._handle_gen_dropout,
    FaultType.LOAD_SPIKE: FaultHandler._handle_load_spike,
    FaultType.RESTORE: FaultHandler._handle_restore,
}
