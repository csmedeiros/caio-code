"""Evaluation domain: dataset cases, probes, trial scoring and aggregation."""

from __future__ import annotations

from caio_code.domain.evaluation.cases import (
    CriticalFact,
    EvalDataset,
    HistoryCase,
    Probe,
    answer_matches,
    normalize_answer,
)
from caio_code.domain.evaluation.scoring import (
    ArmAggregate,
    ExperimentReport,
    ProbeScore,
    TrialResult,
    pass_at_k,
)

__all__ = [
    "ArmAggregate",
    "CriticalFact",
    "EvalDataset",
    "ExperimentReport",
    "HistoryCase",
    "Probe",
    "ProbeScore",
    "TrialResult",
    "answer_matches",
    "normalize_answer",
    "pass_at_k",
]
