"""Fault injection handler for the city-grid simulator.

Translates resource-identifier (RID) references into concrete
:class:`~.swing.GridSimulator` mutations.

RID examples
────────────
* ``ri.city-grid.main.transmission-line.5``  → line index 5
* ``ri.city-grid.main.transformer.3``        → transformer index 3
* ``ri.city-grid.main.generator.2``          → generator at bus 2
* ``ri.city-grid.main.load-bus.45``          → load at bus 45
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from .swing import GridSimulator

log = logging.getLogger(__name__)

_RID_TAIL_RE = re.compile(r"\.(\d+)$")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class FaultType(str, Enum):
    LINE_TRIP = "LINE_TRIP"
    TRAFO_TRIP = "TRAFO_TRIP"
    GEN_DROPOUT = "GEN_DROPOUT"
    LOAD_SPIKE = "LOAD_SPIKE"
    GEN_SETPOINT = "GEN_SETPOINT"
    RESTORE = "RESTORE"


class FaultRequest(BaseModel):
    """Wire format for incoming fault commands."""

    type: FaultType
    target_rid: str = ""
    magnitude_mw: float = 0.0


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def _parse_rid_index(rid: str) -> int:
    """Extract the trailing integer from a resource-identifier (RID) string."""
    m = _RID_TAIL_RE.search(rid)
    if m is None:
        raise ValueError(f"Cannot extract numeric index from RID: {rid!r}")
    return int(m.group(1))


class FaultHandler:
    """Translates :class:`FaultRequest` messages into simulator mutations."""

    def __init__(self, simulator: GridSimulator) -> None:
        self._sim = simulator

    def apply(self, request: FaultRequest) -> str:
        """Apply *request* and return a human-readable acknowledgement."""
        ft = request.type

        if ft is FaultType.RESTORE:
            self._sim.restore()
            log.info("System restored to initial state")
            return "System restored to initial state"

        idx = _parse_rid_index(request.target_rid)

        if ft is FaultType.LINE_TRIP:
            self._sim.trip_line(idx)
            msg = f"Tripped transmission line {idx}"

        elif ft is FaultType.TRAFO_TRIP:
            self._sim.trip_transformer(idx)
            msg = f"Tripped transformer {idx}"

        elif ft is FaultType.GEN_DROPOUT:
            self._sim.gen_dropout(idx)
            msg = f"Generator dropout at bus {idx}"

        elif ft is FaultType.LOAD_SPIKE:
            self._sim.load_spike(idx, request.magnitude_mw)
            msg = f"Load spike +{request.magnitude_mw:.1f} MW at bus {idx}"

        elif ft is FaultType.GEN_SETPOINT:
            self._sim.set_gen_setpoint(idx, request.magnitude_mw)
            msg = f"Generator at bus {idx} setpoint → {request.magnitude_mw:.1f} MW"

        else:
            msg = f"Unrecognised fault type: {ft}"
            log.warning(msg)
            return msg

        log.info(msg)
        return msg
