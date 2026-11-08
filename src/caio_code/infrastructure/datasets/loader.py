"""Loading and describing the frozen long-history dataset.

``load_dataset`` reads every ``case-*.json`` in a directory in sorted order
plus the ``dataset.json`` manifest, and validates each case through the codec.
A missing directory, an empty one, a case that fails validation or a manifest
that disagrees with the files on disk all raise
:class:`~caio_code.domain.errors.DatasetError`: the experiment must stop before
it measures a dataset that is not the one the thesis describes.

``describe`` produces the table Chapter 4 reports -- size, proxy token cost,
fact positions and the largest tool output per case -- using the same
``CharProxyTokenCounter`` the policies use, so the numbers in the thesis and
the numbers the agent sees cannot drift apart.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from caio_code.domain.errors import DatasetError
from caio_code.domain.evaluation.cases import POSITIONS, EvalDataset, HistoryCase
from caio_code.domain.ports.tokenizer import TokenCounter
from caio_code.infrastructure.datasets.codec import case_from_dict, dataset_from_dict
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

CASE_GLOB = "case-*.json"
MANIFEST_NAME = "dataset.json"
DEFAULT_DATASET_NAME = "long_histories"


@dataclass(frozen=True, slots=True)
class ToolOutputStats:
    """The single largest tool result of a case."""

    message_id: str
    name: str
    chars: int
    lines: int


@dataclass(frozen=True, slots=True)
class CaseStats:
    """Everything the thesis reports about one case."""

    case_id: str
    messages: int
    chars: int
    proxy_tokens: int
    window_multiples: float
    tool_results: int
    facts_by_position: dict[str, int]
    probes: int
    pinned_messages: int
    largest_tool_output: ToolOutputStats | None

    @property
    def total_facts(self) -> int:
        return sum(self.facts_by_position.values())


@dataclass(frozen=True, slots=True)
class DatasetStats:
    """Per-case stats plus the dataset-level totals."""

    name: str
    seed: int
    generator: str
    window_tokens: int
    counter_name: str
    cases: tuple[CaseStats, ...]

    @property
    def case_count(self) -> int:
        return len(self.cases)

    @property
    def total_messages(self) -> int:
        return sum(case.messages for case in self.cases)

    @property
    def total_chars(self) -> int:
        return sum(case.chars for case in self.cases)

    @property
    def total_proxy_tokens(self) -> int:
        return sum(case.proxy_tokens for case in self.cases)

    @property
    def total_probes(self) -> int:
        return sum(case.probes for case in self.cases)

    @property
    def total_facts(self) -> int:
        return sum(case.total_facts for case in self.cases)

    @property
    def facts_by_position(self) -> dict[str, int]:
        totals = {position: 0 for position in POSITIONS}
        for case in self.cases:
            for position, count in case.facts_by_position.items():
                totals[position] = totals.get(position, 0) + count
        return totals

    @property
    def min_window_multiples(self) -> float:
        return min((case.window_multiples for case in self.cases), default=0.0)

    @property
    def max_window_multiples(self) -> float:
        return max((case.window_multiples for case in self.cases), default=0.0)


def _read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"{path}: cannot read case file: {exc}"
        raise DatasetError(msg) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"{path}: invalid JSON: {exc}"
        raise DatasetError(msg) from exc


def load_dataset(directory: Path, *, limit: int | None = None) -> EvalDataset:
    """Read a dataset directory into a validated :class:`EvalDataset`.

    ``limit`` keeps only the first ``limit`` cases in sorted file order, which
    is how a short smoke run uses the same frozen files as the full experiment.
    """
    if not isinstance(directory, Path):
        msg = f"directory must be a Path, got {directory!r}"
        raise DatasetError(msg)
    if not directory.is_dir():
        msg = f"dataset directory does not exist: {directory}"
        raise DatasetError(msg)
    if limit is not None and limit <= 0:
        msg = f"limit must be positive or None, got {limit}"
        raise DatasetError(msg)

    case_paths = sorted(directory.glob(CASE_GLOB))
    if not case_paths:
        msg = f"dataset directory has no {CASE_GLOB} file: {directory}"
        raise DatasetError(msg)
    if limit is not None:
        case_paths = case_paths[:limit]

    cases = tuple(
        case_from_dict(_read_json(path), source=path.name) for path in case_paths
    )

    manifest_path = directory / MANIFEST_NAME
    if manifest_path.is_file():
        return dataset_from_dict(
            _read_json(manifest_path),
            cases,
            source=manifest_path.name,
            require_all_listed=limit is None,
        )

    return EvalDataset(name=directory.name or DEFAULT_DATASET_NAME, cases=cases)


def largest_tool_output(case: HistoryCase) -> ToolOutputStats | None:
    """The biggest single tool result, or ``None`` when the case has none."""
    best: ToolOutputStats | None = None
    for message in case.messages:
        if not message.is_tool_result():
            continue
        stats = ToolOutputStats(
            message_id=message.id,
            name=message.name or "",
            chars=len(message.text),
            lines=message.text.count("\n") + 1 if message.text else 0,
        )
        if best is None or stats.chars > best.chars:
            best = stats
    return best


def describe_case(
    case: HistoryCase,
    *,
    window_tokens: int,
    counter: TokenCounter | None = None,
) -> CaseStats:
    """Stats of one case, counted with the same proxy the policies use."""
    if window_tokens <= 0:
        msg = f"window_tokens must be positive, got {window_tokens}"
        raise DatasetError(msg)
    active = counter or CharProxyTokenCounter()
    tokens = active.count_transcript(case.transcript)
    positions = {position: 0 for position in POSITIONS}
    for fact in case.facts:
        positions[fact.position] = positions.get(fact.position, 0) + 1
    return CaseStats(
        case_id=case.id,
        messages=len(case.messages),
        chars=case.char_count,
        proxy_tokens=tokens,
        window_multiples=round(tokens / window_tokens, 2),
        tool_results=sum(1 for message in case.messages if message.is_tool_result()),
        facts_by_position=positions,
        probes=len(case.probes),
        pinned_messages=len(case.transcript.pinned_indices()),
        largest_tool_output=largest_tool_output(case),
    )


def describe(
    dataset: EvalDataset,
    *,
    window_tokens: int = 0,
    counter: TokenCounter | None = None,
) -> DatasetStats:
    """Per-case stats for the whole dataset.

    ``window_tokens`` defaults to :data:`caio_code.config.WindowConfig.tokens`,
    read lazily so that a caller may report the table against a different
    window without importing config here.
    """
    resolved = window_tokens
    if not resolved:
        from caio_code.config import WindowConfig

        resolved = WindowConfig().tokens
    active = counter or CharProxyTokenCounter()
    return DatasetStats(
        name=dataset.name,
        seed=dataset.seed,
        generator=dataset.generator,
        window_tokens=resolved,
        counter_name=active.name,
        cases=tuple(
            describe_case(case, window_tokens=resolved, counter=active)
            for case in dataset.cases
        ),
    )


def format_stats(stats: DatasetStats) -> str:
    """The stats table as fixed-width text, ready for the thesis and the logs."""
    header = (
        f"{'case':<34} {'msgs':>5} {'chars':>8} {'tokens':>7} {'x window':>8} "
        f"{'tools':>5} {'e/m/l':>7} {'probes':>6} {'pin':>4} {'largest tool output':>22}"
    )
    lines = [
        f"dataset {stats.name!r} seed={stats.seed} generator={stats.generator!r}",
        f"counter {stats.counter_name} window {stats.window_tokens} tokens",
        header,
        "-" * len(header),
    ]
    for case in stats.cases:
        facts = case.facts_by_position
        spread = "/".join(str(facts.get(position, 0)) for position in POSITIONS)
        largest = case.largest_tool_output
        biggest = (
            f"{largest.chars:,} ch / {largest.lines:,} ln" if largest is not None else "-"
        )
        lines.append(
            f"{case.case_id:<34} {case.messages:>5} {case.chars:>8,} {case.proxy_tokens:>7,} "
            f"{case.window_multiples:>8.2f} {case.tool_results:>5} {spread:>7} "
            f"{case.probes:>6} {case.pinned_messages:>4} {biggest:>22}"
        )
    totals = stats.facts_by_position
    lines.append("-" * len(header))
    lines.append(
        f"{'TOTAL':<34} {stats.total_messages:>5} {stats.total_chars:>8,} "
        f"{stats.total_proxy_tokens:>7,} {'':>8} {'':>5} "
        f"{'/'.join(str(totals.get(position, 0)) for position in POSITIONS):>7} "
        f"{stats.total_probes:>6}"
    )
    lines.append(
        f"window multiples: min {stats.min_window_multiples:.2f} "
        f"max {stats.max_window_multiples:.2f}"
    )
    return "\n".join(lines)


def case_ids(dataset: EvalDataset) -> tuple[str, ...]:
    """Case ids in dataset order."""
    return tuple(case.id for case in dataset.cases)


def validate_positions(cases: Sequence[HistoryCase]) -> None:
    """Every case must state facts in all three positions, or the design is broken."""
    for case in cases:
        seen = {fact.position for fact in case.facts}
        missing = [position for position in POSITIONS if position not in seen]
        if missing:
            msg = f"case {case.id!r} has no fact in position(s) {missing}"
            raise DatasetError(msg)


__all__ = [
    "CASE_GLOB",
    "DEFAULT_DATASET_NAME",
    "MANIFEST_NAME",
    "CaseStats",
    "DatasetStats",
    "ToolOutputStats",
    "case_ids",
    "describe",
    "describe_case",
    "format_stats",
    "largest_tool_output",
    "load_dataset",
    "validate_positions",
]
