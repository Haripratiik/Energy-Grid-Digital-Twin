"""OpenAI GPT-4o reasoning engine with structured outputs.

Analyses real-time grid telemetry and proposes corrective actions using
Pydantic-validated structured responses from the OpenAI Chat Completions API.
Falls back to cached demo responses when the API is unavailable.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, Field

from .cached_responses import (
    DEMO_CASCADE_RESPONSE_TEXT,
    DEMO_HEADLINE,
    DEMO_PROPOSED_ACTIONS,
    DEMO_WHAT_CHANGED,
)

if TYPE_CHECKING:
    from physics.swing import GridState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured-output schemas (sent to OpenAI via response_format)
# ---------------------------------------------------------------------------

class ActionParameters(BaseModel):
    delta_mw: Optional[float] = None
    target_pct: Optional[float] = None
    tap_position: Optional[int] = None
    switch_open: Optional[bool] = None

class DecisionResponseAction(BaseModel):
    action_type: str
    target_rid: str
    parameters: ActionParameters
    rationale: str
    confidence: float
    estimated_impact_mw: float
    reversible: bool


class DecisionResponse(BaseModel):
    operator_headline: str
    answer_to_operator: str = ""
    what_changed: list[str]
    situation_summary: str
    proposed_actions: list[DecisionResponseAction]
    risk_assessment: str
    cascade_probability: float
    time_horizon_seconds: int


# ---------------------------------------------------------------------------
# Internal result model
# ---------------------------------------------------------------------------

class ReasoningResult(BaseModel):
    id: str
    triggered_by_alert_id: Optional[str] = None
    trigger_type: Literal["AUTO_CRITICAL", "AUTO_WARNING", "MANUAL"]
    user_query: Optional[str] = None
    context_snapshot: dict
    operator_headline: str = ""
    answer_to_operator: Optional[str] = None
    what_changed: list[str] = Field(default_factory=list)
    response_text: str
    proposed_actions: list[dict]
    cascade_probability: float
    time_horizon_seconds: int
    timestamp: datetime


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are GRID Assistant, an AI operator aide for a city-scale power grid \
digital twin (80-bus, multi-voltage, multi-generator). You receive live \
telemetry and may also receive a question from the human operator.

Be BRIEF. Keep all text fields short (1-2 sentences each). Respond fast.

PRIORITIES (in order):
1. Answer the operator's question clearly and directly if one is provided.
2. Summarise what is happening on the grid in plain language.
3. Propose specific corrective actions to RESTORE the grid to a healthy state.

ACTION STRATEGY — ALWAYS prefer adding generation over shedding load:
- If a generator tripped, FIRST ramp up other available generators (GEN_SETPOINT \
with positive delta_mw) to recover the lost capacity.
- Available generator buses: 1(nuclear 800MW), 2(hydro 400MW), 3(gas 350MW), \
4(wind 200MW), 5(solar 150MW), 8(gas 120MW), 10(gas 100MW), 12(hydro 80MW), \
15(wind 60MW), 18(solar 40MW), 20(gas 80MW), 22(wind 50MW).
- Only use LOAD_SHED as a last resort when generation cannot cover the deficit.
- For GEN_SETPOINT, use positive delta_mw to INCREASE output (e.g. delta_mw: +60 \
means add 60 MW).

RESPONSE STRUCTURE (all fields required):

operator_headline — One short sentence (max 15 words) summarising grid \
status in plain language. Example: "Frequency dropping — ramping gas peakers \
to compensate."

answer_to_operator — If the operator asked a question, answer it in 1-3 \
clear sentences. Use everyday language where possible; add technical detail \
only when it helps. Leave empty string if no question was asked.

what_changed — 2-4 short bullet strings describing the key telemetry the \
model relied on. Example: ["Frequency at 59.72 Hz (−0.28 Hz)", \
"Line L-12 at 92% thermal limit", "Generator Bus 3 ramping to compensate"].

situation_summary — 2 sentences max, technical assessment for the log.

proposed_actions — Ordered list of corrective actions. Each action MUST have:
  action_type: LOAD_SHED | GEN_SETPOINT | LINE_SWITCH | TRANSFORMER_TAP | ISLANDING
  target_rid: Palantir RID (e.g. "ri.city-grid.main.generator.8")
  parameters: object with optional keys: delta_mw (float), target_pct (float), tap_position (int), switch_open (bool). Use whichever apply.
  rationale: 1-sentence technical justification
  confidence: 0.0-1.0
  estimated_impact_mw: positive = adding MW to grid, negative = removing MW from grid
  reversible: true/false

risk_assessment — 1 sentence on cascade probability.
cascade_probability — float 0.0-1.0.
time_horizon_seconds — seconds until cascade if no action taken.

When the grid is healthy and no actions are needed, still fill \
operator_headline and what_changed; return an empty proposed_actions list \
and set cascade_probability to 0."""

