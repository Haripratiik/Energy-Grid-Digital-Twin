from __future__ import annotations
import logging
from typing import TYPE_CHECKING
from .models import GridDecision, ProposedAction

if TYPE_CHECKING:
    from physics.swing import GridSimulator

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Applies approved/auto-approved GridDecision actions to the running simulator."""

    def __init__(self, simulator: GridSimulator):
        self._sim = simulator

    def execute(self, decision: GridDecision) -> bool:
        """Execute the decision's action on the simulator. Returns True on success."""
        action = decision.action
        params = action.parameters or {}
        try:
            if action.action_type == "LOAD_SHED":
                bus_id = self._parse_bus_id(action.target_rid)
                delta = params.get("delta_mw", action.estimated_impact_mw or -20)
                if delta > 0:
                    delta = -delta
                self._sim.load_spike(bus_id, delta)

            elif action.action_type == "GEN_SETPOINT":
                bus_id = self._parse_bus_id(action.target_rid)
                if "target_mw" in params:
                    target = params["target_mw"]
                elif "delta_mw" in params:
                    target = self._current_gen_mw(bus_id) + params["delta_mw"]
                elif "target_pct" in params:
                    target = self._gen_capacity(bus_id) * params["target_pct"] / 100.0
                else:
                    target = self._current_gen_mw(bus_id) + abs(action.estimated_impact_mw or 20)
                target = max(0, target)
                self._sim.set_gen_setpoint(bus_id, target)

            elif action.action_type == "LINE_SWITCH":
                line_idx = self._parse_index(action.target_rid)
                open_switch = params.get("switch_open", True)
                if open_switch:
                    self._sim.trip_line(line_idx)

            elif action.action_type == "TRANSFORMER_TAP":
                trafo_idx = self._parse_index(action.target_rid)
                self._sim.trip_transformer(trafo_idx)

            elif action.action_type == "ISLANDING":
                line_idx = self._parse_index(action.target_rid)
                self._sim.trip_line(line_idx)

            else:
                logger.warning("Unknown action type %s — marking as executed", action.action_type)

            decision.status = "EXECUTED"
            decision.executed_by = decision.executed_by or "AI_AUTO"
            logger.info("Executed decision %s: %s on %s", decision.id[:8], action.action_type, action.target_rid)
            return True

        except Exception:
            logger.exception("Failed to execute decision %s — marking EXPIRED", decision.id[:8])
            decision.status = "EXPIRED"
            return False

    def _current_gen_mw(self, bus_id: int) -> float:
        """Get current generator output for a bus."""
        for gen in self._sim._generators:
            if gen.bus_id == bus_id:
                return gen.p_electrical_mw
        return 0.0

    def _gen_capacity(self, bus_id: int) -> float:
        """Get generator capacity for a bus."""
        for gen in self._sim._generators:
            if gen.bus_id == bus_id:
                return gen.capacity_mw
        return 100.0

    def revert(self, decision: GridDecision) -> bool:
        """Attempt to revert an executed decision."""
        action = decision.action
        if not action.reversible:
            return False
        try:
            if action.action_type == "LOAD_SHED":
                bus_id = self._parse_bus_id(action.target_rid)
                delta = action.parameters.get("delta_mw", 0)
                self._sim.load_spike(bus_id, -delta)  # reverse the delta
            elif action.action_type == "GEN_SETPOINT":
                bus_id = self._parse_bus_id(action.target_rid)
                pre_mw = decision.pre_state_snapshot.get("gen_mw", 0)
                self._sim.set_gen_setpoint(bus_id, pre_mw)
            decision.status = "REVERTED"
            return True
        except Exception:
            logger.exception("Failed to revert decision %s", decision.id[:8])
            return False

    @staticmethod
    def _parse_bus_id(rid: str) -> int:
        return int(rid.rsplit(".", 1)[-1])

    @staticmethod
    def _parse_index(rid: str) -> int:
        return int(rid.rsplit(".", 1)[-1])
