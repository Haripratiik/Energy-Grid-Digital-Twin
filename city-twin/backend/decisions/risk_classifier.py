from .models import ProposedAction, RiskLevel


class RiskClassifier:
    """Scores ProposedAction objects into RiskLevel tiers."""

    @staticmethod
    def classify(action: ProposedAction) -> RiskLevel:
        if action.action_type == "ISLANDING":
            return RiskLevel.EMERGENCY
        if abs(action.estimated_impact_mw) > 100:
            return RiskLevel.EMERGENCY
        if not action.reversible:
            return RiskLevel.CRITICAL
        if action.action_type == "LINE_SWITCH" and abs(action.estimated_impact_mw) > 30:
            return RiskLevel.CRITICAL
        if abs(action.estimated_impact_mw) > 50:
            return RiskLevel.CRITICAL
        if action.confidence < 0.65:
            return RiskLevel.CRITICAL
        if abs(action.estimated_impact_mw) > 10:
            return RiskLevel.CONTROLLED
        return RiskLevel.ADVISORY
