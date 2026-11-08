"""Model adapters: stub, OpenAI-compatible, and the provider factory.

TypeSafe is deliberately absent: Jev is a decision model, not a chat model. It
lives in :mod:`caio_code.infrastructure.decision` behind the decision port
(ADR 0005).
"""

from __future__ import annotations

from caio_code.infrastructure.llm.factory import (
    build_gateway,
    build_scorer,
    build_summarizer,
)
from caio_code.infrastructure.llm.openai_compatible import (
    ModelRelevanceScorer,
    OpenAICompatibleGateway,
    OpenAICompatibleSummarizer,
)
from caio_code.infrastructure.llm.stub import StubGateway, StubScorer, StubSummarizer

__all__ = [
    "ModelRelevanceScorer",
    "OpenAICompatibleGateway",
    "OpenAICompatibleSummarizer",
    "StubGateway",
    "StubScorer",
    "StubSummarizer",
    "build_gateway",
    "build_scorer",
    "build_summarizer",
]
