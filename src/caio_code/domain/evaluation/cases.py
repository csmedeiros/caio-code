"""Evaluation domain: cases, probes and the scoring of one trial.

The dataset is small on purpose -- five long histories with critical facts
placed early, in the middle and late -- because what Chapter 4 measures is the
difference between policies on the same input, not the size of the benchmark.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from caio_code.domain.conversation.messages import Message, Transcript
from caio_code.domain.errors import DatasetError

FactPosition = Literal["early", "middle", "late"]
POSITIONS: tuple[FactPosition, ...] = ("early", "middle", "late")

CaseVariant = Literal["full", "spill"]
VARIANTS: tuple[CaseVariant, ...] = ("full", "spill")
"""The truncation factor of the chat-replay experiment.

``full`` seeds the recorded tool outputs as-is; ``spill`` replaces every output
above the byte ceiling with a pointer to a spill file the agent can read back
during the probe round. Same history, same facts, same probes: the variant is
the only difference, which is what makes "does truncation change retention?"
answerable.
"""


@dataclass(frozen=True, slots=True)
class SpillFile:
    """One tool output moved out of the context into a file the agent can read.

    The text is kept in memory, never on disk: the replay tool server serves it
    when the agent reads the path back, which is what makes the spill variant
    deterministic and offline-testable.
    """

    path: str
    text: str
    source_message_id: str
    tool_name: str
    byte_count: int
    line_count: int

    def __post_init__(self) -> None:
        if not self.path:
            msg = "a spill file needs a path"
            raise DatasetError(msg)
        if not self.text:
            msg = f"spill file {self.path!r} is empty"
            raise DatasetError(msg)


@dataclass(frozen=True, slots=True)
class CriticalFact:
    """One fact the agent must still know at the end of a long session."""

    id: str
    statement: str
    answer: str
    aliases: tuple[str, ...] = ()
    position: FactPosition = "middle"
    message_index: int | None = None

    def __post_init__(self) -> None:
        if not self.id:
            msg = "a critical fact needs an id"
            raise DatasetError(msg)
        if not self.answer.strip():
            msg = f"fact {self.id!r} has an empty answer"
            raise DatasetError(msg)
        if self.position not in POSITIONS:
            msg = f"fact {self.id!r} has unknown position {self.position!r}"
            raise DatasetError(msg)

    @property
    def acceptable_answers(self) -> tuple[str, ...]:
        """Answer plus aliases, normalized for comparison."""
        return (self.answer, *self.aliases)


@dataclass(frozen=True, slots=True)
class Probe:
    """A question asked after the history, and the fact it tests."""

    id: str
    fact_id: str
    question: str
    expected: str
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.question.strip():
            msg = f"probe {self.id!r} has an empty question"
            raise DatasetError(msg)

    @property
    def acceptable_answers(self) -> tuple[str, ...]:
        return (self.expected, *self.aliases)


@dataclass(frozen=True, slots=True)
class HistoryCase:
    """One prebuilt long chat history with its facts and probes."""

    id: str
    description: str
    messages: tuple[Message, ...]
    facts: tuple[CriticalFact, ...]
    probes: tuple[Probe, ...]
    task: str = ""
    source: str = "synthetic"
    variant: CaseVariant = "full"
    spill_files: tuple[SpillFile, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not self.messages:
            msg = f"case {self.id!r} has no messages"
            raise DatasetError(msg)
        if not self.probes:
            msg = f"case {self.id!r} has no probes"
            raise DatasetError(msg)
        if self.variant not in VARIANTS:
            msg = f"case {self.id!r} has unknown variant {self.variant!r}"
            raise DatasetError(msg)
        if self.variant == "full" and self.spill_files:
            msg = f"case {self.id!r}: the full variant carries no spill files"
            raise DatasetError(msg)
        fact_ids = {fact.id for fact in self.facts}
        for probe in self.probes:
            if probe.fact_id not in fact_ids:
                msg = f"case {self.id!r}: probe {probe.id!r} references unknown fact {probe.fact_id!r}"
                raise DatasetError(msg)

    @property
    def transcript(self) -> Transcript:
        return Transcript(self.messages)

    @property
    def char_count(self) -> int:
        return sum(message.char_count() for message in self.messages)

    def fact(self, fact_id: str) -> CriticalFact:
        for candidate in self.facts:
            if candidate.id == fact_id:
                return candidate
        msg = f"case {self.id!r} has no fact {fact_id!r}"
        raise DatasetError(msg)


@dataclass(frozen=True, slots=True)
class EvalDataset:
    """The frozen set of cases an experiment runs over."""

    name: str
    cases: tuple[HistoryCase, ...]
    seed: int = 0
    generator: str = ""

    def __post_init__(self) -> None:
        if not self.cases:
            msg = f"dataset {self.name!r} is empty"
            raise DatasetError(msg)
        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids):
            msg = f"dataset {self.name!r} has duplicate case ids: {sorted(ids)}"
            raise DatasetError(msg)

    def __len__(self) -> int:
        return len(self.cases)

    def case(self, case_id: str) -> HistoryCase:
        for candidate in self.cases:
            if candidate.id == case_id:
                return candidate
        msg = f"dataset {self.name!r} has no case {case_id!r}"
        raise DatasetError(msg)

    def limited(self, count: int) -> EvalDataset:
        """First ``count`` cases, in dataset order."""
        if count <= 0:
            msg = f"count must be positive, got {count}"
            raise DatasetError(msg)
        return EvalDataset(
            name=self.name,
            cases=self.cases[:count],
            seed=self.seed,
            generator=self.generator,
        )


def normalize_answer(text: str) -> str:
    """Lowercase, collapse whitespace and strip surrounding punctuation."""
    collapsed = " ".join(text.split()).strip().lower()
    return collapsed.strip(" .,;:!?'\"()[]{}")


def answer_matches(text: str, acceptable: Sequence[str]) -> bool:
    """Alias matching: the normalized answer appears in the model's reply."""
    haystack = normalize_answer(text)
    if not haystack:
        return False
    for candidate in acceptable:
        needle = normalize_answer(candidate)
        if needle and needle in haystack:
            return True
    return False
