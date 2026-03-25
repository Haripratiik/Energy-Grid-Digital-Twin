"""Conversational chat engine backed by OpenAI GPT-4o.

Supports multi-turn conversations with grid telemetry injected as context.
Falls back to demo responses when no API key is available.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel

from reasoning.cached_responses import (
    DEMO_CASCADE_RESPONSE_TEXT,
    DEMO_HEADLINE,
    DEMO_PROPOSED_ACTIONS,
    DEMO_WHAT_CHANGED,
)
from .store import ChatMessage

if TYPE_CHECKING:
    from physics.swing import GridState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured output schema for chat responses
# ---------------------------------------------------------------------------

class ChatActionParameters(BaseModel):
    delta_mw: Optional[float] = None
    target_pct: Optional[float] = None
    tap_position: Optional[int] = None
    switch_open: Optional[bool] = None

class ChatResponseAction(BaseModel):
    action_type: str
    target_rid: str
    parameters: ChatActionParameters
    rationale: str
    confidence: float
    estimated_impact_mw: float
    reversible: bool


class ChatResponse(BaseModel):
    message_text: str
    what_changed: list[str] = []
    proposed_actions: list[ChatResponseAction] = []
    cascade_probability: float = 0.0
    time_horizon_seconds: int = 0


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are GRID Assistant, an AI-powered conversational aide for operators of a \
city-scale power grid digital twin. The twin simulates an 80-bus, \
3-voltage-tier (400 kV / 132 kV / 33 kV) city power system with nuclear, \
hydro, wind, solar, and gas generators.

You can:
- Answer ANY question about the grid, the application, power engineering, \
or how this digital twin works.
- Summarize grid health in plain language.
- Explain what specific metrics mean (frequency, loading, voltage, etc.).
- Propose corrective actions when the grid is stressed.
- Have natural multi-turn conversations; refer to earlier messages in the \
thread if relevant.

TONE: Friendly, clear, concise. Keep answers SHORT — 2-4 sentences max \
unless the user asks for detail. Lead with the practical answer. Avoid jargon.

LIVE TELEMETRY: Every message includes a snapshot of current grid telemetry \
injected by the system. Use it to give real-time-aware answers. If the user \
asks about grid status, reference the actual numbers.

RESPONSE FORMAT (JSON, all fields required):

message_text — Your conversational reply. This is the main text the \
operator sees. Can be multiple paragraphs, use markdown for clarity. \
Always answer the user's question directly here.

what_changed — 0-4 short bullet strings about key telemetry observations. \
Only include when grid status is noteworthy or the user asked about it. \
Empty list is fine for general questions.

proposed_actions — Ordered list of corrective actions. Only include when \
the grid needs attention or the user asked for recommendations. Empty list \
is fine. Each action MUST have:
  action_type: LOAD_SHED | GEN_SETPOINT | LINE_SWITCH | TRANSFORMER_TAP | ISLANDING
  target_rid: Palantir RID (e.g. "ri.city-grid.main.load-bus.14")
  parameters: object with optional keys: delta_mw, target_pct, tap_position, switch_open
  rationale: 1-sentence justification
  confidence: 0.0-1.0
  estimated_impact_mw: MW impact (negative = reduction)
  reversible: true/false

cascade_probability — float 0.0-1.0, set to 0 unless there's real risk.
time_horizon_seconds — seconds until cascade if no action, 0 if not applicable.

For general questions (e.g. "how do I use this app?", "what is frequency?"), \
reply naturally in message_text with empty what_changed, empty \
proposed_actions, cascade_probability 0, time_horizon_seconds 0."""

