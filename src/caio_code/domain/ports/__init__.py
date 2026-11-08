"""Ports the domain depends on. Infrastructure implements them; nothing here
imports a SDK, a file, or a clock.

The dependency rule: domain -> nothing. application -> domain. infrastructure
and presentation -> application + domain. A port is the only place where an
outside capability is named.
"""

from __future__ import annotations

from caio_code.domain.ports.gateway import ModelGateway, ModelReply
from caio_code.domain.ports.scorer import RelevanceScorer, ScoredMessage
from caio_code.domain.ports.storage import ResultRecord, ResultStore, TranscriptStore
from caio_code.domain.ports.summarizer import Summarizer, SummaryResult
from caio_code.domain.ports.time import Clock, IdentifierFactory
from caio_code.domain.ports.tokenizer import TokenCounter

__all__ = [
    "Clock",
    "IdentifierFactory",
    "ModelGateway",
    "ModelReply",
    "RelevanceScorer",
    "ResultRecord",
    "ResultStore",
    "ScoredMessage",
    "Summarizer",
    "SummaryResult",
    "TokenCounter",
    "TranscriptStore",
]
