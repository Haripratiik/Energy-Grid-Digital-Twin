from __future__ import annotations
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from .models import AutonomousMode, GridDecision, ProposedAction, RiskLevel
from .risk_classifier import RiskClassifier
from .action_executor import ActionExecutor
from .outcome_monitor import OutcomeMonitor
from .decision_log import DecisionLog
from .safety_verifier import SafetyVerifier

if TYPE_CHECKING:
    from physics.swing import GridSimulator, GridState
    from reasoning.engine import ReasoningEngine

logger = logging.getLogger(__name__)

CONTROLLED_COUNTDOWN_S = 15.0
CRITICAL_AUTO_WINDOW_S = 8.0
FULL_AUTO_DISPLAY_S = 3.0
OUTCOME_WAIT_S = 5.0


class AutonomousEngine:
    def __init__(self, simulator: GridSimulator, reasoning: ReasoningEngine,
                 *, verify_actions: bool = True):
        self._sim = simulator
        self._reasoning = reasoning
        self._executor = ActionExecutor(simulator)
        self._verifier = SafetyVerifier()
        self._verify_actions = verify_actions
        self._log = DecisionLog()
        self._mode = AutonomousMode.SEMI
        self._last_analysis_time = 0.0
        self._analysis_cooldown = 15.0
        self._analyzing = False
        self._recent_alert_types: dict[str, float] = {}
        self._alert_dedup_window = 12.0
        self._pending_outcomes: list[tuple[GridDecision, float]] = []  # (decision, execute_time)

    @property
    def mode(self) -> AutonomousMode:
        return self._mode

    @mode.setter
    def mode(self, value: AutonomousMode):
        old = self._mode
        self._mode = value
        logger.info("Autonomous mode changed to: %s", value)
        if old != value:
            stale = self._log.get_pending()
            for d in stale:
                d.status = "EXPIRED"
            if stale:
                logger.info("Expired %d stale pending decisions from mode switch", len(stale))
            self._recent_alert_types.clear()

    @property
    def decision_log(self) -> DecisionLog:
        return self._log

    async def on_alert(self, alert_type: str, severity: str, state: GridState, alert_id: str) -> None:
        """Called when a new alert fires. Triggers analysis in a background thread."""
        if severity not in ("CRITICAL", "WARNING"):
            return

        now = time.time()
        if now - self._last_analysis_time < self._analysis_cooldown:
            return
        if self._analyzing:
            return

        self._recent_alert_types = {
            k: v for k, v in self._recent_alert_types.items()
            if now - v < self._alert_dedup_window
        }
        if alert_type in self._recent_alert_types:
            return
        self._recent_alert_types[alert_type] = now

        self._last_analysis_time = now
        self._analyzing = True

        trigger_label = "AUTO_CRITICAL" if severity == "CRITICAL" else "AUTO_WARNING"
        logger.info("AutonomousEngine: analyzing for %s alert %s (%s)", severity, alert_id[:8], alert_type)

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, self._reasoning.analyze, state, None, trigger_label, alert_id,
            )
        except Exception:
            logger.exception("Analysis failed")
            return
        finally:
            self._analyzing = False

        if not result or not result.proposed_actions:
            return

        pre_snapshot = OutcomeMonitor.capture_snapshot(state)

        for pa_dict in result.proposed_actions:
            if isinstance(pa_dict, dict):
                clean = {k: v for k, v in pa_dict.items() if k != "risk_level"}
                proposed = ProposedAction(**clean)
            else:
                proposed = pa_dict
            risk = RiskClassifier.classify(proposed)
            decision = GridDecision(
                risk_level=risk,
                action=proposed,
                triggered_by_alert_id=alert_id,
                pre_state_snapshot=pre_snapshot,
            )

            self._apply_mode_policy(decision)
            self._log.record(decision)

    def _apply_mode_policy(self, decision: GridDecision) -> None:
        """Apply the autonomous mode policy to determine what happens to this decision."""
        risk = decision.risk_level
        mode = self._mode

        if risk == RiskLevel.EMERGENCY:
            decision.status = "PENDING"
            decision.expires_at = None  # no expiry — must be manually handled
            logger.info("EMERGENCY decision %s queued for manual approval", decision.id[:8])
            return

        if mode == AutonomousMode.SEMI:
            if risk == RiskLevel.ADVISORY:
                self._auto_execute(decision)
            elif risk == RiskLevel.CONTROLLED:
                decision.status = "PENDING"
                decision.expires_at = datetime.now(timezone.utc) + timedelta(seconds=CONTROLLED_COUNTDOWN_S)
                logger.info("CONTROLLED decision %s queued with %ds countdown", decision.id[:8], CONTROLLED_COUNTDOWN_S)
            else:  # CRITICAL
                decision.status = "PENDING"
                decision.expires_at = None
                logger.info("CRITICAL decision %s requires manual approval", decision.id[:8])

        elif mode == AutonomousMode.FULL_AUTO:
            decision.status = "PENDING"
            decision.expires_at = datetime.now(timezone.utc) + timedelta(seconds=FULL_AUTO_DISPLAY_S)
            decision.executed_by = "AI_AUTO"
            logger.info("FULL_AUTO: %s decision %s queued — auto-executes in %ds", risk.value, decision.id[:8], FULL_AUTO_DISPLAY_S)

    def _verify_and_execute(self, decision: GridDecision) -> bool:
        """Physics safety gate: re-solve power flow for the action before executing.

        Rejects (does not execute) any action that fails to converge or worsens
        grid security — "AI proposes, physics guarantees safety."
        """
        if self._verify_actions:
            result = self._verifier.verify(self._sim.get_state(), decision.action)
            decision.verification = result.model_dump()
            if not result.safe:
                decision.status = "REJECTED"
                logger.warning("Safety verifier BLOCKED decision %s: %s",
                               decision.id[:8], result.reason)
                return False
        return self._executor.execute(decision)

    def _auto_execute(self, decision: GridDecision) -> None:
        success = self._verify_and_execute(decision)
        if success:
            self._pending_outcomes.append((decision, time.time()))
            logger.info("Auto-executed %s decision %s", decision.risk_level.value, decision.id[:8])
        else:
            if decision.status == "PENDING":
                decision.status = "EXPIRED"
                logger.warning("Auto-execute failed for %s — marked EXPIRED", decision.id[:8])

    def tick(self, state: GridState) -> None:
        """Called every simulation emit. Handles countdowns and outcome checks."""
        now = datetime.now(timezone.utc)

        for decision in self._log.get_pending():
            if decision.expires_at and now >= decision.expires_at:
                logger.info("Countdown expired — auto-executing decision %s", decision.id[:8])
                success = self._verify_and_execute(decision)
                if success:
                    self._pending_outcomes.append((decision, time.time()))
                else:
                    decision.status = "EXPIRED"
                    logger.warning("Execution failed for expired decision %s — marked EXPIRED", decision.id[:8])

        completed = []
        for i, (decision, exec_time) in enumerate(self._pending_outcomes):
            if time.time() - exec_time >= OUTCOME_WAIT_S:
                OutcomeMonitor.evaluate(decision, state)
                completed.append(i)

        for i in reversed(completed):
            self._pending_outcomes.pop(i)

    def approve(self, decision_id: str) -> bool:
        decision = self._log.get(decision_id)
        if not decision or decision.status != "PENDING":
            return False
        decision.executed_by = "OPERATOR"
        state = self._sim.get_state()
        decision.pre_state_snapshot = OutcomeMonitor.capture_snapshot(state)
        success = self._verify_and_execute(decision)
        if success:
            self._pending_outcomes.append((decision, time.time()))
        return success

    def reject(self, decision_id: str) -> bool:
        decision = self._log.get(decision_id)
        if not decision or decision.status != "PENDING":
            return False
        decision.status = "REJECTED"
        return True

    def revert(self, decision_id: str) -> bool:
        decision = self._log.get(decision_id)
        if not decision or decision.status != "EXECUTED":
            return False
        return self._executor.revert(decision)
