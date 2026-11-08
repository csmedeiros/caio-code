"""Decision-model adapters: TypeSafe Jev, the offline stub, and the composed uses.

Jev answers typed questions with probabilities; it is not a chat model and never
appears behind the gateway/summarizer ports (ADR 0005). This package implements
the ``DecisionModel`` port and the two uses the agent makes of it: relevance
scoring for message selection and advisory tool-risk assessment.
"""

from __future__ import annotations

from caio_code.infrastructure.decision.factory import (
    build_decision_model,
    build_decision_scorer,
)
from caio_code.infrastructure.decision.risk import DecisionRiskAdvisor, RiskAssessment
from caio_code.infrastructure.decision.scorer import DecisionRelevanceScorer
from caio_code.infrastructure.decision.stub import StubDecisionModel
from caio_code.infrastructure.decision.typesafe import TypeSafeDecisionModel

__all__ = [
    "DecisionRelevanceScorer",
    "DecisionRiskAdvisor",
    "RiskAssessment",
    "StubDecisionModel",
    "TypeSafeDecisionModel",
    "build_decision_model",
    "build_decision_scorer",
]
