from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    ADVISORY = "ADVISORY"      # auto-execute in both modes
    CONTROLLED = "CONTROLLED"  # semi: 30s countdown; full-auto: execute immediately
    CRITICAL = "CRITICAL"      # semi: manual approval required; full-auto: 10s window
    EMERGENCY = "EMERGENCY"    # ALWAYS requires manual approval (even in full-auto)


class ProposedAction(BaseModel):
    action_type: Literal["LOAD_SHED", "GEN_SETPOINT", "LINE_SWITCH", "TRANSFORMER_TAP", "ISLANDING"]
    target_rid: str
    parameters: dict[str, Any]    # e.g. {"delta_mw": -40} or {"target_mw": 250}
    rationale: str                # from GPT-4o
    confidence: float             # 0.0 – 1.0
    estimated_impact_mw: float
    reversible: bool


class GridDecision(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    risk_level: RiskLevel
    action: ProposedAction
    triggered_by_alert_id: Optional[str] = None
    status: Literal["PENDING", "APPROVED", "REJECTED", "EXECUTED", "EXPIRED", "REVERTED"] = "PENDING"
    expires_at: Optional[datetime] = None
    executed_by: Optional[str] = None     # "AI_AUTO" or "OPERATOR"
    pre_state_snapshot: dict = Field(default_factory=dict)
    post_state_snapshot: Optional[dict] = None
    outcome_delta: Optional[dict] = None  # measured improvement/degradation
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AutonomousMode(str, Enum):
    SEMI = "SEMI"
    FULL_AUTO = "FULL_AUTO"
