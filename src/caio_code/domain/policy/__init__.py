"""Context-management strategies: the independent variable of the experiment."""

from __future__ import annotations

from caio_code.domain.policy.base import (
    ContextPolicy,
    PipelineDecision,
    PolicyDecision,
    PolicyPipeline,
    PolicyRequest,
    Removal,
    StepOutcome,
    Substitution,
)
from caio_code.domain.policy.compaction import CompactionPlanner, summary_message_from
from caio_code.domain.policy.full_history import FullHistoryPolicy
from caio_code.domain.policy.message_selection import MessageSelectionPolicy
from caio_code.domain.policy.sliding_window import SlidingWindowPolicy
from caio_code.domain.policy.structure_repair import StructureRepairPolicy
from caio_code.domain.policy.tool_output import ToolOutputTruncationPolicy, TruncationLimits

__all__ = [
    "CompactionPlanner",
    "ContextPolicy",
    "FullHistoryPolicy",
    "MessageSelectionPolicy",
    "PipelineDecision",
    "PolicyDecision",
    "PolicyPipeline",
    "PolicyRequest",
    "Removal",
    "SlidingWindowPolicy",
    "StepOutcome",
    "StructureRepairPolicy",
    "Substitution",
    "ToolOutputTruncationPolicy",
    "TruncationLimits",
    "summary_message_from",
]