_MAX_HISTORY = 10


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ReasoningEngine:
    """Wraps OpenAI GPT-4o to provide grid-aware reasoning with structured outputs."""

    def __init__(self, api_key: str, *, demo_mode: bool = False) -> None:
        self._api_key = api_key
        self._demo_mode = demo_mode
        self._history: deque[ReasoningResult] = deque(maxlen=_MAX_HISTORY)
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self._api_key,
                timeout=10.0,
                max_retries=0,
            )
        return self._client

    # -- context helpers ----------------------------------------------------

    @staticmethod
    def _build_context(state: GridState, trigger_type: str) -> dict:
        overloaded = [
            ln for ln in state.lines
            if ln.flow_pct_of_limit > 0.8 and not ln.tripped
        ]
        tripped_lines = [ln for ln in state.lines if ln.tripped]

        return {
            "sim_time_s": state.sim_time_s,
            "system_frequency_hz": state.system_frequency_hz,
            "freq_deviation_hz": round(state.system_frequency_hz - 60.0, 4),
            "total_generation_mw": state.total_generation_mw,
            "total_load_mw": state.total_load_mw,
            "total_loss_mw": state.total_loss_mw,
            "gen_surplus_mw": round(
                state.total_generation_mw - state.total_load_mw, 2
            ),
            "overloaded_lines": [
                {
                    "id": ln.id,
                    "flow_mw": ln.flow_mw,
                    "loading_pct": round(ln.flow_pct_of_limit * 100, 1),
                }
                for ln in overloaded
            ],
            "tripped_lines": [ln.id for ln in tripped_lines],
            "generators": [
                {
                    "bus_id": g.bus_id,
                    "type": g.gen_type,
                    "p_mw": g.electrical_power_mw,
                    "online": g.online,
                    "angle_deg": g.rotor_angle_deg,
                }
                for g in state.generators
            ],
            "trigger_type": trigger_type,
        }

    @staticmethod
    def _context_to_message(ctx: dict, user_query: str | None = None) -> str:
        parts = [
            (
                f"Time: {ctx['sim_time_s']:.1f}s | "
                f"Freq: {ctx['system_frequency_hz']:.3f} Hz "
                f"(Δ={ctx['freq_deviation_hz']:+.3f})"
            ),
            (
                f"Generation: {ctx['total_generation_mw']:.1f} MW | "
                f"Load: {ctx['total_load_mw']:.1f} MW | "
                f"Losses: {ctx['total_loss_mw']:.1f} MW"
            ),
        ]
        if ctx["overloaded_lines"]:
            parts.append(
                "Overloaded: "
                + ", ".join(
                    f"{ln['id']} at {ln['loading_pct']}%"
                    for ln in ctx["overloaded_lines"]
                )
            )
        if ctx["tripped_lines"]:
            parts.append("Tripped: " + ", ".join(ctx["tripped_lines"]))
        parts.append(
            "Generators: "
            + ", ".join(
                f"Bus{g['bus_id']}({g['type']}) "
                f"{'ONLINE' if g['online'] else 'OFFLINE'} "
                f"{g['p_mw']:.0f}MW δ={g['angle_deg']:.1f}°"
                for g in ctx["generators"]
            )
        )
        if user_query:
            parts.append(f"\nOperator question: {user_query}")
        return "\n".join(parts)

    # -- risk enrichment ----------------------------------------------------

    @staticmethod
    def _enrich_actions_with_risk(actions: list[dict]) -> list[dict]:
        """Attach a risk_level string to each proposed-action dict."""
        from decisions.models import ProposedAction
        from decisions.risk_classifier import RiskClassifier

        enriched = []
        for a in actions:
            try:
                pa = ProposedAction(**a)
                a["risk_level"] = RiskClassifier.classify(pa).value
            except Exception:
                a["risk_level"] = "ADVISORY"
            enriched.append(a)
        return enriched

    # -- public API ---------------------------------------------------------

    def analyze(
        self,
        state: GridState,
        propagation,
        trigger_type: Literal["AUTO_CRITICAL", "AUTO_WARNING", "MANUAL"],
        alert_id: str | None = None,
        user_query: str | None = None,
    ) -> ReasoningResult:
        """Run reasoning over the current grid state and return a result."""
        ctx = self._build_context(state, trigger_type)

        if self._demo_mode:
            response_text = DEMO_CASCADE_RESPONSE_TEXT.strip()
            proposed = [dict(a) for a in DEMO_PROPOSED_ACTIONS]
            cascade_prob = 0.61
            time_horizon = 20
            headline = DEMO_HEADLINE
            what_changed = list(DEMO_WHAT_CHANGED)
            answer = None
        else:
            (
                response_text, proposed, cascade_prob, time_horizon,
                headline, what_changed, answer,
            ) = self._call_llm(ctx, user_query)

        proposed = self._enrich_actions_with_risk(proposed)

        result = ReasoningResult(
            id=str(uuid.uuid4()),
            triggered_by_alert_id=alert_id,
            trigger_type=trigger_type,
            user_query=user_query,
            context_snapshot=ctx,
            operator_headline=headline,
            answer_to_operator=answer,
            what_changed=what_changed,
            response_text=response_text,
            proposed_actions=proposed,
            cascade_probability=cascade_prob,
            time_horizon_seconds=time_horizon,
            timestamp=datetime.now(timezone.utc),
        )
        self._history.append(result)
        return result

    # -- LLM call -----------------------------------------------------------

    def _call_llm(
        self, ctx: dict, user_query: str | None = None,
    ) -> tuple[str, list[dict], float, int, str, list[str], str | None]:
        from shared.rate_limiter import openai_limiter

        if not openai_limiter.wait_and_acquire(timeout=15.0):
            logger.warning("Rate limiter timeout — using cached response")
            return (
                DEMO_CASCADE_RESPONSE_TEXT.strip(),
                [dict(a) for a in DEMO_PROPOSED_ACTIONS],
                0.61, 20, DEMO_HEADLINE, list(DEMO_WHAT_CHANGED), None,
            )

        client = self._get_client()
        user_msg = self._context_to_message(ctx, user_query)

        try:
            response = client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format=DecisionResponse,
                max_tokens=500,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise ValueError("No parsed response from OpenAI")

            text = f"SITUATION\n{parsed.situation_summary}\n\nIMMEDIATE ACTIONS\n"
            for i, action in enumerate(parsed.proposed_actions, 1):
                text += f"{i}. [{action.action_type}] {action.rationale}\n"
            text += f"\nRISK ASSESSMENT\n{parsed.risk_assessment}"

            actions = []
            for a in parsed.proposed_actions:
                d = a.model_dump()
                params = {k: v for k, v in d.get("parameters", {}).items() if v is not None}
                d["parameters"] = params
                actions.append(d)
            return (
                text,
                actions,
                parsed.cascade_probability,
                parsed.time_horizon_seconds,
                parsed.operator_headline,
                parsed.what_changed,
                parsed.answer_to_operator or None,
            )

        except Exception:
            logger.exception("OpenAI API call failed — using cached response")
            return (
                DEMO_CASCADE_RESPONSE_TEXT.strip(),
                [dict(a) for a in DEMO_PROPOSED_ACTIONS],
                0.61,
                20,
                DEMO_HEADLINE,
                list(DEMO_WHAT_CHANGED),
                None,
            )

    # -- history access -----------------------------------------------------

    def get_history(self) -> list[ReasoningResult]:
        return list(self._history)