_MAX_CONTEXT_MESSAGES = 20


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ChatEngine:
    """Multi-turn conversational engine wrapping OpenAI GPT-4o."""

    def __init__(self, api_key: str, *, demo_mode: bool = False) -> None:
        self._api_key = api_key
        self._demo_mode = demo_mode
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

    @staticmethod
    def _build_telemetry_block(state: GridState) -> str:
        overloaded = [
            ln for ln in state.lines
            if ln.flow_pct_of_limit > 0.8 and not ln.tripped
        ]
        tripped = [ln for ln in state.lines if ln.tripped]

        parts = [
            "=== LIVE GRID TELEMETRY ===",
            f"Sim time: {state.sim_time_s:.1f}s",
            f"Frequency: {state.system_frequency_hz:.3f} Hz "
            f"(deviation: {state.system_frequency_hz - 60.0:+.3f} Hz)",
            f"Generation: {state.total_generation_mw:.1f} MW | "
            f"Load: {state.total_load_mw:.1f} MW | "
            f"Losses: {state.total_loss_mw:.1f} MW",
        ]
        if overloaded:
            parts.append(
                "Overloaded lines: "
                + ", ".join(
                    f"{ln.id} at {ln.flow_pct_of_limit * 100:.0f}%"
                    for ln in overloaded
                )
            )
        if tripped:
            parts.append("Tripped lines: " + ", ".join(ln.id for ln in tripped))

        gen_lines = []
        for g in state.generators:
            status = "ONLINE" if g.online else "OFFLINE"
            gen_lines.append(
                f"  Bus {g.bus_id} ({g.gen_type}) {status} "
                f"{g.electrical_power_mw:.0f} MW"
            )
        parts.append("Generators:\n" + "\n".join(gen_lines))

        alerts = state.active_alerts or []
        if alerts:
            alert_lines = []
            for a in alerts[-10:]:
                sev = a.get("severity", "?")
                atype = a.get("type", "?")
                summary = a.get("summary", "")
                alert_lines.append(f"  [{sev}] {atype}: {summary}")
            parts.append(f"Active alerts ({len(alerts)} total):\n" + "\n".join(alert_lines))
        else:
            parts.append("Active alerts: none")

        offline_gens = [g for g in state.generators if not g.online]
        if offline_gens:
            parts.append("*** OFFLINE GENERATORS: " + ", ".join(
                f"Bus {g.bus_id} ({g.gen_type})" for g in offline_gens
            ) + " ***")

        parts.append("=== END TELEMETRY ===")
        return "\n".join(parts)

    @staticmethod
    def _enrich_actions(actions: list[dict]) -> list[dict]:
        from decisions.models import ProposedAction
        from decisions.risk_classifier import RiskClassifier

        enriched = []
        for a in actions:
            try:
                clean = {k: v for k, v in a.items() if k != "risk_level"}
                pa = ProposedAction(**clean)
                a["risk_level"] = RiskClassifier.classify(pa).value
            except Exception:
                a["risk_level"] = "ADVISORY"
            enriched.append(a)
        return enriched

    def respond(
        self,
        user_content: str,
        history: list[ChatMessage],
        state: GridState,
    ) -> ChatMessage:
        """Generate an assistant response given user input, history, and live state."""
        if self._demo_mode:
            return self._demo_respond(user_content, state)

        return self._llm_respond(user_content, history, state)

    def _llm_respond(
        self,
        user_content: str,
        history: list[ChatMessage],
        state: GridState,
    ) -> ChatMessage:
        client = self._get_client()
        telemetry = self._build_telemetry_block(state)

        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "system", "content": telemetry},
        ]

        for msg in history[-_MAX_CONTEXT_MESSAGES:]:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": user_content})

        from shared.rate_limiter import chat_limiter
        if not chat_limiter.wait_and_acquire(timeout=25.0):
            logger.warning("Rate limiter timeout for chat — using demo fallback")
            return self._demo_respond(user_content, state)

        try:
            response = client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=messages,
                response_format=ChatResponse,
                max_tokens=600,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise ValueError("No parsed response")

            actions = []
            for a in parsed.proposed_actions:
                d = a.model_dump()
                params = {k: v for k, v in d.get("parameters", {}).items() if v is not None}
                d["parameters"] = params
                actions.append(d)
            actions = self._enrich_actions(actions)

            structured: dict[str, Any] = {
                "what_changed": parsed.what_changed,
                "proposed_actions": actions,
                "cascade_probability": parsed.cascade_probability,
                "time_horizon_seconds": parsed.time_horizon_seconds,
            }

            return ChatMessage(
                role="assistant",
                content=parsed.message_text,
                structured=structured,
            )

        except Exception:
            logger.exception("Chat LLM call failed — using demo fallback")
            return self._demo_respond(user_content, state)

    def _demo_respond(self, user_content: str, state: GridState) -> ChatMessage:
        lower = user_content.lower()

        freq_dev = state.system_frequency_hz - 60.0
        overloaded = [
            ln for ln in state.lines
            if ln.flow_pct_of_limit > 0.8 and not ln.tripped
        ]
        tripped_lines = [ln for ln in state.lines if ln.tripped]
        tripped_trafos = [t for t in state.transformers if t.status == "TRIPPED"]
        offline_gens = [g for g in state.generators if not g.online]
        alert_count = len(state.active_alerts) if state.active_alerts else 0

        # --- Grid health / status / summary (check FIRST, before generic help) ---
        if any(kw in lower for kw in [
            "health", "status", "summary", "summarize", "summarise",
            "freq", "frequency", "load", "generation", "worry",
            "overload", "trip", "alert", "grid", "power",
            "generator", "line", "transformer", "voltage", "bus",
        ]):
            health = "nominal" if abs(freq_dev) < 0.05 else (
                "under stress" if abs(freq_dev) < 0.2 else "degraded"
            )
            text = f"**Grid Health: {health.title()}**\n\n"
            text += (
                f"Frequency is **{state.system_frequency_hz:.3f} Hz** "
                f"({freq_dev:+.3f} Hz deviation). "
                f"Generation: **{state.total_generation_mw:.0f} MW** | "
                f"Load: **{state.total_load_mw:.0f} MW** | "
                f"Losses: **{state.total_loss_mw:.1f} MW**.\n\n"
            )
            issues: list[str] = []
            if overloaded:
                names = ", ".join(f"{ln.id} ({ln.flow_pct_of_limit*100:.0f}%)" for ln in overloaded[:5])
                issues.append(f"**{len(overloaded)} overloaded line(s)**: {names}")
            if tripped_lines:
                issues.append(f"**{len(tripped_lines)} tripped line(s)**: {', '.join(ln.id for ln in tripped_lines[:5])}")
            if tripped_trafos:
                issues.append(f"**{len(tripped_trafos)} tripped transformer(s)**")
            if offline_gens:
                names = ", ".join(f"Bus {g.bus_id} ({g.gen_type})" for g in offline_gens)
                issues.append(f"**{len(offline_gens)} offline generator(s)**: {names}")
            if alert_count > 0:
                crit = sum(1 for a in (state.active_alerts or []) if a.get("severity") == "CRITICAL")
                issues.append(f"**{alert_count} alert(s)** ({crit} critical)")

            if issues:
                text += "**Current issues:**\n" + "\n".join(f"- {i}" for i in issues)
            else:
                text += "No issues detected. All systems are operating within normal parameters."

            what_changed = [
                f"Frequency: {state.system_frequency_hz:.3f} Hz ({freq_dev:+.3f})",
                f"Generation: {state.total_generation_mw:.0f} MW",
                f"Load: {state.total_load_mw:.0f} MW",
            ]
            if overloaded:
                what_changed.append(f"{len(overloaded)} line(s) above 80% loading")
            if tripped_lines:
                what_changed.append(f"{len(tripped_lines)} line(s) tripped")

            return ChatMessage(
                role="assistant",
                content=text,
                structured={
                    "what_changed": what_changed[:4],
                    "proposed_actions": [],
                    "cascade_probability": min(0.8, abs(freq_dev) * 3),
                    "time_horizon_seconds": 30 if abs(freq_dev) > 0.1 else 0,
                },
            )

        # --- Recommendations / what to do ---
        if any(kw in lower for kw in ["recommend", "should", "action", "fix", "solve", "do about"]):
            actions = [dict(a) for a in DEMO_PROPOSED_ACTIONS]
            actions = self._enrich_actions(actions)
            text = (
                f"Based on the current state "
                f"(frequency at **{state.system_frequency_hz:.3f} Hz**), "
                f"here are my recommendations:\n\n"
            )
            for i, a in enumerate(actions, 1):
                text += f"{i}. **{a['action_type']}** on `{a['target_rid']}` — {a['rationale']}\n"
            return ChatMessage(
                role="assistant",
                content=text,
                structured={
                    "what_changed": list(DEMO_WHAT_CHANGED),
                    "proposed_actions": actions,
                    "cascade_probability": 0.61,
                    "time_horizon_seconds": 20,
                },
            )

        # --- Help / how to use (generic — checked AFTER grid-specific) ---
        if any(kw in lower for kw in ["use this", "help me", "what can you", "how do i", "explain app", "tutorial"]):
            text = (
                "Here's what you can do with the **GRID Assistant**:\n\n"
                "- **Ask about grid health**: \"How is the grid?\" or \"Are any lines overloaded?\"\n"
                "- **Get recommendations**: \"What should I do about the frequency drop?\"\n"
                "- **Learn about the system**: \"What generators do we have?\" or \"How does the 400kV ring work?\"\n"
                "- **Inject faults**: Use the Fault Injector panel to simulate line trips, load spikes, etc.\n"
                "- **Manage decisions**: The Decision Queue shows AI-proposed actions you can approve or reject.\n\n"
                "Just ask me anything about the grid and I'll answer using live data!"
            )
            return ChatMessage(
                role="assistant",
                content=text,
                structured={
                    "what_changed": [],
                    "proposed_actions": [],
                    "cascade_probability": 0.0,
                    "time_horizon_seconds": 0,
                },
            )

        # --- Fallback: give a contextual response based on current grid state ---
        text = (
            f"The grid is at **{state.system_frequency_hz:.3f} Hz** "
            f"with **{state.total_generation_mw:.0f} MW** generation and "
            f"**{state.total_load_mw:.0f} MW** load. "
        )
        if abs(freq_dev) > 0.1 or overloaded or tripped_lines:
            text += (
                "There are some conditions worth monitoring. "
                "Ask me to **summarize grid health** or **recommend actions** for more detail."
            )
        else:
            text += "Everything looks healthy. Feel free to ask me anything about the grid!"

        return ChatMessage(
            role="assistant",
            content=text,
            structured={
                "what_changed": [
                    f"Frequency: {state.system_frequency_hz:.3f} Hz",
                    f"Gen/Load: {state.total_generation_mw:.0f}/{state.total_load_mw:.0f} MW",
                ],
                "proposed_actions": [],
                "cascade_probability": 0.0,
                "time_horizon_seconds": 0,
            },
        )
