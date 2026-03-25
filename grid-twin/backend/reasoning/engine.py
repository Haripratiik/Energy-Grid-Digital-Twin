"""
LLM Reasoning Engine (GRID-AI)
===============================
Anthropic-powered operational intelligence layer that analyses real-time grid
telemetry and produces structured operator advisories.  In demo mode the engine
returns a pre-authored cached response so the front-end can function without a
live API key.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel

from .cached_responses import DEMO_CASCADE_RESPONSE

if TYPE_CHECKING:
    from ontology.model import PropagationResponse
    from physics.simulator import GridState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class ReasoningResult(BaseModel):
    id: str
    triggered_by_alert_id: Optional[str]
    trigger_type: Literal["AUTO_CRITICAL", "MANUAL"]
    context_snapshot: dict
    response_text: str
    timestamp: datetime


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are GRID-AI, an operational intelligence system for power grid management \
deployed on Palantir AIP. You receive real-time telemetry streamed from a \
digital twin of the IEEE 9-bus power system, modeled as a Palantir Foundry \
Ontology. Your role is to assess grid stability, identify cascading failure \
risk, and provide specific actionable operator recommendations.

Be concise, technical, and direct. Address the operator directly using \
imperative language. Always reference specific asset IDs (bus numbers, line \
IDs). Structure every response with exactly these three labeled sections:

SITUATION
[2 sentences max. State what is happening and how serious it is.]

IMMEDIATE ACTIONS
[Numbered list, max 3 items. Each action must name a specific asset.]

RISK ASSESSMENT
[1 sentence. State probability of cascade failure and time horizon.]

Use power engineering terminology: load shedding, islanding, voltage angle \
instability, thermal overload, frequency nadir, spinning reserve. This is a \
real-time operational context. Brevity and specificity save the grid."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_MAX_HISTORY = 10


class ReasoningEngine:
    """Anthropic-backed reasoning engine for the Energy Grid Digital Twin."""

    def __init__(self, api_key: str, *, demo_mode: bool = False) -> None:
        self._api_key = api_key
        self._demo_mode = demo_mode
        self._history: deque[ReasoningResult] = deque(maxlen=_MAX_HISTORY)
        self._client = None

    def _get_client(self):
        """Lazy-initialise the Anthropic client so the import is deferred."""
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    # ------------------------------------------------------------------
    # Context builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(
        state: GridState,
        propagation: PropagationResponse | None,
        trigger_type: str,
    ) -> dict:
        overloaded = [
            l for l in state.lines if l.flow_pct_of_limit > 0.80 and not l.tripped
        ]
        tripped = [l for l in state.lines if l.tripped]
        unstable_gens = [
            g for g in state.generators
            if abs(g.rotor_angle_deg) > 45.0 or not g.online
        ]

        ctx: dict = {
            "sim_time_s": state.sim_time_s,
            "system_frequency_hz": state.system_frequency_hz,
            "total_generation_mw": state.total_generation_mw,
            "total_load_mw": state.total_load_mw,
            "overloaded_lines": [
                {
                    "id": l.id,
                    "flow_mw": l.flow_mw,
                    "pct": round(l.flow_pct_of_limit * 100, 1),
                }
                for l in overloaded
            ],
            "tripped_lines": [l.id for l in tripped],
            "unstable_generators": [
                {
                    "bus_id": g.bus_id,
                    "angle_deg": g.rotor_angle_deg,
                    "online": g.online,
                }
                for g in unstable_gens
            ],
            "bus_angles_deg": {
                b.id: round(b.voltage_angle_deg, 2) for b in state.buses
            },
            "trigger_type": trigger_type,
        }

        if propagation:
            ctx["propagation"] = {
                "affected_nodes": propagation.affected_nodes,
                "propagation_order": propagation.propagation_order,
            }

        return ctx

    @staticmethod
    def _context_to_user_message(ctx: dict) -> str:
        parts: list[str] = [
            f"Simulation time: {ctx['sim_time_s']:.2f}s",
            f"System frequency: {ctx['system_frequency_hz']:.4f} Hz",
            f"Generation: {ctx['total_generation_mw']:.1f} MW  |  Load: {ctx['total_load_mw']:.1f} MW",
        ]
        if ctx["overloaded_lines"]:
            lines_str = ", ".join(
                f"Line {l['id']} at {l['pct']}%" for l in ctx["overloaded_lines"]
            )
            parts.append(f"Overloaded lines: {lines_str}")
        if ctx["tripped_lines"]:
            parts.append(f"Tripped lines: {', '.join(ctx['tripped_lines'])}")
        if ctx["unstable_generators"]:
            gens_str = ", ".join(
                f"Gen@Bus{g['bus_id']} δ={g['angle_deg']:.1f}° online={g['online']}"
                for g in ctx["unstable_generators"]
            )
            parts.append(f"Unstable generators: {gens_str}")
        if "propagation" in ctx:
            parts.append(
                f"Propagation subgraph: {len(ctx['propagation']['affected_nodes'])} nodes affected"
            )
        parts.append(f"Trigger: {ctx['trigger_type']}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Main analysis entry point
    # ------------------------------------------------------------------

    def analyze(
        self,
        state: GridState,
        propagation_subgraph: PropagationResponse | None,
        trigger_type: Literal["AUTO_CRITICAL", "MANUAL"],
        alert_id: str | None = None,
    ) -> ReasoningResult:
        """Run a full reasoning cycle and return the operator advisory."""
        ctx = self._build_context(state, propagation_subgraph, trigger_type)

        if self._demo_mode:
            response_text = DEMO_CASCADE_RESPONSE.strip()
        else:
            response_text = self._call_llm(ctx)

        result = ReasoningResult(
            id=str(uuid.uuid4()),
            triggered_by_alert_id=alert_id,
            trigger_type=trigger_type,
            context_snapshot=ctx,
            response_text=response_text,
            timestamp=datetime.now(timezone.utc),
        )
        self._history.append(result)
        return result

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, ctx: dict) -> str:
        client = self._get_client()
        user_msg = self._context_to_user_message(ctx)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            return response.content[0].text
        except Exception:
            logger.exception("Anthropic API call failed — falling back to cached response")
            return DEMO_CASCADE_RESPONSE.strip()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history(self) -> list[ReasoningResult]:
        return list(self._history)
