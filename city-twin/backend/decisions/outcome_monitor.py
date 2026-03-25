from __future__ import annotations
import logging
from typing import TYPE_CHECKING
from .models import GridDecision

if TYPE_CHECKING:
    from physics.swing import GridState

logger = logging.getLogger(__name__)


class OutcomeMonitor:
    """Evaluates the outcome of executed decisions by comparing pre/post state."""

    @staticmethod
    def capture_snapshot(state: GridState) -> dict:
        """Capture key metrics from grid state for comparison."""
        return {
            "frequency_hz": state.system_frequency_hz,
            "freq_deviation_hz": abs(state.system_frequency_hz - 60.0),
            "total_gen_mw": state.total_generation_mw,
            "total_load_mw": state.total_load_mw,
            "total_loss_mw": state.total_loss_mw,
            "overloaded_lines": sum(1 for l in state.lines if l.flow_pct_of_limit > 0.8 and not l.tripped),
            "tripped_lines": sum(1 for l in state.lines if l.tripped),
            "offline_generators": sum(1 for g in state.generators if not g.online),
            "gen_surplus_mw": state.total_generation_mw - state.total_load_mw,
        }

    @staticmethod
    def evaluate(decision: GridDecision, post_state: GridState) -> dict:
        """Compare pre and post state. Returns outcome_delta dict."""
        post = OutcomeMonitor.capture_snapshot(post_state)
        pre = decision.pre_state_snapshot

        delta = {}
        for key in post:
            if key in pre:
                delta[f"{key}_before"] = pre[key]
                delta[f"{key}_after"] = post[key]
                if isinstance(pre[key], (int, float)) and isinstance(post[key], (int, float)):
                    delta[f"{key}_change"] = round(post[key] - pre[key], 4)

        freq_improved = abs(post.get("freq_deviation_hz", 0)) < abs(pre.get("freq_deviation_hz", 0))
        overload_improved = post.get("overloaded_lines", 0) <= pre.get("overloaded_lines", 0)

        delta["freq_improved"] = freq_improved
        delta["overload_improved"] = overload_improved
        delta["overall_improved"] = freq_improved or overload_improved
        delta["backfired"] = not freq_improved and not overload_improved and (
            abs(post.get("freq_deviation_hz", 0)) > abs(pre.get("freq_deviation_hz", 0)) + 0.1
            or post.get("overloaded_lines", 0) > pre.get("overloaded_lines", 0)
        )

        decision.post_state_snapshot = post
        decision.outcome_delta = delta

        if delta["backfired"]:
            logger.warning("Decision %s BACKFIRED — state degraded", decision.id[:8])
        else:
            logger.info("Decision %s outcome: improved=%s", decision.id[:8], delta["overall_improved"])

        return delta
