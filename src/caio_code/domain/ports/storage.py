"""Persistence ports: transcripts in, results out."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from caio_code.domain.conversation.messages import Transcript


@dataclass(frozen=True, slots=True)
class ResultRecord:
    """One row of an experiment report, serializable as-is."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TranscriptStore(Protocol):
    """Reads and writes transcripts, one file per session."""

    def save(self, session_id: str, transcript: Transcript) -> Path:
        """Persist a transcript and return where it went."""

    def load(self, session_id: str) -> Transcript:
        """Load a transcript. Raises StorageError when absent or corrupt."""

    def list_sessions(self) -> Sequence[str]:
        """Known session ids, sorted."""


@runtime_checkable
class ResultStore(Protocol):
    """Appends result records, one JSONL file per experiment run."""

    def append(self, run_id: str, record: ResultRecord) -> None:
        """Append one record, flushing so a crash keeps the previous ones."""

    def read(self, run_id: str) -> Sequence[ResultRecord]:
        """Every record of a run, in write order."""

    def path_of(self, run_id: str) -> Path:
        """Where a run's records live."""
