#!/usr/bin/env python
"""Deterministic generator of the frozen long-history evaluation dataset.

The five cases are the input of the Chapter 4 experiment: each one is a long
software-engineering session with critical facts hidden at known positions and
tool outputs big enough that the truncation arm has something to cut. The
dataset is *generated*, never hand-edited, so that it can be rebuilt
byte-identically and audited against this file.

Run::

    .venv/bin/python evals/generate_dataset.py [--out DIR] [--seed N]

Determinism contract:

* only ``random.Random(seed)`` is used -- never the ``random`` globals, never
  the clock, never ``uuid``;
* message ids are ``f"{case_id}-m{index:03d}"`` and tool call ids
  ``f"{case_id}-tc{index:03d}"``, both following the final message order;
* every number that shapes the data is a named constant below or comes from
  :mod:`caio_code.config`;
* files are written with ``sort_keys=True``, two-space indent and a trailing
  newline, so the same seed produces the same bytes.

The generator validates its own output (shape, fact spread, answer
findability, tool-output ceilings, window overflow) and raises
:class:`~caio_code.domain.errors.DatasetError` on any violation: a dataset that
does not match the experimental design must not be written at all.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:  # pragma: no cover - editable installs skip it
    sys.path.insert(0, str(SRC_ROOT))

from caio_code.config import (  # noqa: E402
    EvalConfig,
    GuardrailConfig,
    ToolOutputConfig,
    WindowConfig,
)
from caio_code.domain.conversation.messages import Message, Role, ToolCall  # noqa: E402
from caio_code.domain.errors import DatasetError  # noqa: E402
from caio_code.domain.evaluation.cases import (  # noqa: E402
    POSITIONS,
    CriticalFact,
    EvalDataset,
    FactPosition,
    HistoryCase,
    Probe,
    answer_matches,
)
from caio_code.domain.policy.tool_output import (  # noqa: E402
    TruncationLimits,
    truncate_text,
)
from caio_code.infrastructure.datasets.codec import (  # noqa: E402
    case_to_dict,
    dataset_to_dict,
)
from caio_code.infrastructure.datasets.loader import describe, format_stats  # noqa: E402
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter  # noqa: E402

# ---------------------------------------------------------------------------
# Named constants: every number that shapes the dataset lives here
# ---------------------------------------------------------------------------

DATASET_NAME = "long_histories"
GENERATOR_NAME = "evals/generate_dataset.py"
GENERATOR_VERSION = 1
CASE_FILE_TEMPLATE = "{case_id}.json"
MANIFEST_NAME = "dataset.json"
DEFAULT_SEED = EvalConfig().seed
DEFAULT_OUT_DIR = REPO_ROOT / EvalConfig().dataset_dir
CASE_COUNT = EvalConfig().max_cases

MESSAGE_ID_TEMPLATE = "{case_id}-m{index:03d}"
TOOL_CALL_ID_TEMPLATE = "{case_id}-tc{index:03d}"
FACT_ID_TEMPLATE = "{case_id}-f{index:02d}"
PROBE_ID_TEMPLATE = "{case_id}-p{index:02d}"
TODO_ID_TEMPLATE = "{case_id}-todo{index:02d}"

# Shape of one case: the experimental design, as hard bounds.
MIN_MESSAGES = 60
MAX_MESSAGES = 140
MIN_CHARS = 60_000
MAX_CHARS = 200_000
MIN_FACTS = 6
MAX_FACTS = 8
MIN_ALIASES = 1
MAX_ALIASES = 3
MIN_FACTS_PER_POSITION = 2
MIN_PROBES = 3
MAX_PROBES = 5
MIN_TOOL_RESULTS = 4
MIN_OUTPUTS_ABOVE_BYTE_CEILING = 1
MIN_OUTPUTS_TRUNCATED = 2
MIN_TODO_STEPS = 2
MAX_TODO_STEPS = 4
MIN_TRAPS = 1
MIN_REPEATED_TOOL_CALLS = 1
REPEATED_TOOL_CALLS = GuardrailConfig().max_repeats
MIN_DUPLICATE_FILLERS = 2
MIN_CONTRACT_MESSAGES = 1
MIN_LARGE_OUTPUT_LINES = 300
MIN_CASES_WITH_LINE_OVERFLOW = 2
MIN_CASES_WITH_TWO_TRUNCATED_OUTPUTS = 3
MIN_SIZE_SPREAD_CHARS = 20_000
MIN_FACTS_DESTROYED_BY_TRUNCATION = 1
MIN_PROBE_POSITIONS = 2
MIN_QUESTION_WORDS = 5
TODO_TOOL_NAME = "write_todos"
TODO_STATUSES: tuple[str, ...] = ("pending", "in_progress", "completed")

# A position is the first / last fifth of the transcript.
EARLY_FRACTION = 0.20
LATE_FRACTION = 0.20

# The window the histories must overflow, and by how much.
WINDOW_TOKENS = WindowConfig().tokens
MIN_WINDOW_MULTIPLES = 2.0
MAX_WINDOW_MULTIPLES = 6.0

# Tool-output truncation ceilings, read from config so the two cannot drift.
TOOL_LIMITS = TruncationLimits(
    max_lines=ToolOutputConfig().max_lines,
    max_bytes=ToolOutputConfig().max_bytes,
)

# Filler weaving: the unscripted part of a session.
MIN_FILLER_BEATS = 10
FILLER_WEIGHTS: dict[str, int] = {
    "user_note": 18,
    "assistant_note": 28,
    "boilerplate": 14,
    "small_tool_run": 20,
    "duplicate": 20,
}
SMALL_OUTPUT_MIN_LINES = 8
SMALL_OUTPUT_MAX_LINES = 44
SMALL_OUTPUT_WIDTH = 64
DUPLICATE_SPAN_MIN = 2
DUPLICATE_SPAN_MAX = 12
DUPLICATE_MAX_SOURCE_CHARS = 400
DUPLICABLE_ROLES = (Role.USER, Role.ASSISTANT)
SINGLE_STEP_FILLER_KINDS: tuple[str, ...] = ("user_note", "assistant_note", "boilerplate")
FILLER_TOOLS: tuple[str, ...] = ("grep", "read_file", "execute")
FILLER_OUTPUT_KINDS: tuple[str, ...] = ("run_log", "file_dump", "test_log")
TOOL_RUN_MESSAGES = 2

# Output builders.
FILE_DUMP_HEADER_LINES = 3
GREP_HEADER_LINES = 2
RUN_LOG_HEADER_LINES = 2
TEST_LOG_HEADER_LINES = 2
CSV_HEADER_LINES = 1
LOCK_LINES_PER_PACKAGE = 6
CHANGELOG_LINES_PER_RELEASE = 8
TEST_LOG_LINES_PER_TEST = 6
TRACEBACK_DEPTH = 4
TODO_ITEMS_PER_BOARD = 4

# Serialization.
JSON_INDENT = 2
CONTRACT_ANCHOR = 0.985

# Per-case tool-output sizes. A case needs at least one output above the line
# ceiling and one above the byte ceiling, and at least one critical fact buried
# where the head/tail cut removes it; these numbers are what delivers that.
FILE_DUMP_LINES_API = 300
GREP_LINES_API = 300
TEST_LOG_LINES_API = 2_060
RUN_LOG_LINES_API = 950

GREP_LINES_WEB = 2_080
TSC_LINES_WEB = 900
FILE_DUMP_LINES_WEB = 300

CSV_LINES_PIPELINE = 1_400
SQL_LOG_LINES_PIPELINE = 1_150
EXPLAIN_LINES_PIPELINE = 300

PYTEST_LINES_CI = 2_140
MATRIX_LINES_CI = 950
GIT_LOG_LINES_CI = 300

LOCK_LINES_UPGRADE = 2_100
CHANGELOG_LINES_UPGRADE = 1_800
PIP_CHECK_LINES_UPGRADE = 300

# Depth at which a critical line is embedded inside a large tool output: the
# middle, which is exactly the band the head/tail truncation removes.
EMBEDDED_FACT_DEPTH = 0.5



# ---------------------------------------------------------------------------
# Specification dataclasses: the case design expressed as data
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FactSpec:
    """One critical fact: where it sits, what it states, how it is probed."""

    slug: str
    statement: str
    answer: str
    aliases: tuple[str, ...]
    position: FactPosition
    question: str
    expected: str
    probe_aliases: tuple[str, ...] = ()
    trap: str = ""
    probed: bool = True


@dataclass(frozen=True, slots=True)
class OutputSpec:
    """One tool result, large enough that a truncation policy has work to do."""

    kind: str
    tool: str
    target: str
    lines: int
    width: int
    arguments: Mapping[str, Any] = field(default_factory=dict)
    embedded: tuple[str, ...] = ()
    embedded_at: tuple[float, ...] = ()
    summary: int = 0


@dataclass(frozen=True, slots=True)
class Step:
    """One message of a scripted beat."""

    role: Role
    text: str = ""
    tool_call: str = ""
    tool_arguments: Mapping[str, Any] = field(default_factory=dict)
    tool_name: str = ""
    pinned: bool = False
    states_fact: str = ""
    trap_for: str = ""
    note: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Beat:
    """A scripted moment: one message, or a tool call with its result."""

    anchor: float
    steps: tuple[Step, ...]
    kind: str = "turn"
    output: OutputSpec | None = None


@dataclass(frozen=True, slots=True)
class TodoBeat:
    """One ``write_todos`` call, carrying the whole board as the agent sends it."""

    anchor: float
    prelude: str
    items: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """Domain words the filler and the output builders draw from."""

    paths: tuple[str, ...]
    symbols: tuple[str, ...]
    commands: tuple[str, ...]
    observations: tuple[str, ...]
    questions: tuple[str, ...]
    log_lines: tuple[str, ...]
    code_lines: tuple[str, ...]
    packages: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseSpec:
    """The full design of one case."""

    index: int
    slug: str
    domain: str
    description: str
    task: str
    notes: str
    message_target: int
    contract: str
    vocabulary: Vocabulary
    facts: tuple[FactSpec, ...]
    beats: tuple[Beat, ...]
    todos: tuple[TodoBeat, ...]

    def __post_init__(self) -> None:
        slugs = [fact.slug for fact in self.facts]
        if len(set(slugs)) != len(slugs):
            msg = f"case {self.case_id!r} repeats a fact slug: {sorted(slugs)}"
            raise DatasetError(msg)

    @property
    def case_id(self) -> str:
        return f"case-{self.index:02d}-{self.slug}"

    @property
    def file_name(self) -> str:
        return CASE_FILE_TEMPLATE.format(case_id=self.case_id)


# ---------------------------------------------------------------------------
# Output builders: realistic large tool results
# ---------------------------------------------------------------------------

OutputBuilder = Callable[[random.Random, OutputSpec, Vocabulary], list[str]]


def _clip(text: str, width: int) -> str:
    """Keep a generated line inside the width the output declares."""
    if width and len(text) > width:
        return text[: max(0, width - 1)] + "..."
    return text


def _numbered_file(rng: random.Random, spec: OutputSpec, vocab: Vocabulary) -> list[str]:
    """A file dump with line numbers, as ``read_file`` returns it."""
    head = [
        f"--- {spec.target} ---",
        f"read_file: {spec.lines} lines, utf-8, no trailing newline stripped",
        "line numbers are 1-based, as in the editor",
    ]
    body = [
        f"{number:>{len(str(spec.lines))}}| {_clip(rng.choice(vocab.code_lines), spec.width)}"
        for number in range(1, spec.lines - len(head) + 1)
    ]
    return [*head, *body]


def _run_log(rng: random.Random, spec: OutputSpec, vocab: Vocabulary) -> list[str]:
    """A service or command log: levels, timings and one traceback."""
    head = [f"$ {spec.target}", f"captured {spec.lines} lines, exit status follows"]
    levels = ("DEBUG", "INFO", "INFO", "WARNING", "ERROR")
    body: list[str] = []
    for _ in range(spec.lines - len(head)):
        level = rng.choice(levels)
        stamp = f"{rng.randrange(24):02d}:{rng.randrange(60):02d}:{rng.randrange(60):02d}"
        body.append(_clip(f"{stamp} {level:<7} {rng.choice(vocab.log_lines)}", spec.width))
    depth = min(len(body) - 1, max(1, int(len(body) * 0.7)))
    traceback = [
        _clip("Traceback (most recent call last):", spec.width),
        *[
            _clip(
                f'  File "{rng.choice(vocab.paths)}", line {rng.randrange(9, 400)}, '
                f"in {rng.choice(vocab.symbols).split('.')[-1]}",
                spec.width,
            )
            for _ in range(TRACEBACK_DEPTH)
        ],
        _clip(f"AssertionError: {rng.choice(vocab.observations)}", spec.width),
    ]
    body[depth : depth + len(traceback)] = traceback
    return [*head, *body]


def _test_log(rng: random.Random, spec: OutputSpec, vocab: Vocabulary) -> list[str]:
    """A test run: one block per test, the failing one deep in the middle."""
    head = [f"$ {spec.target}", f"collected {spec.summary} items"]
    body: list[str] = []
    number = 0
    while len(body) < spec.lines - len(head):
        number += 1
        name = f"test_{rng.choice(vocab.symbols).split('.')[-1]}_{number:03d}"
        body.append(_clip(f"{rng.choice(vocab.paths)}::{name} ", spec.width) + "PASSED")
        for _ in range(rng.randrange(1, TEST_LOG_LINES_PER_TEST)):
            body.append(_clip(f"    {rng.choice(vocab.log_lines)}", spec.width))
    return [*head, *body]


def _grep_hits(rng: random.Random, spec: OutputSpec, vocab: Vocabulary) -> list[str]:
    """A grep result over many files: ``path:line:content``."""
    head = [f"$ grep -rn --color=never {spec.target} .", f"{spec.lines - GREP_HEADER_LINES} matches"]
    body = [
        _clip(
            f"{rng.choice(vocab.paths)}:{rng.randrange(1, 900)}: "
            f"{rng.choice(vocab.code_lines).strip()}",
            spec.width,
        )
        for _ in range(spec.lines - len(head))
    ]
    return [*head, *body]


def _csv_rows(rng: random.Random, spec: OutputSpec, vocab: Vocabulary) -> list[str]:
    """A CSV of metrics: a header plus one row per measured unit."""
    columns = vocab.columns or ("unit", "value")
    header = ",".join(columns)
    body = [
        ",".join(_cell(rng, column, vocab) for column in columns)
        for _ in range(spec.lines - CSV_HEADER_LINES)
    ]
    return [header, *body]


def _cell(rng: random.Random, column: str, vocab: Vocabulary) -> str:
    """One CSV cell, typed by the column name so the file reads as real data."""
    if column.endswith("_ms") or column.endswith("_count") or column.endswith("_bytes"):
        return str(rng.randrange(1, 999_999))
    if column.endswith("_rate") or column.endswith("_ratio"):
        return f"{rng.random():.4f}"
    if column.endswith("_at"):
        return f"2026-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}T0{rng.randrange(10)}:00:00Z"
    return rng.choice(vocab.notes or vocab.paths)


def _lock_excerpt(rng: random.Random, spec: OutputSpec, vocab: Vocabulary) -> list[str]:
    """A dependency lock excerpt: a fixed block per pinned package."""
    packages = vocab.packages or vocab.symbols
    lines: list[str] = []
    number = 0
    while len(lines) < spec.lines:
        number += 1
        package = packages[number % len(packages)]
        digest = "".join(rng.choice("0123456789abcdef") for _ in range(32))
        lines.extend(
            _clip(line, spec.width)
            for line in (
                "[[package]]",
                f'name = "{package}"',
                f'version = "{number % 12}.{number % 7}.{number % 5}"',
                f'description = "{rng.choice(vocab.notes or vocab.observations)}"',
                f'files = "{digest}"',
                "",
            )
        )
    return lines[: spec.lines]


def _changelog(rng: random.Random, spec: OutputSpec, vocab: Vocabulary) -> list[str]:
    """A changelog: release headers and bullet points, read top to bottom."""
    kinds = ("Added", "Fixed", "Changed", "Removed", "Deprecated")
    lines = ["# Changelog", ""]
    release = 0
    while len(lines) < spec.lines:
        release += 1
        lines.append(f"## {release % 9}.{release % 11}.{release % 5} - internal build")
        lines.append("")
        for _ in range(CHANGELOG_LINES_PER_RELEASE):
            lines.append(
                _clip(f"- {rng.choice(kinds)}: {rng.choice(vocab.log_lines)}", spec.width)
            )
        lines.append("")
    return lines[: spec.lines]


OUTPUT_BUILDERS: dict[str, OutputBuilder] = {
    "file_dump": _numbered_file,
    "run_log": _run_log,
    "test_log": _test_log,
    "grep": _grep_hits,
    "csv": _csv_rows,
    "lock": _lock_excerpt,
    "changelog": _changelog,
}


def render_output(rng: random.Random, spec: OutputSpec, vocab: Vocabulary) -> str:
    """Build one tool result, embedding the critical lines at known depths."""
    try:
        builder = OUTPUT_BUILDERS[spec.kind]
    except KeyError as exc:
        msg = f"unknown tool-output kind {spec.kind!r} for target {spec.target!r}"
        raise DatasetError(msg) from exc
    lines = builder(rng, spec, vocab)
    for text, at in zip(spec.embedded, spec.embedded_at, strict=True):
        position = min(len(lines) - 1, max(0, round(at * len(lines))))
        lines.insert(position, _clip(text, max(len(text), spec.width)))
    if not lines:
        msg = f"tool output for {spec.target!r} rendered no lines"
        raise DatasetError(msg)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Position arithmetic
# ---------------------------------------------------------------------------


def early_boundary(total: int) -> int:
    """First index that is no longer ``early``."""
    return max(1, math.ceil(total * EARLY_FRACTION))


def late_boundary(total: int) -> int:
    """First index that counts as ``late``."""
    return max(early_boundary(total), total - math.floor(total * LATE_FRACTION))


def position_for(index: int, total: int) -> FactPosition:
    """The position an index falls in, given the transcript length."""
    if index < early_boundary(total):
        return "early"
    if index >= late_boundary(total):
        return "late"
    return "middle"


# ---------------------------------------------------------------------------
# Filler: the realistic noise that makes a session long
# ---------------------------------------------------------------------------


def _filler_kind(rng: random.Random) -> str:
    kinds = tuple(FILLER_WEIGHTS)
    weights = tuple(FILLER_WEIGHTS[kind] for kind in kinds)
    return rng.choices(kinds, weights=weights, k=1)[0]


def _small_output(rng: random.Random, vocab: Vocabulary, kind: str) -> str:
    """A tool result small enough to survive truncation untouched."""
    lines = rng.randrange(SMALL_OUTPUT_MIN_LINES, SMALL_OUTPUT_MAX_LINES + 1)
    spec = OutputSpec(
        kind=kind,
        tool="execute",
        target=rng.choice(vocab.commands),
        lines=lines,
        width=SMALL_OUTPUT_WIDTH,
    )
    return render_output(rng, spec, vocab)


def _filler_steps(
    rng: random.Random,
    vocab: Vocabulary,
    recent: Sequence[Step],
    *,
    budget: int = 2,
    forced: str = "",
) -> tuple[Step, ...]:
    """One filler beat: plausible traffic that carries no critical fact.

    ``budget`` is the number of message slots the beat may occupy, so the woven
    transcript always hits the exact message count the spec declares.
    """
    kind = forced or _filler_kind(rng)
    if kind == "small_tool_run" and budget < TOOL_RUN_MESSAGES:
        kind = rng.choice(SINGLE_STEP_FILLER_KINDS)
    candidates = [
        step
        for step in recent[-DUPLICATE_SPAN_MAX:]
        if step.role in DUPLICABLE_ROLES
        and not step.states_fact
        and not step.trap_for
        and 0 < len(step.text) <= DUPLICATE_MAX_SOURCE_CHARS
    ]
    if kind == "duplicate" and len(candidates) < DUPLICATE_SPAN_MIN:
        kind = rng.choice(SINGLE_STEP_FILLER_KINDS)
    if kind == "duplicate":
        original = rng.choice(candidates)
        return (
            Step(
                role=original.role,
                text=original.text,
                note="near-duplicate of an earlier turn",
                metadata={"filler": "duplicate"},
            ),
        )
    if kind == "user_note":
        return (Step(role=Role.USER, text=rng.choice(vocab.questions), metadata={"filler": kind}),)
    if kind == "assistant_note":
        return (
            Step(
                role=Role.ASSISTANT,
                text=f"{rng.choice(vocab.observations)} I re-read {rng.choice(vocab.paths)} "
                f"around `{rng.choice(vocab.symbols)}` before settling on that.",
                metadata={"filler": kind},
            ),
        )
    if kind == "boilerplate":
        return (
            Step(
                role=Role.ASSISTANT,
                text=f"Running `{rng.choice(vocab.commands)}` now and reporting back; "
                "no other file changes in flight.",
                metadata={"filler": kind},
            ),
        )
    if kind == "small_tool_run":
        tool = rng.choice(FILLER_TOOLS)
        target = rng.choice(vocab.paths)
        command = rng.choice(vocab.commands)
        arguments = (
            {"command": command}
            if tool == "execute"
            else {"path": target}
            if tool == "read_file"
            else {"pattern": rng.choice(vocab.symbols), "path": "."}
        )
        output_kind = "grep" if tool == "grep" else rng.choice(FILLER_OUTPUT_KINDS)
        return (
            Step(
                role=Role.ASSISTANT,
                text=f"Let me check {target} with `{command}`.",
                tool_call=tool,
                tool_arguments=arguments,
                metadata={"filler": kind},
            ),
            Step(
                role=Role.TOOL,
                text=_small_output(rng, vocab, output_kind),
                tool_name=tool,
                metadata={"filler": kind},
            ),
        )
    raise DatasetError(f"unknown filler kind {kind!r}")


# ---------------------------------------------------------------------------
# Case weaving
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CaseBuild:
    """Mutable state of one case while it is woven."""

    spec: CaseSpec
    rng: random.Random
    messages: list[Message] = field(default_factory=list)
    fact_indices: dict[str, int] = field(default_factory=dict)
    trap_indices: dict[str, int] = field(default_factory=dict)
    duplicates: int = 0
    tool_calls: int = 0
    recent: list[Step] = field(default_factory=list)

    @property
    def case_id(self) -> str:
        return self.spec.case_id

    def next_message_id(self) -> str:
        return MESSAGE_ID_TEMPLATE.format(case_id=self.case_id, index=len(self.messages))

    def next_tool_call_id(self) -> str:
        self.tool_calls += 1
        return TOOL_CALL_ID_TEMPLATE.format(case_id=self.case_id, index=self.tool_calls)

    def add(self, step: Step, *, tool_call_id: str | None = None) -> Message:
        """Append one message, resolving its ids from its final position."""
        calls: tuple[ToolCall, ...] = ()
        if step.tool_call:
            calls = (
                ToolCall(
                    id=self.next_tool_call_id(),
                    name=step.tool_call,
                    arguments=json.dumps(step.tool_arguments, sort_keys=True),
                ),
            )
        metadata = dict(step.metadata)
        if step.states_fact:
            metadata["states_fact"] = step.states_fact
        if step.trap_for:
            metadata["trap_for"] = step.trap_for
        if step.note:
            metadata["note"] = step.note
        message = Message(
            id=self.next_message_id(),
            role=step.role,
            text=step.text,
            tool_calls=calls,
            tool_call_id=tool_call_id,
            name=step.tool_name or None,
            pinned=step.pinned,
            metadata=metadata,
        )
        self.messages.append(message)
        if step.states_fact:
            self.fact_indices[step.states_fact] = len(self.messages) - 1
        if step.trap_for:
            self.trap_indices.setdefault(step.trap_for, len(self.messages) - 1)
        self.recent.append(step)
        return message


def _todo_steps(spec: CaseSpec, todo: TodoBeat, position: int) -> tuple[Step, ...]:
    """The assistant's ``write_todos`` call and the tool acknowledgement."""
    board = [
        {
            "id": TODO_ID_TEMPLATE.format(case_id=spec.case_id, index=index),
            "content": content,
            "status": status,
            "priority": "high" if index == 0 else "medium",
            "order": index,
        }
        for index, (content, status) in enumerate(todo.items)
    ]
    completed = sum(1 for item in board if item["status"] == "completed")
    return (
        Step(
            role=Role.ASSISTANT,
            text=todo.prelude,
            tool_call="write_todos",
            tool_arguments={"todos": board},
            metadata={"todo_step": position, "todo_items": len(board)},
        ),
        Step(
            role=Role.TOOL,
            text=f"Todos updated: {len(board)} items, {completed} completed, "
            f"{len(board) - completed} open.",
            tool_name="write_todos",
            metadata={"todo_step": position},
        ),
    )


def _scripted_beats(spec: CaseSpec) -> tuple[Beat, ...]:
    """Every scripted beat of a case, todo boards and the pinned contract included."""
    todos = tuple(
        Beat(
            anchor=todo.anchor,
            kind="todo",
            steps=_todo_steps(spec, todo, position),
        )
        for position, todo in enumerate(spec.todos)
    )
    contract = Beat(
        anchor=CONTRACT_ANCHOR,
        kind="contract",
        steps=(
            Step(
                role=Role.USER,
                text=spec.contract,
                pinned=True,
                note="user restates a constraint near the end",
                metadata={"role_in_case": "contract"},
            ),
        ),
    )
    return tuple(sorted((*spec.beats, *todos, contract), key=lambda beat: beat.anchor))


def _gap_plan(spec: CaseSpec, beats: Sequence[Beat], rng: random.Random) -> list[int]:
    """How many filler beats precede each scripted beat.

    The layout is computed before any text is generated so that the anchors in
    the spec decide where facts land, and the total is exactly
    ``spec.message_target`` -- which is what makes positions reproducible.
    """
    scripted = 1 + sum(len(beat.steps) for beat in beats)
    filler = spec.message_target - scripted
    if filler < MIN_FILLER_BEATS:
        msg = (
            f"case {spec.case_id!r}: {spec.message_target} messages cannot hold {scripted} "
            f"scripted messages plus the {MIN_FILLER_BEATS} filler beats a long session needs"
        )
        raise DatasetError(msg)

    gaps: list[int] = []
    cursor = 1
    for beat in beats:
        target = max(cursor, round(beat.anchor * (spec.message_target - 1)))
        gaps.append(target - cursor)
        cursor = target + len(beat.steps)
    leftover = filler - sum(gaps)
    if leftover < 0:
        msg = (
            f"case {spec.case_id!r}: beats are anchored too close together, "
            f"{-leftover} message slots overlap"
        )
        raise DatasetError(msg)

    order = list(range(len(gaps)))
    rng.shuffle(order)
    for slot in order:
        if leftover <= 0:
            break
        gaps[slot] += 1
        leftover -= 1
    return gaps


def _facts_for(build: CaseBuild, total: int) -> tuple[CriticalFact, ...]:
    """Materialize the facts, each recording the message that states it."""
    facts: list[CriticalFact] = []
    for position, spec in enumerate(build.spec.facts):
        if spec.slug not in build.fact_indices:
            msg = f"case {build.case_id!r}: no message states fact {spec.slug!r}"
            raise DatasetError(msg)
        index = build.fact_indices[spec.slug]
        facts.append(
            CriticalFact(
                id=FACT_ID_TEMPLATE.format(case_id=build.case_id, index=position),
                statement=spec.statement,
                answer=spec.answer,
                aliases=spec.aliases,
                position=position_for(index, total),
                message_index=index,
            )
        )
    return tuple(facts)


def _probes_for(build: CaseBuild, facts: Sequence[CriticalFact]) -> tuple[Probe, ...]:
    """One probe per fact that declares a question, in fact order."""
    probes: list[Probe] = []
    for fact, spec in zip(facts, build.spec.facts, strict=True):
        if not spec.probed:
            continue
        if not spec.question:
            msg = f"case {build.case_id!r}: fact {spec.slug!r} is probed but has no question"
            raise DatasetError(msg)
        probes.append(
            Probe(
                id=PROBE_ID_TEMPLATE.format(case_id=build.case_id, index=len(probes)),
                fact_id=fact.id,
                question=spec.question,
                expected=spec.expected,
                aliases=spec.probe_aliases,
            )
        )
    return tuple(probes)


def _case_metadata(spec: CaseSpec, build: CaseBuild, facts: Sequence[CriticalFact], seed: int) -> dict[str, Any]:
    """The audit trail of one case: what generated it and how big it came out."""
    counter = CharProxyTokenCounter()
    tool_texts = [message.text for message in build.messages if message.is_tool_result()]
    largest = max(tool_texts, key=len, default="")
    largest_message = next(
        (
            message.id
            for message in build.messages
            if message.is_tool_result() and message.text == largest and largest
        ),
        "",
    )
    positions = {position: 0 for position in POSITIONS}
    for fact in facts:
        positions[fact.position] += 1
    return {
        "generator": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "case_seed": case_seed(seed, spec),
        "domain": spec.domain,
        "message_count": len(build.messages),
        "char_count": sum(message.char_count() for message in build.messages),
        "proxy_tokens": counter.count_messages(build.messages),
        "largest_tool_output_chars": len(largest),
        "largest_tool_output_lines": largest.count("\n") + 1 if largest else 0,
        "largest_tool_output_message": largest_message,
        "tool_results": len(tool_texts),
        "fact_positions": positions,
        "facts_inside_tool_output": sorted(
            step.states_fact
            for beat in spec.beats
            if beat.output is not None
            for step in beat.steps
            if step.role is Role.TOOL and step.states_fact
        ),
        "traps": len(build.trap_indices),
        "repeated_tool_calls": sum(
            1
            for message in build.messages
            if message.metadata.get("distractor") == "repeated_tool_call"
        ),
        "near_duplicate_messages": build.duplicates,
        "todo_steps": len(spec.todos),
        "pinned_messages": sum(1 for message in build.messages if message.pinned),
        "notes": spec.notes,
    }


def case_seed(seed: int, spec: CaseSpec) -> int:
    """The per-case stream: the dataset seed offset by the case index.

    Deriving it instead of sharing one stream keeps a case byte-stable when
    another case is added or reordered, which is what makes the committed files
    auditable one case at a time.
    """
    return seed + spec.index


def build_case(spec: CaseSpec, seed: int) -> HistoryCase:
    """Weave one case: task, scripted beats, filler, ids, facts, probes."""
    _check_spec_texts(spec)
    rng = random.Random(case_seed(seed, spec))
    build = CaseBuild(spec=spec, rng=rng)
    beats = _scripted_beats(spec)
    gaps = _gap_plan(spec, beats, rng)

    build.add(
        Step(
            role=Role.USER,
            text=spec.task,
            pinned=True,
            note="the task statement; policies may never drop it",
            metadata={"role_in_case": "task"},
        )
    )

    pending_call_id: str | None = None
    for beat, gap in zip(beats, gaps, strict=True):
        slots = gap
        while slots > 0:
            steps = _filler_steps(rng, spec.vocabulary, build.recent, budget=slots)
            if steps[0].metadata.get("filler") == "duplicate":
                build.duplicates += 1
            for step in steps:
                message = build.add(
                    step, tool_call_id=pending_call_id if step.role is Role.TOOL else None
                )
                pending_call_id = message.tool_calls[0].id if message.tool_calls else None
            slots -= len(steps)
        for step in beat.steps:
            resolved = step
            if beat.output is not None and step.role is Role.TOOL:
                text = render_output(rng, beat.output, spec.vocabulary)
                resolved = Step(
                    role=step.role,
                    text=text,
                    tool_name=step.tool_name or beat.output.tool,
                    states_fact=step.states_fact,
                    metadata={
                        **step.metadata,
                        "tool_output_lines": text.count("\n") + 1,
                        "tool_output_chars": len(text),
                    },
                )
            message = build.add(
                resolved, tool_call_id=pending_call_id if resolved.role is Role.TOOL else None
            )
            pending_call_id = message.tool_calls[0].id if message.tool_calls else None

    if len(build.messages) != spec.message_target:
        msg = (
            f"case {spec.case_id!r}: built {len(build.messages)} messages, "
            f"the spec asks for {spec.message_target}"
        )
        raise DatasetError(msg)

    facts = _facts_for(build, len(build.messages))
    case = HistoryCase(
        id=spec.case_id,
        description=spec.description,
        task=spec.task,
        messages=tuple(build.messages),
        facts=facts,
        probes=_probes_for(build, facts),
        source="synthetic",
        metadata=_case_metadata(spec, build, facts, seed),
    )
    validate_case(case, spec, build)
    return case


# ---------------------------------------------------------------------------
# Validation: the design is checked, not assumed
# ---------------------------------------------------------------------------


def _require(condition: bool, msg: str) -> None:
    if not condition:
        raise DatasetError(msg)


def _check_shape(case: HistoryCase, spec: CaseSpec) -> None:
    total = len(case.messages)
    _require(
        MIN_MESSAGES <= total <= MAX_MESSAGES,
        f"case {case.id!r}: {total} messages outside [{MIN_MESSAGES}, {MAX_MESSAGES}]",
    )
    _require(
        MIN_CHARS <= case.char_count <= MAX_CHARS,
        f"case {case.id!r}: {case.char_count} chars outside [{MIN_CHARS}, {MAX_CHARS}]",
    )
    tokens = CharProxyTokenCounter().count_transcript(case.transcript)
    multiples = tokens / WINDOW_TOKENS
    _require(
        MIN_WINDOW_MULTIPLES <= multiples <= MAX_WINDOW_MULTIPLES,
        f"case {case.id!r}: {tokens} proxy tokens is {multiples:.2f}x the "
        f"{WINDOW_TOKENS}-token window, expected between {MIN_WINDOW_MULTIPLES}x "
        f"and {MAX_WINDOW_MULTIPLES}x",
    )
    _require(
        MIN_FACTS <= len(case.facts) <= MAX_FACTS,
        f"case {case.id!r}: {len(case.facts)} facts outside [{MIN_FACTS}, {MAX_FACTS}]",
    )


def _check_pinning(case: HistoryCase) -> None:
    first = case.messages[0]
    _require(
        first.role is Role.USER and first.pinned,
        f"case {case.id!r}: message 0 must be the pinned user task, got "
        f"role={first.role.value!r} pinned={first.pinned}",
    )
    total = len(case.messages)
    contracts = [
        index
        for index, message in enumerate(case.messages)
        if message.pinned and message.metadata.get("role_in_case") == "contract"
    ]
    _require(
        len(contracts) >= MIN_CONTRACT_MESSAGES,
        f"case {case.id!r}: no pinned contract message found",
    )
    for index in contracts:
        _require(
            position_for(index, total) == "late",
            f"case {case.id!r}: the pinned contract at index {index} must sit in the last "
            f"{LATE_FRACTION:.0%} of the transcript",
        )


def _states(message: Message, acceptable: Sequence[str]) -> bool:
    """Whether a message shows an answer to the model: its text or its tool call."""
    rendered = " ".join(
        [message.text, *(call.name + " " + call.arguments for call in message.tool_calls)]
    )
    return answer_matches(rendered, acceptable)


def _check_facts(case: HistoryCase, spec: CaseSpec, build: CaseBuild) -> None:
    total = len(case.messages)
    by_position = {position: 0 for position in POSITIONS}
    for fact, fact_spec in zip(case.facts, spec.facts, strict=True):
        index = fact.message_index
        _require(
            index is not None and 0 <= index < total,
            f"case {case.id!r}: fact {fact.id!r} has message_index {index!r} outside the "
            f"{total}-message transcript",
        )
        _require(
            fact.position == fact_spec.position,
            f"case {case.id!r}: fact {fact.id!r} landed in {fact.position!r} at index {index}, "
            f"the spec places it in {fact_spec.position!r}",
        )
        _require(
            position_for(index or 0, total) == fact.position,
            f"case {case.id!r}: fact {fact.id!r} at index {index} is labelled {fact.position!r}",
        )
        carrier = case.messages[index or 0]
        _require(
            answer_matches(carrier.text, fact.acceptable_answers),
            f"case {case.id!r}: the answer of fact {fact.id!r} ({fact.answer!r}) does not appear "
            f"in message {carrier.id!r} that is supposed to state it",
        )
        occurrences = [
            message.id for message in case.messages if _states(message, fact.acceptable_answers)
        ]
        _require(
            occurrences == [carrier.id],
            f"case {case.id!r}: the answer of fact {fact.id!r} ({fact.answer!r}) also appears in "
            f"{[m for m in occurrences if m != carrier.id]}, so a policy could recover it "
            f"without retaining {carrier.id!r}",
        )
        _require(
            MIN_ALIASES <= len(fact.aliases) <= MAX_ALIASES,
            f"case {case.id!r}: fact {fact.id!r} has {len(fact.aliases)} aliases, "
            f"expected between {MIN_ALIASES} and {MAX_ALIASES}",
        )
        _require(
            bool(fact.statement.strip()),
            f"case {case.id!r}: fact {fact.id!r} has an empty statement",
        )
        by_position[fact.position] += 1

        trap_index = build.trap_indices.get(fact_spec.slug)
        if fact_spec.trap:
            _require(
                trap_index is not None,
                f"case {case.id!r}: fact {fact.id!r} declares trap {fact_spec.trap!r} but no "
                "message carries it",
            )
            _require(
                trap_index is not None and trap_index < (index or 0),
                f"case {case.id!r}: the trap for fact {fact.id!r} at index {trap_index} must "
                f"precede the corrected value at index {index}",
            )
            trap_text = case.messages[trap_index or 0].text
            _require(
                not answer_matches(trap_text, fact.acceptable_answers),
                f"case {case.id!r}: the trap message for fact {fact.id!r} already contains an "
                f"acceptable answer, so it is not a trap: {trap_text[:120]!r}",
            )

    for position in POSITIONS:
        _require(
            by_position[position] >= MIN_FACTS_PER_POSITION,
            f"case {case.id!r}: only {by_position[position]} facts in position {position!r}, "
            f"the design needs at least {MIN_FACTS_PER_POSITION}",
        )

    answers = [fact.answer for fact in case.facts]
    _require(
        len(set(answers)) == len(answers),
        f"case {case.id!r}: two facts share the same answer: {sorted(answers)}",
    )


def _check_probes(case: HistoryCase) -> None:
    _require(
        MIN_PROBES <= len(case.probes) <= MAX_PROBES,
        f"case {case.id!r}: {len(case.probes)} probes outside [{MIN_PROBES}, {MAX_PROBES}]",
    )
    targeted = [probe.fact_id for probe in case.probes]
    _require(
        len(set(targeted)) == len(targeted),
        f"case {case.id!r}: two probes target the same fact: {sorted(targeted)}",
    )
    positions = set()
    for probe in case.probes:
        fact = case.fact(probe.fact_id)
        _require(
            fact.message_index is not None,
            f"case {case.id!r}: probe {probe.id!r} targets fact {fact.id!r} without an index",
        )
        carrier = case.messages[fact.message_index or 0]
        _require(
            answer_matches(carrier.text, probe.acceptable_answers),
            f"case {case.id!r}: probe {probe.id!r} expects {probe.expected!r}, which does not "
            f"appear in message {carrier.id!r} stating fact {fact.id!r}",
        )
        _require(
            len(probe.question.split()) >= MIN_QUESTION_WORDS,
            f"case {case.id!r}: probe {probe.id!r} question is too short to be unambiguous: "
            f"{probe.question!r}",
        )
        positions.add(fact.position)
    _require(
        len(positions) >= MIN_PROBE_POSITIONS,
        f"case {case.id!r}: probes cover only {sorted(positions)}, the design needs at least "
        f"{MIN_PROBE_POSITIONS} positions",
    )


def _check_tool_outputs(case: HistoryCase, spec: CaseSpec) -> None:
    results = [message for message in case.messages if message.is_tool_result()]
    _require(
        len(results) >= MIN_TOOL_RESULTS,
        f"case {case.id!r}: {len(results)} tool results, the design needs {MIN_TOOL_RESULTS}",
    )
    above_lines = 0
    above_bytes = 0
    truncated_outputs = 0
    destroyed = 0
    for message in results:
        lines = message.text.count("\n") + 1
        size = len(message.text.encode("utf-8"))
        over_lines = lines > TOOL_LIMITS.max_lines
        over_bytes = size > TOOL_LIMITS.max_bytes
        above_lines += int(over_lines)
        above_bytes += int(over_bytes)
        if not (over_lines or over_bytes):
            continue
        truncated_outputs += 1
        truncated, changed = truncate_text(message.text, TOOL_LIMITS)
        _require(
            changed,
            f"case {case.id!r}: tool result {message.id!r} is above a ceiling but "
            "truncate_text kept everything",
        )
        for fact in case.facts:
            if fact.message_index is None or case.messages[fact.message_index].id != message.id:
                continue
            if not answer_matches(truncated, fact.acceptable_answers):
                destroyed += 1
    _require(
        truncated_outputs >= MIN_OUTPUTS_TRUNCATED,
        f"case {case.id!r}: only {truncated_outputs} tool outputs are above a truncation "
        f"ceiling, the design needs {MIN_OUTPUTS_TRUNCATED}",
    )
    _require(
        above_bytes >= MIN_OUTPUTS_ABOVE_BYTE_CEILING,
        f"case {case.id!r}: {above_bytes} tool outputs above the {TOOL_LIMITS.max_bytes}-byte "
        f"ceiling, the truncation arm needs at least {MIN_OUTPUTS_ABOVE_BYTE_CEILING}",
    )
    _require(
        destroyed >= MIN_FACTS_DESTROYED_BY_TRUNCATION,
        f"case {case.id!r}: no critical fact is destroyed by truncating a large tool output, "
        "which is the contrast the thesis reports",
    )
    _require(
        all(output.lines >= MIN_LARGE_OUTPUT_LINES for output in _large_outputs(spec)),
        f"case {case.id!r}: a scripted tool output is below {MIN_LARGE_OUTPUT_LINES} lines",
    )


def _large_outputs(spec: CaseSpec) -> tuple[OutputSpec, ...]:
    return tuple(beat.output for beat in spec.beats if beat.output is not None)


def _check_todos(case: HistoryCase, spec: CaseSpec) -> None:
    _require(
        MIN_TODO_STEPS <= len(spec.todos) <= MAX_TODO_STEPS,
        f"case {case.id!r}: {len(spec.todos)} write_todos beats outside "
        f"[{MIN_TODO_STEPS}, {MAX_TODO_STEPS}]",
    )
    calls = [
        message
        for message in case.messages
        if any(call.name == TODO_TOOL_NAME for call in message.tool_calls)
    ]
    _require(
        len(calls) == len(spec.todos),
        f"case {case.id!r}: {len(calls)} {TODO_TOOL_NAME} calls for {len(spec.todos)} beats",
    )
    for message in calls:
        payload = json.loads(message.tool_calls[0].arguments)
        items = payload.get("todos")
        _require(
            isinstance(items, list) and bool(items),
            f"case {case.id!r}: {TODO_TOOL_NAME} call {message.id!r} carries no todo list",
        )
        in_progress = sum(1 for item in items if item["status"] == "in_progress")
        _require(
            in_progress <= 1,
            f"case {case.id!r}: {TODO_TOOL_NAME} call {message.id!r} has {in_progress} items "
            "in progress, the board allows at most one",
        )
        for item in items:
            _require(
                item["status"] in TODO_STATUSES,
                f"case {case.id!r}: todo item {item.get('id')!r} has unknown status "
                f"{item.get('status')!r}",
            )


def _check_distractors(case: HistoryCase, build: CaseBuild) -> None:
    _require(
        build.duplicates >= MIN_DUPLICATE_FILLERS,
        f"case {case.id!r}: only {build.duplicates} near-duplicate messages, the design needs "
        f"{MIN_DUPLICATE_FILLERS}",
    )
    _require(
        len(build.trap_indices) >= MIN_TRAPS,
        f"case {case.id!r}: {len(build.trap_indices)} superseded decisions, the design needs "
        f"{MIN_TRAPS}",
    )
    texts = [message.text for message in case.messages if len(message.text) < 400]
    _require(
        len(texts) != len(set(texts)),
        f"case {case.id!r}: no repeated message text, so nothing tests near-duplicate handling",
    )


def _check_repeated_tool_calls(case: HistoryCase) -> None:
    """The guardrail arm needs a call repeated with identical arguments."""
    seen: dict[tuple[str, str], int] = {}
    for message in case.messages:
        for call in message.tool_calls:
            key = (call.name, call.arguments)
            seen[key] = seen.get(key, 0) + 1
    repeated = {key: count for key, count in seen.items() if count >= REPEATED_TOOL_CALLS}
    _require(
        len(repeated) >= MIN_REPEATED_TOOL_CALLS,
        f"case {case.id!r}: no tool call is repeated {REPEATED_TOOL_CALLS} times with the same "
        f"arguments, so the loop guardrail has nothing to catch: {sorted(seen)}",
    )


def _check_metadata(case: HistoryCase) -> None:
    required = (
        "generator",
        "seed",
        "message_count",
        "char_count",
        "largest_tool_output_chars",
        "fact_positions",
        "notes",
    )
    missing = [key for key in required if key not in case.metadata]
    _require(not missing, f"case {case.id!r}: metadata is missing {sorted(missing)}")
    _require(
        case.metadata["message_count"] == len(case.messages),
        f"case {case.id!r}: metadata says {case.metadata['message_count']} messages, "
        f"the transcript has {len(case.messages)}",
    )
    _require(
        case.metadata["char_count"] == case.char_count,
        f"case {case.id!r}: metadata says {case.metadata['char_count']} chars, "
        f"the transcript has {case.char_count}",
    )


def _check_spec_texts(spec: CaseSpec) -> None:
    """No string of the spec may repeat a fact answer outside the message that states it.

    Checked before weaving, on the spec, because the offender is then named
    exactly: a vocabulary entry, a tool target, a follow-up. A fact whose answer
    the filler repeats measures nothing, since any policy that keeps one of those
    messages answers the probe without retaining the original.
    """
    suspects: list[tuple[str, str]] = [
        ("task", spec.task),
        ("contract", spec.contract),
        ("description", spec.description),
        ("notes", spec.notes),
    ]
    for name, values in (
        ("paths", spec.vocabulary.paths),
        ("symbols", spec.vocabulary.symbols),
        ("commands", spec.vocabulary.commands),
        ("observations", spec.vocabulary.observations),
        ("questions", spec.vocabulary.questions),
        ("log_lines", spec.vocabulary.log_lines),
        ("code_lines", spec.vocabulary.code_lines),
        ("packages", spec.vocabulary.packages),
        ("columns", spec.vocabulary.columns),
        ("notes", spec.vocabulary.notes),
    ):
        suspects.extend((f"vocabulary.{name}[{index}]", value) for index, value in enumerate(values))
    for beat_position, beat in enumerate(spec.beats):
        for step_position, step in enumerate(beat.steps):
            where = f"beats[{beat_position}].steps[{step_position}]"
            suspects.append((f"{where}.text", step.text))
            suspects.append((f"{where}.arguments", json.dumps(step.tool_arguments, sort_keys=True)))
        if beat.output is not None:
            where = f"beats[{beat_position}].output"
            suspects.append((f"{where}.target", beat.output.target))
            suspects.append((f"{where}.arguments", json.dumps(beat.output.arguments, sort_keys=True)))
            for index, line in enumerate(beat.output.embedded):
                suspects.append((f"{where}.embedded[{index}]", line))
    for todo_position, todo in enumerate(spec.todos):
        suspects.append((f"todos[{todo_position}].prelude", todo.prelude))
        for index, (content, _status) in enumerate(todo.items):
            suspects.append((f"todos[{todo_position}].items[{index}]", content))

    for fact in spec.facts:
        carrier = _carrier_beat(spec, fact.slug)
        for where, text in suspects:
            if where.startswith(carrier):
                continue
            _require(
                not answer_matches(text, (fact.answer, *fact.aliases)),
                f"case {spec.case_id!r}: {where} repeats the answer of fact {fact.slug!r} "
                f"({fact.answer!r}): {text[:120]!r}",
            )


def _carrier_beat(spec: CaseSpec, slug: str) -> str:
    """The label prefix of the beat that states a fact.

    A beat states it either in one of its steps or inside the tool output it
    renders, so the whole beat is exempt from the uniqueness check; everything
    else in the spec has to keep the answer out of the transcript.
    """
    for beat_position, beat in enumerate(spec.beats):
        if any(step.states_fact == slug for step in beat.steps):
            return f"beats[{beat_position}]."
        if beat.output is not None and any(
            answer_matches(line, _answers_of(spec, slug)) for line in beat.output.embedded
        ):
            return f"beats[{beat_position}]."
    raise DatasetError(f"case {spec.case_id!r}: no beat states fact {slug!r}")


def _answers_of(spec: CaseSpec, slug: str) -> tuple[str, ...]:
    for fact in spec.facts:
        if fact.slug == slug:
            return (fact.answer, *fact.aliases)
    raise DatasetError(f"case {spec.case_id!r}: unknown fact slug {slug!r}")


def validate_case(case: HistoryCase, spec: CaseSpec, build: CaseBuild) -> None:
    """Every invariant of the experimental design, checked before anything is written."""
    _check_shape(case, spec)
    _check_pinning(case)
    _check_facts(case, spec, build)
    _check_probes(case)
    _check_tool_outputs(case, spec)
    _check_todos(case, spec)
    _check_distractors(case, build)
    _check_repeated_tool_calls(case)
    _check_metadata(case)


# ---------------------------------------------------------------------------
# Dataset assembly and writing
# ---------------------------------------------------------------------------


def build_dataset(seed: int = DEFAULT_SEED, specs: Sequence[CaseSpec] | None = None) -> EvalDataset:
    """Build the five cases with one seed, in spec order."""
    chosen = tuple(specs) if specs is not None else case_specs()
    _require(
        len(chosen) == CASE_COUNT,
        f"the dataset must have {CASE_COUNT} cases, the specs define {len(chosen)}",
    )
    cases = tuple(build_case(spec, seed) for spec in chosen)
    dataset = EvalDataset(
        name=DATASET_NAME,
        cases=cases,
        seed=seed,
        generator=f"{GENERATOR_NAME}@v{GENERATOR_VERSION}",
    )
    validate_dataset(dataset)
    return dataset


def dumps(payload: Any) -> str:
    """The canonical serialization: sorted keys, fixed indent, trailing newline."""
    return json.dumps(payload, indent=JSON_INDENT, sort_keys=True, ensure_ascii=False) + "\n"


def write_dataset(dataset: EvalDataset, out_dir: Path) -> tuple[Path, ...]:
    """Write every case and the manifest; returns the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in dataset.cases:
        path = out_dir / CASE_FILE_TEMPLATE.format(case_id=case.id)
        path.write_text(dumps(case_to_dict(case)), encoding="utf-8")
        written.append(path)
    manifest = out_dir / MANIFEST_NAME
    manifest.write_text(dumps(dataset_to_dict(dataset)), encoding="utf-8")
    written.append(manifest)
    return tuple(written)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: generate, validate and write the frozen dataset."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"output directory (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help=f"generator seed (default: {DEFAULT_SEED})"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="build and validate without writing files"
    )
    args = parser.parse_args(argv)

    dataset = build_dataset(seed=args.seed)
    if not args.dry_run:
        for path in write_dataset(dataset, args.out):
            print(f"wrote {path}")
    stats = describe(dataset, window_tokens=WINDOW_TOKENS)
    print(format_stats(stats))
    return 0



# ---------------------------------------------------------------------------
# Beat constructors: they keep the case specs readable
# ---------------------------------------------------------------------------


def _user(text: str, **kwargs: Any) -> Step:
    return Step(role=Role.USER, text=text, **kwargs)


def _assistant(text: str, **kwargs: Any) -> Step:
    return Step(role=Role.ASSISTANT, text=text, **kwargs)


def _turn(anchor: float, *steps: Step, kind: str = "turn") -> Beat:
    return Beat(anchor=anchor, steps=steps, kind=kind)


def _tool(
    anchor: float,
    prelude: str,
    output: OutputSpec,
    *,
    followup: str = "",
    states_fact: str = "",
    trap_for: str = "",
) -> Beat:
    """An assistant tool call, its result, and an optional reading of it."""
    steps = [
        Step(
            role=Role.ASSISTANT,
            text=prelude,
            tool_call=output.tool,
            tool_arguments=dict(output.arguments),
        ),
        Step(
            role=Role.TOOL,
            text="",
            tool_name=output.tool,
            states_fact=states_fact,
            trap_for=trap_for,
        ),
    ]
    if followup:
        steps.append(_assistant(followup))
    return Beat(anchor=anchor, steps=tuple(steps), kind="tool", output=output)


def _repeat(
    anchor: float,
    *,
    tool: str,
    command: str,
    output: str,
    reason: str,
) -> Beat:
    """The same tool call repeated with the same arguments, as a loop would.

    ``REPEATED_TOOL_CALLS`` is ``GuardrailConfig.max_repeats``, so the dataset
    contains exactly the pattern the loop guardrail is supposed to catch.
    """
    steps: list[Step] = []
    for attempt in range(REPEATED_TOOL_CALLS):
        steps.append(
            Step(
                role=Role.ASSISTANT,
                text=reason,
                tool_call=tool,
                tool_arguments={"command": command},
                metadata={"distractor": "repeated_tool_call", "attempt": attempt + 1},
            )
        )
        steps.append(
            Step(
                role=Role.TOOL,
                text=output,
                tool_name=tool,
                metadata={"distractor": "repeated_tool_call", "attempt": attempt + 1},
            )
        )
    return Beat(anchor=anchor, steps=tuple(steps), kind="repeat")


def _todos(anchor: float, prelude: str, items: tuple[tuple[str, str], ...]) -> TodoBeat:
    return TodoBeat(anchor=anchor, prelude=prelude, items=items)


# ---------------------------------------------------------------------------
# Case 1 - debugging a Python payments API
# ---------------------------------------------------------------------------

API_VOCAB = Vocabulary(
    paths=(
        "src/payments/reconciler.py",
        "src/payments/gateway.py",
        "src/payments/webhooks.py",
        "src/api/routes/charges.py",
        "src/api/middleware/auth.py",
        "src/settings/runtime.py",
        "src/observability/metrics.py",
        "tests/test_reconciler.py",
        "tests/test_webhooks.py",
        "migrations/0007_add_charge_index.py",
        "deploy/staging.yaml",
        "docker-compose.yml",
    ),
    symbols=(
        "reconcile_pending_charges",
        "GatewayClient.charge",
        "WebhookVerifier.verify",
        "RetryPolicy.backoff",
        "ChargeStore.mark_settled",
        "idempotency_key",
        "load_runtime_settings",
        "require_bearer",
    ),
    commands=(
        "pytest -q tests/test_reconciler.py",
        "ruff check src",
        "uvicorn src.api.app:app --reload",
        "docker compose up -d gateway-mock",
        "git log --oneline -20",
        "grep -rn MAX_RETRIES src",
        "python -m src.scripts.replay_charges --dry-run",
    ),
    observations=(
        "The retry loop never re-reads the idempotency key, so a retried charge becomes a new one.",
        "The gateway answers 202 and the reconciler treats anything that is not 200 as a failure.",
        "The webhook signature is verified before the body is parsed, which hides the real error.",
        "Every failed attempt writes a metric, so the dashboard double counts a single charge.",
        "The staging config file is read before the environment, which is why the secret looks absent.",
        "ChargeStore.mark_settled is called inside the retry loop instead of after it.",
    ),
    questions=(
        "Did you confirm the staging secret is actually loaded, or are we chasing a config ghost?",
        "Can you check whether the reconciler still swallows the gateway error body?",
        "Is the double charge reproducible with the mock gateway, or only against staging?",
        "Should the metric be written per attempt or per charge? The dashboard disagrees with itself.",
        "Did the last deploy change the retry policy, or only the webhook verifier?",
    ),
    log_lines=(
        "charge ch_9f2c retried after backoff",
        "gateway responded 202 Accepted",
        "idempotency key missing, generating a new one",
        "webhook signature verified for evt_4417",
        "mark_settled skipped: charge still pending",
        "retry budget exhausted, parking charge in the dead letter table",
        "health probe answered in 3 ms",
    ),
    code_lines=(
        "    retries = settings.retry_limit",
        "    for attempt in range(retries):",
        "        response = client.charge(payload, key=idempotency_key)",
        "        if response.status_code == 202:",
        "            store.mark_settled(response.charge_id)",
        "            return response.charge_id",
        "        time.sleep(policy.backoff(attempt))",
        "    raise ReconcileFailed(payload['reference'])",
        "def require_bearer(request: Request) -> None:",
        "    if request.url.path == '/healthz':",
        "        return",
    ),
    notes=(
        "staging",
        "production",
        "dead letter",
        "idempotent",
        "webhook",
    ),
)

API_FACTS = (
    FactSpec(
        slug="retry-config",
        statement="The reconciler retries a pending charge at most five times, waiting 250 ms "
        "between attempts.",
        answer="retry limit 5 with a 250 ms backoff",
        aliases=("MAX_RETRIES = 5", "5 retries with a 250 ms backoff"),
        position="early",
        question="What retry limit did the team settle on for the reconciler?",
        expected="5",
        probe_aliases=("five", "retry limit 5", "5 retries"),
        trap="let's start with 3 retries and a 100 ms backoff",
    ),
    FactSpec(
        slug="webhook-secret",
        probed=False,
        statement="In staging the webhook signing key is read from the PAYMENTS_WEBHOOK_SECRET "
        "environment variable, never from the config file.",
        answer="PAYMENTS_WEBHOOK_SECRET",
        aliases=("the PAYMENTS_WEBHOOK_SECRET environment variable",),
        position="early",
        question="Which environment variable holds the webhook signing key in staging?",
        expected="PAYMENTS_WEBHOOK_SECRET",
    ),
    FactSpec(
        slug="healthz-open",
        probed=False,
        statement="The team kept the health endpoint unauthenticated because the load balancer "
        "probes it from outside the VPC.",
        answer="/healthz stays unauthenticated because the load balancer probes it from "
        "outside the VPC",
        aliases=("the load balancer probes it from outside the VPC",),
        position="early",
        question="Why did the team keep the /healthz endpoint unauthenticated?",
        expected="the load balancer probes it from outside the VPC",
        probe_aliases=("load balancer probes it from outside the VPC", "outside the VPC"),
    ),
    FactSpec(
        slug="bug-file",
        statement="The defect that double-charges pending payments lives in the reconciler module.",
        answer="the defect that double-charges pending payments is in src/payments/reconciler.py",
        aliases=("the double charge comes from the reconciler module, not the gateway client",),
        position="middle",
        question="Which file contains the defect that double-charges pending payments?",
        expected="src/payments/reconciler.py",
        probe_aliases=("payments/reconciler.py", "reconciler.py"),
    ),
    FactSpec(
        slug="failing-assertion",
        statement="The failing assertion buried in the test run reports a status mismatch between "
        "what the gateway sent and what the reconciler recorded.",
        answer="expected 202 but the reconciler saw 500",
        aliases=("AssertionError: expected 202 but the reconciler saw 500",),
        position="middle",
        question="What does the failing assertion in the reconciler test report?",
        expected="expected 202 but the reconciler saw 500",
        probe_aliases=("202 but the reconciler saw 500",),
    ),
    FactSpec(
        slug="gateway-port",
        probed=False,
        statement="The mock gateway used to reproduce the bug listens on port 8931.",
        answer="the mock gateway listens on port 8931",
        aliases=("the gateway mock answers on port 8931",),
        position="late",
        question="Which port does the mock gateway listen on?",
        expected="8931",
        probe_aliases=("port 8931", "localhost:8931"),
    ),
    FactSpec(
        slug="migrations-untouched",
        statement="The agent must not modify anything under the migrations directory during this "
        "investigation.",
        answer="never touch migrations/",
        aliases=("do not edit anything under migrations/", "migrations/ is off limits"),
        position="late",
        question="Which directory must stay untouched during this investigation?",
        expected="migrations/",
        probe_aliases=("never touch migrations/", "the migrations directory"),
    ),
    FactSpec(
        slug="reproducing-test-id",
        statement="One named test in the reconciler suite reproduces the double charge.",
        answer="the double charge reproduces in tests/test_reconciler.py::test_charge_idempotency",
        aliases=("test_charge_idempotency reproduces the double charge",),
        position="late",
        question="Which test id reproduces the double charge?",
        expected="tests/test_reconciler.py::test_charge_idempotency",
        probe_aliases=("test_charge_idempotency",),
    ),
)

API_BEATS = (
    _turn(
        0.02,
        _user(
            "Payments is double-charging pending charges in staging. The dashboard shows two "
            "settled charges for one order, and the webhook log looks clean. Start from the "
            "reconciler and work outward; do not restart from the gateway client."
        ),
        _assistant(
            "Understood. I will trace one charge end to end: reconciler, gateway client, webhook "
            "verifier, then the store write.",
        ),
    ),
    _turn(
        0.03,
        _user(
            "Before you change anything: let's start with 3 retries and a 100 ms backoff and see "
            "if the flake disappears on its own.",
            trap_for="retry-config",
            note="superseded later in the same session",
        ),
    ),
    _turn(
        0.05,
        _assistant(
            "The three-retry experiment did not hold: with a 100 ms backoff the gateway still "
            "answers before the store commit. Decision recorded - retry limit 5 with a 250 ms "
            "backoff, and the value is read from RetryPolicy.backoff rather than hard-coded.",
            states_fact="retry-config",
        ),
    ),
    _turn(
        0.10,
        _user(
            "One correction from the platform team, please write it down: staging reads the "
            "webhook signing key from PAYMENTS_WEBHOOK_SECRET, and it is never committed to the "
            "config file. If the verifier fails, that variable is the first thing to check.",
            states_fact="webhook-secret",
        ),
    ),
    _turn(
        0.15,
        _assistant(
            "I tried to put the bearer check back on the health route and the staging alarms "
            "fired immediately. Decision recorded: /healthz stays unauthenticated because the "
            "load balancer probes it from outside the VPC. Everything under /api keeps the "
            "bearer check.",
            states_fact="healthz-open",
        ),
    ),
    _tool(
        0.20,
        "Reading the reconciler top to bottom before touching it.",
        OutputSpec(
            kind="file_dump",
            tool="read_file",
            target="src/payments/reconciler.py",
            lines=FILE_DUMP_LINES_API,
            width=64,
            arguments={"path": "src/payments/reconciler.py"},
        ),
        followup="The loop re-reads the batch but never the idempotency key, which matches the "
        "double-charge symptom.",
    ),
    _tool(
        0.28,
        "Sweeping the repository for every caller of the retry policy.",
        OutputSpec(
            kind="grep",
            tool="grep",
            target="RetryPolicy",
            lines=GREP_LINES_API,
            width=56,
            arguments={"pattern": "RetryPolicy", "path": "."},
        ),
        followup="Three callers, only one of them passes a key.",
    ),
    _turn(
        0.36,
        _assistant(
            "Narrowed it down: the defect that double-charges pending payments is in "
            "src/payments/reconciler.py, in reconcile_pending_charges. The gateway client and the "
            "webhook verifier are innocent.",
            states_fact="bug-file",
        ),
    ),
    _tool(
        0.46,
        "Running the reconciler suite to capture the failure verbatim.",
        OutputSpec(
            kind="test_log",
            tool="execute",
            target="pytest -q tests/test_reconciler.py --durations=20",
            lines=TEST_LOG_LINES_API,
            width=24,
            summary=412,
            arguments={"command": "pytest -q tests/test_reconciler.py --durations=20"},
            embedded=("E       AssertionError: expected 202 but the reconciler saw 500",),
            embedded_at=(EMBEDDED_FACT_DEPTH,),
        ),
        states_fact="failing-assertion",
        followup="The assertion is buried in the middle of the run, which is exactly the kind of "
        "line a truncated tool output loses.",
    ),
    _tool(
        0.60,
        "Capturing the mock gateway traffic while the failing test runs.",
        OutputSpec(
            kind="run_log",
            tool="execute",
            target="docker compose logs --tail=all gateway-mock",
            lines=RUN_LOG_LINES_API,
            width=58,
            arguments={"command": "docker compose logs --tail=all gateway-mock"},
        ),
        followup="The gateway never returns 500; the 500 is produced by our own middleware.",
    ),
    _turn(
        0.70,
        _user("So the 500 is ours, not the gateway's? That changes the fix completely."),
        _assistant(
            "Yes. require_bearer raises before the route handler runs, the reconciler sees 500, "
            "and the retry loop charges again. The fix is the auth middleware plus one store "
            "write, not the gateway client.",
        ),
    ),
    _turn(
        0.86,
        _assistant(
            "For reproduction, note that the mock gateway listens on port 8931 - not 8080, which "
            "the compose file used before the last change.",
            states_fact="gateway-port",
        ),
    ),
    _turn(
        0.90,
        _user(
            "Two rules before you write the patch: never touch migrations/, and keep the diff "
            "inside src/ and tests/.",
            states_fact="migrations-untouched",
        ),
    ),
    _turn(
        0.93,
        _assistant(
            "The smallest reproduction is one test: the double charge reproduces in "
            "tests/test_reconciler.py::test_charge_idempotency, and it fails in isolation, so we "
            "do not need the whole suite to verify the fix.",
            states_fact="reproducing-test-id",
        ),
    ),
    _repeat(
        0.32,
        tool="execute",
        command="curl -sS -o /dev/null -w '%{http_code}' http://localhost:8931/healthz",
        output="200\n200\nhealth probe answered in 3 ms",
        reason="Probing the mock gateway health endpoint again to see whether the 500 is "
        "intermittent.",
    ),
)

API_TODOS = (
    _todos(
        0.18,
        "Writing down the investigation plan so the session keeps its shape.",
        (
            ("Trace one charge through the reconciler", "in_progress"),
            ("Confirm the staging webhook secret is loaded", "pending"),
            ("Reproduce the double charge against the mock gateway", "pending"),
            ("Write the failing test before the fix", "pending"),
        ),
    ),
    _todos(
        0.52,
        "Updating the board after the reproduction.",
        (
            ("Trace one charge through the reconciler", "completed"),
            ("Confirm the staging webhook secret is loaded", "completed"),
            ("Reproduce the double charge against the mock gateway", "in_progress"),
            ("Write the failing test before the fix", "pending"),
        ),
    ),
    _todos(
        0.80,
        "Board update before the patch.",
        (
            ("Trace one charge through the reconciler", "completed"),
            ("Confirm the staging webhook secret is loaded", "completed"),
            ("Reproduce the double charge against the mock gateway", "completed"),
            ("Write the failing test before the fix", "in_progress"),
        ),
    ),
)


def _case_api_service() -> CaseSpec:
    return CaseSpec(
        index=1,
        slug="api-service-debug",
        domain="python-api-service",
        description="A debugging session on a Python payments API: a double-charge bug traced "
        "from the reconciler through the auth middleware, with a failing assertion buried in a "
        "2000-line test log.",
        task="Payments double-charges pending charges in staging. Find the defect, reproduce it "
        "with a single test, and propose the smallest patch. Report every decision you take "
        "before you take it.",
        notes="Stresses retention of an early config decision that is first stated wrong and "
        "corrected later, plus one critical fact hidden in the middle of a tool output that "
        "exceeds both truncation ceilings.",
        message_target=96,
        contract="Before you push anything, re-run the reproducing test and keep the patch inside "
        "the source and test folders; I review it tonight.",
        vocabulary=API_VOCAB,
        facts=API_FACTS,
        beats=API_BEATS,
        todos=API_TODOS,
    )


# ---------------------------------------------------------------------------
# Case 2 - a TypeScript checkout refactor
# ---------------------------------------------------------------------------

WEB_VOCAB = Vocabulary(
    paths=(
        "packages/web/src/features/checkout/useCheckoutForm.ts",
        "packages/web/src/features/checkout/PaymentWizard.tsx",
        "packages/web/src/features/checkout/ExpressCheckoutButton.tsx",
        "packages/web/src/features/checkout/validation.ts",
        "packages/web/src/api/client.ts",
        "packages/ui/src/Button.tsx",
        "packages/web/vite.config.ts",
        "packages/web/src/features/checkout/__tests__/useCheckoutForm.spec.ts",
        "tsconfig.base.json",
        "pnpm-workspace.yaml",
    ),
    symbols=(
        "useCheckoutForm",
        "PaymentWizard",
        "ExpressCheckoutButton",
        "enableExpressCheckout",
        "validateCheckoutPayload",
        "submitOrder",
        "legacyFetch",
        "queryClient",
    ),
    commands=(
        "pnpm --filter web typecheck",
        "pnpm --filter web test -- --run",
        "pnpm lint",
        "pnpm build",
        "git grep -n legacyFetch",
        "pnpm why @tanstack/react-query",
    ),
    observations=(
        "The wizard keeps its own copy of the cart, so a price change never reaches the summary.",
        "Every field revalidates on each keystroke, which is why typing feels slow on mobile.",
        "The express button reads the flag at module scope, so a toggle needs a full reload.",
        "Two components still import the legacy fetch wrapper, and one of them is dead code.",
        "The spec file mounts the hook twice, so the assertion count doubles in the report.",
    ),
    questions=(
        "Are we keeping the cart in the hook or in the query cache? The two disagree today.",
        "Did the design system button change its disabled contract in the last release?",
        "Can the express button be toggled without a reload, or is that out of scope?",
        "Is the legacy fetch wrapper still used by anything we cannot delete?",
    ),
    log_lines=(
        "type error: property 'cart' does not exist on type 'CheckoutState'",
        "warning: unused import ExpressCheckoutButton",
        "vitest: 41 passed, 2 skipped",
        "vite: rebuilt the checkout chunk in 812 ms",
        "eslint: prefer the query cache over local component state",
    ),
    code_lines=(
        "  const { cart, setCart } = useCheckoutForm({ orderId });",
        "  if (!enableExpressCheckout) return null;",
        "  return <ExpressCheckoutButton onSubmit={submitOrder} />;",
        "  const payload = validateCheckoutPayload(cart, address);",
        "  export const legacyFetch = (url: string) => fetch(url);",
        "  useQuery({ queryKey: ['cart', orderId], queryFn: loadCart });",
    ),
    notes=("checkout", "express", "wizard", "summary"),
)

WEB_FACTS = (
    FactSpec(
        slug="typescript-pin",
        statement="The workspace pins one exact TypeScript version for the whole refactor.",
        answer="TypeScript 5.6.3",
        aliases=("typescript@5.6.3", "pinned to TypeScript 5.6.3"),
        position="early",
        question="Which TypeScript version is pinned for this refactor?",
        expected="TypeScript 5.6.3",
        probe_aliases=("5.6.3", "typescript@5.6.3"),
        trap="let's jump straight to the TypeScript 5.7 beta",
    ),
    FactSpec(
        slug="state-decision",
        probed=False,
        statement="The wizard state moves out of Redux into React Query, because the state never "
        "outlives the checkout route.",
        answer="drop Redux for the wizard state and keep React Query for server state",
        aliases=("wizard state moves to React Query", "no Redux in the checkout wizard"),
        position="early",
        question="What did the team decide about the checkout wizard state?",
        expected="drop Redux for the wizard state and keep React Query for server state",
        probe_aliases=("React Query", "drop Redux"),
    ),
    FactSpec(
        slug="hook-file",
        statement="The hook that owns the checkout form state lives in one file under the "
        "checkout feature.",
        answer="the checkout form state lives in "
        "packages/web/src/features/checkout/useCheckoutForm.ts",
        aliases=("the hook that owns the form state is useCheckoutForm.ts",),
        position="middle",
        question="Which file holds the hook that owns the checkout form state?",
        expected="packages/web/src/features/checkout/useCheckoutForm.ts",
        probe_aliases=("useCheckoutForm.ts",),
    ),
    FactSpec(
        slug="express-flag",
        probed=False,
        statement="The express checkout button is gated behind one feature flag.",
        answer="the express button is gated behind the enableExpressCheckout flag",
        aliases=("enableExpressCheckout gates the express checkout button",),
        position="middle",
        question="Which feature flag gates the express checkout button?",
        expected="enableExpressCheckout",
    ),
    FactSpec(
        slug="last-legacy-caller",
        statement="The last live caller of the legacy fetch wrapper is one file in the api "
        "folder, found by sweeping the repository.",
        answer="packages/web/src/api/legacy/session.ts",
        aliases=("api/legacy/session.ts", "legacy/session.ts"),
        position="middle",
        question="Which file is the last live caller of legacyFetch?",
        expected="packages/web/src/api/legacy/session.ts",
        probe_aliases=("api/legacy/session.ts", "legacy/session.ts"),
    ),
    FactSpec(
        slug="typecheck-command",
        statement="The command that gates the refactor in CI type-checks only the web package.",
        answer="the command that type-checks the web package is pnpm --filter web typecheck",
        aliases=("run pnpm --filter web typecheck before committing",),
        position="late",
        question="Which command type-checks the web package before a commit?",
        expected="pnpm --filter web typecheck",
        probe_aliases=("--filter web typecheck",),
    ),
    FactSpec(
        slug="public-prop",
        statement="One public prop of the wizard must keep its name, because partner apps pass "
        "it.",
        answer="do not rename the public prop onSubmit",
        aliases=("keep the public prop onSubmit", "onSubmit must keep its name"),
        position="late",
        question="Which public prop must keep its name during the refactor?",
        expected="do not rename the public prop onSubmit",
        probe_aliases=("onSubmit", "the public prop onSubmit"),
    ),
)

WEB_BEATS = (
    _turn(
        0.02,
        _user(
            "We are splitting the checkout wizard into a hook plus presentational components. "
            "Half the team wants to keep Redux, the other half wants it gone. Decide first, "
            "then refactor; do not touch the design system package."
        ),
        _assistant(
            "I will start by mapping what the wizard actually stores, then propose the state "
            "boundary before moving any component.",
        ),
    ),
    _turn(
        0.04,
        _user(
            "Someone suggested we jump straight to the TypeScript 5.7 beta so the new decorator "
            "types work. Let's try that first.",
            trap_for="typescript-pin",
            note="superseded a few turns later",
        ),
    ),
    _turn(
        0.07,
        _assistant(
            "The beta breaks the vite plugin, so that is off the table. We pin TypeScript 5.6.3 "
            "for the whole workspace and revisit after the refactor lands.",
            states_fact="typescript-pin",
        ),
    ),
    _turn(
        0.13,
        _assistant(
            "Decision: drop Redux for the wizard state and keep React Query for server state. "
            "The wizard state never outlives the checkout route, so a global store only adds "
            "synchronization bugs.",
            states_fact="state-decision",
        ),
    ),
    _tool(
        0.22,
        "Reading the current hook before splitting it.",
        OutputSpec(
            kind="file_dump",
            tool="read_file",
            target="packages/web/src/features/checkout/useCheckoutForm.ts",
            lines=FILE_DUMP_LINES_WEB,
            width=70,
            arguments={"path": "packages/web/src/features/checkout/useCheckoutForm.ts"},
        ),
        followup="The hook already owns validation; only the cart duplication has to go.",
    ),
    _turn(
        0.34,
        _assistant(
            "The file to split is the one that holds the form state, the validation call and "
            "the cart copy in one closure: the checkout form state lives in "
            "packages/web/src/features/checkout/useCheckoutForm.ts.",
            states_fact="hook-file",
        ),
    ),
    _turn(
        0.42,
        _user(
            "The express button disappeared in staging again. Which flag is it behind this time?"
        ),
        _assistant(
            "The express button is gated behind the enableExpressCheckout flag, read at module "
            "scope. That is why toggling it needs a reload, and it is the second thing I want to "
            "move into the hook.",
            states_fact="express-flag",
        ),
    ),
    _tool(
        0.50,
        "Sweeping the repository for every remaining caller of the legacy fetch wrapper.",
        OutputSpec(
            kind="grep",
            tool="grep",
            target="legacyFetch",
            lines=GREP_LINES_WEB,
            width=26,
            arguments={"pattern": "legacyFetch", "path": "."},
            embedded=("packages/web/src/api/legacy/session.ts:117: export const sessionFetch = "
                      "legacyFetch;",),
            embedded_at=(EMBEDDED_FACT_DEPTH,),
        ),
        states_fact="last-legacy-caller",
        followup="Every other hit is a test fixture; the only live caller is in the api folder.",
    ),
    _tool(
        0.64,
        "Type-checking the web package after the first extraction.",
        OutputSpec(
            kind="run_log",
            tool="execute",
            target="pnpm --filter web typecheck",
            lines=TSC_LINES_WEB,
            width=62,
            arguments={"command": "pnpm --filter web typecheck"},
        ),
        followup="Four errors, all of them the cart type; none in the design system package.",
    ),
    _turn(
        0.86,
        _assistant(
            "Before you commit, remember that the command that type-checks the web package is "
            "pnpm --filter web typecheck; the workspace-wide check hides the web errors behind "
            "the docs package.",
            states_fact="typecheck-command",
        ),
    ),
    _turn(
        0.91,
        _user(
            "One hard rule for the whole refactor: do not rename the public prop onSubmit. "
            "Partner apps pass it and we cannot coordinate a release with them.",
            states_fact="public-prop",
        ),
    ),
    _repeat(
        0.30,
        tool="execute",
        command="pnpm --filter web typecheck",
        output="web:typecheck: 4 errors in 2 files\nweb:typecheck: cart type mismatch",
        reason="Re-running the type check to see whether the error count moved after the "
        "extraction.",
    ),
)

WEB_TODOS = (
    _todos(
        0.18,
        "Board for the refactor, so the split stays reviewable.",
        (
            ("Map what the wizard stores", "in_progress"),
            ("Move the cart into the query cache", "pending"),
            ("Extract the express button gate", "pending"),
            ("Delete the legacy fetch wrapper", "pending"),
        ),
    ),
    _todos(
        0.55,
        "Board update after the extraction.",
        (
            ("Map what the wizard stores", "completed"),
            ("Move the cart into the query cache", "in_progress"),
            ("Extract the express button gate", "pending"),
            ("Delete the legacy fetch wrapper", "pending"),
        ),
    ),
    _todos(
        0.78,
        "Board update before the typecheck run.",
        (
            ("Map what the wizard stores", "completed"),
            ("Move the cart into the query cache", "completed"),
            ("Extract the express button gate", "completed"),
            ("Delete the legacy fetch wrapper", "in_progress"),
        ),
    ),
)


def _case_frontend_refactor() -> CaseSpec:
    return CaseSpec(
        index=2,
        slug="frontend-refactor",
        domain="typescript-frontend",
        description="A frontend refactor of a checkout wizard: a state-management decision, a "
        "pinned compiler version and a repository-wide sweep whose only live hit sits in the "
        "middle of a 2000-line grep result.",
        task="Split the checkout wizard into a hook plus presentational components, decide the "
        "state boundary first, and keep the design system package untouched.",
        notes="Stresses a decision stated as a correction of an earlier proposal, and a fact "
        "whose only occurrence is one line inside a grep sweep above both truncation ceilings.",
        message_target=112,
        contract="Keep every commit type-checking on its own, and leave the design system package "
        "out of the diff; I will review the split commit by commit.",
        vocabulary=WEB_VOCAB,
        facts=WEB_FACTS,
        beats=WEB_BEATS,
        todos=WEB_TODOS,
    )


# ---------------------------------------------------------------------------
# Case 3 - a data pipeline migration incident
# ---------------------------------------------------------------------------

PIPELINE_VOCAB = Vocabulary(
    paths=(
        "pipelines/order_events/extract.py",
        "pipelines/order_events/load.py",
        "pipelines/order_events/dedupe.py",
        "migrations/20260214_003_split_order_events.sql",
        "dags/order_events_backfill.py",
        "sql/analytics/order_events.sql",
        "scripts/rollback_order_events.py",
        "tests/pipelines/test_order_events.py",
        "config/pipeline.yaml",
    ),
    symbols=(
        "split_order_events",
        "backfill_batch",
        "OrderEventsLoader.load",
        "dedupe_key",
        "event_ts",
        "run_backfill",
        "shard_reader",
    ),
    commands=(
        "airflow dags backfill order_events -s 2026-02-01",
        "psql -f migrations/20260214_003_split_order_events.sql",
        "dbt run --select order_events",
        "python scripts/rollback_order_events.py --dry-run",
        "grep -rn dedupe_key pipelines",
    ),
    observations=(
        "The loader writes rows before the dedupe key is computed, so duplicates land first.",
        "Shard 07 is the only one that reads from the replica, which explains its lag.",
        "The backfill reuses one connection per batch and never resets the lock timeout.",
        "The migration adds a column with a default, which rewrites the whole table.",
        "The metrics CSV is exported per shard, and the export truncates the duplicate rate.",
    ),
    questions=(
        "Are we backfilling the whole month or only the shards that reported duplicates?",
        "Did anyone check the replica lag before shard 07 started?",
        "Is the rollback script idempotent, or does it need a clean batch table?",
        "Can we pause the DAG without losing the watermark?",
    ),
    log_lines=(
        "batch committed, rows written 4987",
        "lock acquired on analytics.order_events",
        "shard reader lagging by 42 s",
        "dedupe key recomputed for 118 rows",
        "COPY finished in 9.4 s",
        "watermark advanced to 2026-02-14T03:00:00Z",
    ),
    code_lines=(
        "    with engine.begin() as connection:",
        "        connection.execute(copy_stmt, batch)",
        "    dedupe_key = f'{row.order_id}:{row.event_ts}'",
        "    if shard == 7:",
        "        reader = replica_reader()",
        "    loader.load(batch, table='analytics.order_events')",
    ),
    columns=("shard", "batch_id", "rows_read", "rows_written", "duplicate_rate", "duration_ms"),
    notes=("shard", "batch", "replica", "warehouse", "backfill"),
    packages=(),
)

PIPELINE_FACTS = (
    FactSpec(
        slug="target-table",
        probed=False,
        statement="The migration splits one analytics table, and that table is the target of "
        "every backfill batch.",
        answer="the table the migration splits is analytics.order_events",
        aliases=("every backfill batch writes to analytics.order_events",),
        position="early",
        question="Which table does the migration split?",
        expected="analytics.order_events",
        probe_aliases=("order_events",),
    ),
    FactSpec(
        slug="copy-decision",
        statement="The backfill loads with COPY instead of a row-by-row insert, because the "
        "warehouse throttles single-row writes.",
        answer="backfill with COPY, not INSERT ... SELECT, because the warehouse throttles "
        "row-by-row writes",
        aliases=("COPY instead of INSERT ... SELECT", "backfill with COPY"),
        position="early",
        question="How did the team decide to load the backfill batches?",
        expected="backfill with COPY, not INSERT ... SELECT",
        probe_aliases=("COPY", "COPY instead of INSERT ... SELECT"),
    ),
    FactSpec(
        slug="migration-file",
        probed=False,
        statement="The migration that splits the table is one dated file under migrations/.",
        answer="the migration that splits the table is "
        "migrations/20260214_003_split_order_events.sql",
        aliases=("20260214_003_split_order_events.sql is the migration that split the table",),
        position="middle",
        question="Which migration file splits the order events table?",
        expected="migrations/20260214_003_split_order_events.sql",
        probe_aliases=("20260214_003_split_order_events.sql",),
    ),
    FactSpec(
        slug="batch-size",
        statement="The backfill runs in fixed-size batches with a pause between them, so the "
        "replica can catch up.",
        answer="batch size 5000 with a 2 s sleep between batches",
        aliases=("5000 rows per batch", "batch size 5000"),
        position="middle",
        question="What batch size did the team settle on for the backfill?",
        expected="batch size 5000 with a 2 s sleep",
        probe_aliases=("5000", "5000 rows per batch"),
        trap="start with batches of 20000 rows and no sleep",
    ),
    FactSpec(
        slug="worst-shard",
        statement="One shard peaks at a duplicate rate far above the others, visible only in the "
        "exported metrics table.",
        answer="shard 07 peaked at a duplicate_rate of 0.0413",
        aliases=("duplicate_rate 0.0413", "shard 07 at 0.0413"),
        position="middle",
        question="Which shard peaked at the highest duplicate rate, and at what value?",
        expected="shard 07 peaked at a duplicate_rate of 0.0413",
        probe_aliases=("0.0413", "shard 07"),
    ),
    FactSpec(
        slug="lock-timeout-var",
        probed=False,
        statement="The lock timeout of the backfill is read from one environment variable.",
        answer="PIPELINE_LOCK_TIMEOUT_MS",
        aliases=("the PIPELINE_LOCK_TIMEOUT_MS environment variable",),
        position="late",
        question="Which environment variable sets the backfill lock timeout?",
        expected="PIPELINE_LOCK_TIMEOUT_MS",
    ),
    FactSpec(
        slug="no-vacuum",
        statement="One maintenance command is forbidden on the production warehouse during the "
        "incident.",
        answer="never run VACUUM FULL on the production warehouse",
        aliases=("no VACUUM FULL in production",),
        position="late",
        question="Which maintenance command is forbidden on production during the incident?",
        expected="never run VACUUM FULL on the production warehouse",
        probe_aliases=("VACUUM FULL",),
    ),
)

PIPELINE_BEATS = (
    _turn(
        0.02,
        _user(
            "The order events pipeline duplicated roughly four percent of yesterday's rows during "
            "the split migration. We need the cause, the corrected backfill and a rollback we "
            "trust, in that order."
        ),
        _assistant(
            "I will start from the migration and the loader, then quantify the duplicates per "
            "shard before proposing a backfill.",
        ),
    ),
    _turn(
        0.06,
        _assistant(
            "Scope confirmed: the table the migration splits is analytics.order_events, and "
            "every batch of the backfill writes to that same table, so nothing else needs a lock.",
            states_fact="target-table",
        ),
    ),
    _turn(
        0.12,
        _assistant(
            "Loading decision: backfill with COPY, not INSERT ... SELECT, because the warehouse "
            "throttles row-by-row writes and we already lost an hour to it this morning.",
            states_fact="copy-decision",
        ),
    ),
    _turn(
        0.20,
        _user(
            "One operator suggested we start with batches of 20000 rows and no sleep, to finish "
            "before the analytics standup.",
            trap_for="batch-size",
            note="superseded once the replica lag was measured",
        ),
    ),
    _tool(
        0.28,
        "Reading the migration that started the incident.",
        OutputSpec(
            kind="run_log",
            tool="execute",
            target="psql -f migrations/20260214_003_split_order_events.sql --echo-all",
            lines=EXPLAIN_LINES_PIPELINE,
            width=80,
            arguments={
                "command": "psql -f migrations/20260214_003_split_order_events.sql --echo-all"
            },
        ),
        followup="The migration adds a column with a default, which rewrites the table and holds "
        "the lock longer than the DAG expects.",
    ),
    _turn(
        0.36,
        _assistant(
            "The migration that splits the table is "
            "migrations/20260214_003_split_order_events.sql; it is the third migration of the "
            "day and the only one that touches the events table.",
            states_fact="migration-file",
        ),
    ),
    _tool(
        0.46,
        "Pulling the per-shard metrics export to find the worst offender.",
        OutputSpec(
            kind="csv",
            tool="execute",
            target="python -m pipelines.order_events.report --format csv",
            lines=CSV_LINES_PIPELINE,
            width=40,
            arguments={"command": "python -m pipelines.order_events.report --format csv"},
            embedded=(
                "# WARNING shard 07 peaked at a duplicate_rate of 0.0413 "
                "(batch_2026_02_14_07, replica reader)",
                "07,batch_2026_02_14_07,499812,498233,0.0413,9412",
            ),
            embedded_at=(EMBEDDED_FACT_DEPTH, EMBEDDED_FACT_DEPTH + 0.01),
        ),
        states_fact="worst-shard",
        followup="The report writes one warning line in the middle of the export, and that line "
        "is the whole incident.",
    ),
    _turn(
        0.58,
        _assistant(
            "Corrected pacing: batch size 5000 with a 2 s sleep between batches. Twenty thousand "
            "rows with no sleep is what produced the lag in the first place.",
            states_fact="batch-size",
        ),
    ),
    _tool(
        0.68,
        "Watching the corrected backfill for one shard.",
        OutputSpec(
            kind="run_log",
            tool="execute",
            target="airflow tasks logs order_events_backfill backfill_shard 2026-02-14",
            lines=SQL_LOG_LINES_PIPELINE,
            width=58,
            arguments={
                "command": "airflow tasks logs order_events_backfill backfill_shard 2026-02-14"
            },
        ),
        followup="No lock timeouts at 5000 rows, and the replica stays inside two seconds.",
    ),
    _turn(
        0.86,
        _assistant(
            "For the runbook: the lock timeout is read from PIPELINE_LOCK_TIMEOUT_MS, and the "
            "default in config/pipeline.yaml is ignored when the variable is set.",
            states_fact="lock-timeout-var",
        ),
    ),
    _turn(
        0.91,
        _user(
            "And whatever you do, never run VACUUM FULL on the production warehouse - it takes an "
            "exclusive lock and we would turn an incident into an outage.",
            states_fact="no-vacuum",
        ),
    ),
    _repeat(
        0.32,
        tool="execute",
        command="python scripts/rollback_order_events.py --dry-run",
        output="dry run: 14 batches would be reverted, 0 rows written\nlock acquired, lock released",
        reason="Running the rollback dry run again to confirm it is idempotent.",
    ),
)

PIPELINE_TODOS = (
    _todos(
        0.16,
        "Incident board, so the on-call handover has the same picture.",
        (
            ("Quantify duplicates per shard", "in_progress"),
            ("Identify the migration that rewrote the table", "pending"),
            ("Correct the backfill pacing", "pending"),
            ("Verify the rollback script on a copy", "pending"),
        ),
    ),
    _todos(
        0.52,
        "Board update after the metrics export.",
        (
            ("Quantify duplicates per shard", "completed"),
            ("Identify the migration that rewrote the table", "completed"),
            ("Correct the backfill pacing", "in_progress"),
            ("Verify the rollback script on a copy", "pending"),
        ),
    ),
    _todos(
        0.80,
        "Board update before the runbook change.",
        (
            ("Quantify duplicates per shard", "completed"),
            ("Identify the migration that rewrote the table", "completed"),
            ("Correct the backfill pacing", "completed"),
            ("Verify the rollback script on a copy", "in_progress"),
        ),
    ),
)


def _case_pipeline_incident() -> CaseSpec:
    return CaseSpec(
        index=3,
        slug="pipeline-migration-incident",
        domain="data-pipeline",
        description="An incident review of a SQL migration that duplicated rows: per-shard "
        "metrics exported as a 2000-line CSV, a corrected backfill pacing and a runbook "
        "constraint restated at the end.",
        task="Find why the order events pipeline duplicated rows, correct the backfill and write "
        "the rollback the on-call team can trust.",
        notes="Stresses a numeric decision that is first proposed wrong, and a single metric row "
        "buried in the middle of a CSV export above both truncation ceilings.",
        message_target=84,
        contract="Every change to the pipeline goes through the dry-run script first, and the "
        "incident timeline stays in the channel; do not edit the DAG in place.",
        vocabulary=PIPELINE_VOCAB,
        facts=PIPELINE_FACTS,
        beats=PIPELINE_BEATS,
        todos=PIPELINE_TODOS,
    )


# ---------------------------------------------------------------------------
# Case 4 - a flaky test investigation in a CI repository
# ---------------------------------------------------------------------------

CI_VOCAB = Vocabulary(
    paths=(
        "tests/test_reconciler.py",
        "tests/conftest.py",
        "tests/test_webhooks.py",
        "tests/support/fake_clock.py",
        ".github/workflows/ci.yml",
        ".github/workflows/nightly.yml",
        "ci/matrix.py",
        "src/payments/reconciler.py",
        "src/observability/timing.py",
        "pytest.ini",
    ),
    symbols=(
        "fake_clock",
        "FrozenClock",
        "retry_until_settled",
        "pytest.mark.quarantine",
        "gateway_stub",
        "advance_clock",
    ),
    commands=(
        "pytest -q --count 40 tests/test_reconciler.py",
        "pytest -q -p no:randomly",
        "act -j tests --reuse",
        "git log --oneline --since=14.days",
        "grep -rn fake_clock tests",
    ),
    observations=(
        "The fake clock is built once per session and never reset between tests.",
        "Randomly reorders the suite, so the flake only appears in one order.",
        "The retry assertion reads the wall clock instead of the injected one.",
        "The nightly workflow pins an older runner image than the pull request one.",
        "Two fixtures share one gateway stub, and the stub keeps a call log.",
    ),
    questions=(
        "Does the flake survive with the random order plugin disabled?",
        "How many runs do we need before we call it reproducible?",
        "Is the quarantine marker honoured by the nightly workflow?",
        "Did the runner image change in the same week the flake started?",
    ),
    log_lines=(
        "worker gw2 finished in 4.81 s",
        "test order shuffled by pytest-randomly",
        "clock advanced by 250 ms",
        "gateway stub recorded 3 calls",
        "retry attempt 2 of 5",
        "quarantine marker applied, test deselected",
    ),
    code_lines=(
        "@pytest.fixture(scope='session')",
        "def fake_clock() -> FrozenClock:",
        "    return FrozenClock(start=EPOCH)",
        "def test_retry_backoff(fake_clock, gateway_stub):",
        "    fake_clock.advance(BACKOFF_STEP)",
        "    assert gateway_stub.calls == 5",
        "@pytest.mark.quarantine(reason='CI-482')",
    ),
    notes=("nightly", "pull request", "matrix", "runner"),
)

CI_FACTS = (
    FactSpec(
        slug="flaky-test",
        probed=False,
        statement="One named test in the reconciler suite is the flaky one the whole "
        "investigation is about.",
        answer="the flaky test is tests/test_reconciler.py::test_retry_backoff",
        aliases=("the test that flakes is test_retry_backoff in the reconciler suite",),
        position="early",
        question="Which test id is the flaky one?",
        expected="tests/test_reconciler.py::test_retry_backoff",
        probe_aliases=("test_retry_backoff",),
    ),
    FactSpec(
        slug="failure-rate",
        statement="The test fails in a small, measured fraction of repeated runs.",
        answer="it fails on 3 of 40 runs",
        aliases=("3 failures out of 40 runs", "3 of 40"),
        position="early",
        question="How often does the flaky test fail when it is run repeatedly?",
        expected="3 of 40 runs",
        probe_aliases=("it fails on 3 of 40 runs", "3 out of 40"),
    ),
    FactSpec(
        slug="shared-clock",
        statement="The root cause is one fixture whose scope makes it shared between tests.",
        answer="the fake clock is shared between fixtures because it is session scoped",
        aliases=("session scoped fake clock", "the fake clock is session scoped"),
        position="middle",
        question="What is the root cause of the flake?",
        expected="the fake clock is shared between fixtures because it is session scoped",
        probe_aliases=("session scoped", "the fake clock is shared"),
    ),
    FactSpec(
        slug="failing-assert",
        statement="The assertion that fails inside the long run compares the number of gateway "
        "calls with the retry limit.",
        answer="assert gateway_stub.calls == 5, got 6 calls",
        aliases=("gateway_stub.calls == 5, got 6 calls",),
        position="middle",
        question="What does the failing assertion inside the repeated run report?",
        expected="assert gateway_stub.calls == 5, got 6 calls",
        probe_aliases=("got 6 calls",),
    ),
    FactSpec(
        slug="quarantine-decision",
        statement="The team quarantines the test with a marker and tracks it in one ticket.",
        answer="quarantine it with @pytest.mark.quarantine and track it in CI-482",
        aliases=("the test goes into quarantine behind a marker, tracked in ticket CI-482",),
        position="late",
        question="How did the team decide to handle the flaky test for now?",
        expected="quarantine it with @pytest.mark.quarantine and track it in CI-482",
        probe_aliases=("@pytest.mark.quarantine", "CI-482"),
    ),
    FactSpec(
        slug="ci-timeout",
        probed=False,
        statement="The CI workflow has one hard timeout for the whole test job.",
        answer="the CI test job times out after 900 s",
        aliases=("CI timeout 900 s", "900 s"),
        position="late",
        question="What is the hard timeout of the CI test job?",
        expected="900 s",
        probe_aliases=("the CI test job times out after 900 s", "900 seconds"),
    ),
    FactSpec(
        slug="no-sleeps",
        probed=False,
        statement="One practice is explicitly forbidden when fixing flaky tests in this "
        "repository.",
        answer="never add sleeps to make a test pass",
        aliases=("no sleeps in tests", "do not fix a flake with a sleep"),
        position="late",
        question="Which practice is forbidden when fixing flaky tests here?",
        expected="never add sleeps to make a test pass",
        probe_aliases=("no sleeps in tests", "adding sleeps"),
    ),
)

CI_BEATS = (
    _turn(
        0.02,
        _user(
            "CI is red twice a week and nobody believes it any more. Find out whether the "
            "reconciler test is genuinely flaky or whether our runner is broken, and give me a "
            "decision we can defend in the retro."
        ),
        _assistant(
            "I will measure the failure rate first: a flake nobody can rate is a rumour, not a "
            "bug.",
        ),
    ),
    _turn(
        0.06,
        _assistant(
            "The flaky test is tests/test_reconciler.py::test_retry_backoff; every other "
            "failure in the last two weeks traces back to it.",
            states_fact="flaky-test",
        ),
    ),
    _turn(
        0.09,
        _user(
            "My guess before you measure anything: one run in twenty, and only on the nightly "
            "runner. That is what it felt like last sprint.",
            trap_for="failure-rate",
            note="superseded by the measured rate a few turns later",
        ),
    ),
    _turn(
        0.12,
        _assistant(
            "Measured, not guessed: it fails on 3 of 40 runs with the random order plugin on, and "
            "on none of 40 with the plugin off.",
            states_fact="failure-rate",
        ),
    ),
    _tool(
        0.24,
        "Running the test forty times to capture every failure verbatim.",
        OutputSpec(
            kind="test_log",
            tool="execute",
            target="pytest -q --count 40 tests/test_reconciler.py",
            lines=PYTEST_LINES_CI,
            width=26,
            summary=40,
            arguments={
                "command": "pytest -q --count 40 tests/test_reconciler.py"
            },
            embedded=("E       assert gateway_stub.calls == 5, got 6 calls",),
            embedded_at=(EMBEDDED_FACT_DEPTH,),
        ),
        states_fact="failing-assert",
        followup="The failures are not clustered at the end of the run, which rules out a "
        "resource leak in the runner.",
    ),
    _turn(
        0.40,
        _user("Does the order matter, or is it the fixtures talking to each other?"),
        _assistant(
            "Order matters. With the plugin off the suite is green, so the tests are not "
            "independent - something survives between them.",
        ),
    ),
    _tool(
        0.50,
        "Sweeping the fixtures for anything session scoped.",
        OutputSpec(
            kind="grep",
            tool="grep",
            target="scope=.session.",
            lines=MATRIX_LINES_CI,
            width=56,
            arguments={"pattern": "scope=.session.", "path": "tests"},
        ),
        followup="Two fixtures are session scoped, and one of them holds a clock.",
    ),
    _turn(
        0.60,
        _assistant(
            "Root cause: the fake clock is shared between fixtures because it is session scoped, "
            "so a test that advances it leaves the next test in the future.",
            states_fact="shared-clock",
        ),
    ),
    _tool(
        0.70,
        "Checking when the flake started against the workflow history.",
        OutputSpec(
            kind="run_log",
            tool="execute",
            target="git log --oneline --since=14.days -- .github/workflows tests",
            lines=GIT_LOG_LINES_CI,
            width=60,
            arguments={"command": "git log --oneline --since=14.days -- .github/workflows tests"},
        ),
        followup="The flake predates the runner image change, so the image is not the cause.",
    ),
    _turn(
        0.86,
        _assistant(
            "Decision for the retro: quarantine it with @pytest.mark.quarantine and track it in "
            "CI-482, and move the clock fixture to function scope in the same pull request.",
            states_fact="quarantine-decision",
        ),
    ),
    _turn(
        0.90,
        _assistant(
            "Also worth writing down: the CI test job times out after 900 s, so a forty-run "
            "reproduction has to stay under that or it is killed mid-suite.",
            states_fact="ci-timeout",
        ),
    ),
    _turn(
        0.93,
        _user(
            "One rule for the fix, and it goes in the contributing guide: never add sleeps to "
            "make a test pass. Inject the clock instead.",
            states_fact="no-sleeps",
        ),
    ),
    _repeat(
        0.32,
        tool="execute",
        command="pytest -q tests/test_reconciler.py -k retry",
        output="1 passed in 0.42 s\nworker gw2 finished in 0.42 s",
        reason="Running the single test again, hoping to catch the flake in the act.",
    ),
)

CI_TODOS = (
    _todos(
        0.18,
        "Board for the flake hunt.",
        (
            ("Measure the failure rate over 40 runs", "in_progress"),
            ("Decide whether the order plugin is involved", "pending"),
            ("Find the shared fixture", "pending"),
            ("Propose a quarantine and a fix", "pending"),
        ),
    ),
    _todos(
        0.55,
        "Board update after the fixture sweep.",
        (
            ("Measure the failure rate over 40 runs", "completed"),
            ("Decide whether the order plugin is involved", "completed"),
            ("Find the shared fixture", "in_progress"),
            ("Propose a quarantine and a fix", "pending"),
        ),
    ),
    _todos(
        0.80,
        "Board update before the retro write-up.",
        (
            ("Measure the failure rate over 40 runs", "completed"),
            ("Decide whether the order plugin is involved", "completed"),
            ("Find the shared fixture", "completed"),
            ("Propose a quarantine and a fix", "in_progress"),
        ),
    ),
)


def _case_flaky_ci() -> CaseSpec:
    return CaseSpec(
        index=4,
        slug="flaky-ci-test",
        domain="ci-flaky-test",
        description="A flaky-test investigation: a measured failure rate, a forty-run log whose "
        "failing assertion sits in the middle, a shared fixture as the root cause and a "
        "quarantine decision for the retro.",
        task="Decide whether the reconciler test is genuinely flaky or the runner is broken, and "
        "bring a defensible decision to the retrospective.",
        notes="Stresses numeric facts stated early, a root cause in the middle, and one assertion "
        "line that only exists inside a run log above both truncation ceilings.",
        message_target=128,
        contract="Whatever you propose, keep the suite green on the pull request workflow and "
        "attach the measured failure rate to the ticket; the retro is on Friday.",
        vocabulary=CI_VOCAB,
        facts=CI_FACTS,
        beats=CI_BEATS,
        todos=CI_TODOS,
    )


# ---------------------------------------------------------------------------
# Case 5 - a dependency upgrade with a long lock file
# ---------------------------------------------------------------------------

UPGRADE_VOCAB = Vocabulary(
    paths=(
        "pyproject.toml",
        "requirements.lock",
        "src/clients/http.py",
        "src/clients/retries.py",
        "src/config/endpoints.py",
        "tests/test_http_client.py",
        "scripts/smoke.py",
        "docs/adr/0004-http-client.md",
        "CHANGELOG.md",
    ),
    symbols=(
        "HttpClient",
        "build_client",
        "AsyncTransport",
        "proxy_argument",
        "TimeoutPolicy",
        "stream_response",
    ),
    commands=(
        "pip install -r requirements.lock --dry-run",
        "pip check",
        "pytest -q tests/test_http_client.py",
        "make smoke",
        "grep -rn proxies src",
    ),
    observations=(
        "The client passes a proxies dictionary, which the new major no longer accepts.",
        "Two adapters wrap the client, and only one of them sets a timeout.",
        "The lock file pins transitive dependencies that the project never imports.",
        "The smoke script is the only thing that exercises the streaming path.",
        "The changelog mentions the removal three releases before it landed.",
    ),
    questions=(
        "Do we upgrade the client before the framework, or the other way round?",
        "Is the streaming path covered by anything other than the smoke script?",
        "Can we bump two majors in one pull request, or does that break the review?",
        "Does the lock file still resolve on the oldest supported interpreter?",
    ),
    log_lines=(
        "resolving dependencies against the internal index",
        "hash verified for the pinned wheel",
        "deprecation: the proxies argument is ignored",
        "smoke script streamed 4 MiB without a timeout error",
        "no conflicting requirements found",
    ),
    code_lines=(
        "    client = httpx.Client(proxy=proxy_argument(), timeout=TimeoutPolicy.total)",
        "    with client.stream('GET', url) as response:",
        "        yield from response.iter_bytes()",
        "requires-python = '>=3.11'",
        "    transport = AsyncTransport(retries=2)",
    ),
    packages=(
        "httpx",
        "httpcore",
        "h11",
        "anyio",
        "sniffio",
        "certifi",
        "idna",
        "langchain",
        "langchain-core",
        "tenacity",
        "rich",
        "textual",
    ),
    notes=("http client", "transport", "proxy", "timeout", "wheel"),
)

UPGRADE_FACTS = (
    FactSpec(
        slug="httpx-pin",
        statement="The lock file pins one exact httpx version, and that pin is the target of the "
        "upgrade.",
        answer="the lock file pins httpx==0.28.1",
        aliases=("the target of the upgrade is httpx==0.28.1",),
        position="early",
        question="Which exact httpx version does the lock file pin?",
        expected="httpx==0.28.1",
        probe_aliases=("0.28.1",),
        trap="bump httpx to 1.0 as long as we are at it",
    ),
    FactSpec(
        slug="upgrade-order",
        probed=False,
        statement="The team fixed the order of the two upgrades, with a reason attached to it.",
        answer="upgrade httpx before langchain because the framework needs the new transport",
        aliases=("httpx first, then langchain", "the framework needs the new transport"),
        position="early",
        question="In which order did the team decide to run the two upgrades?",
        expected="upgrade httpx before langchain",
        probe_aliases=("httpx first", "httpx before langchain"),
    ),
    FactSpec(
        slug="breaking-change",
        statement="One keyword argument was removed by the new major, and the client still "
        "passes it.",
        answer="the proxies argument was removed in favour of proxy",
        aliases=("proxies was removed", "use proxy instead of proxies"),
        position="middle",
        question="Which breaking change does the new httpx major introduce?",
        expected="the proxies argument was removed in favour of proxy",
        probe_aliases=("proxies", "the proxies argument was removed"),
    ),
    FactSpec(
        slug="lock-pin-line",
        statement="The pinned line for httpx, with its hash, sits in the middle of the lock file "
        "excerpt.",
        answer="httpx==0.28.1 --hash=sha256:9f2c41ab7e0d5b3c8f6a1e4d70c9b2a5",
        aliases=("httpx==0.28.1 --hash=sha256",),
        position="middle",
        question="What is the pinned httpx line, with its hash, in the lock file?",
        expected="httpx==0.28.1 --hash=sha256:9f2c41ab7e0d5b3c8f6a1e4d70c9b2a5",
        probe_aliases=("httpx==0.28.1 --hash=sha256",),
    ),
    FactSpec(
        slug="python-floor",
        probed=False,
        statement="The project declares one minimum interpreter version, which bounds the "
        "upgrade.",
        answer="requires-python >=3.11",
        aliases=("Python 3.11 is the floor", "minimum interpreter is 3.11"),
        position="late",
        question="What is the minimum Python version the project declares?",
        expected="requires-python >=3.11",
        probe_aliases=("3.11", ">=3.11"),
    ),
    FactSpec(
        slug="one-major-rule",
        statement="One review rule bounds how much a single upgrade pull request may contain.",
        answer="never bump two majors in one pull request",
        aliases=("one major per pull request",),
        position="late",
        question="Which rule bounds a single upgrade pull request?",
        expected="never bump two majors in one pull request",
        probe_aliases=("one major per pull request", "two majors in one pull request"),
    ),
    FactSpec(
        slug="verify-command",
        probed=False,
        statement="One offline command is the gate before an upgrade pull request is opened.",
        answer="the gate before opening the pull request is make smoke",
        aliases=("make smoke is the offline gate for the upgrade",),
        position="late",
        question="Which command is the gate before opening the upgrade pull request?",
        expected="make smoke",
        probe_aliases=("the gate before opening the pull request is make smoke",),
    ),
)

UPGRADE_BEATS = (
    _turn(
        0.02,
        _user(
            "We are two majors behind on the HTTP client and one on the agent framework. Plan the "
            "upgrade, read whatever the lock file and the changelog force you to read, and do not "
            "open a pull request until the offline gate passes."
        ),
        _assistant(
            "I will read the lock file and the changelog first, then propose an order and the "
            "smallest set of code changes.",
        ),
    ),
    _turn(
        0.05,
        _user(
            "A first idea, so you know what was rejected: bump httpx to 1.0 as long as we are at "
            "it, and take the framework with it.",
            trap_for="httpx-pin",
            note="superseded once the lock file was read",
        ),
    ),
    _turn(
        0.09,
        _assistant(
            "Rejected, and here is the target instead: the lock file pins httpx==0.28.1, and "
            "that is the version we upgrade to, because it is the last one the framework adapter "
            "supports.",
            states_fact="httpx-pin",
        ),
    ),
    _turn(
        0.14,
        _assistant(
            "Order decided: upgrade httpx before langchain because the framework needs the new "
            "transport; the reverse order fails at import time.",
            states_fact="upgrade-order",
        ),
    ),
    _tool(
        0.26,
        "Reading the changelog of every release between the pin and the target.",
        OutputSpec(
            kind="changelog",
            tool="read_file",
            target="CHANGELOG.md",
            lines=CHANGELOG_LINES_UPGRADE,
            width=44,
            arguments={"path": "CHANGELOG.md"},
            embedded=(
                "Removed: the proxies argument was removed in favour of proxy; passing "
                "proxies now raises TypeError",
            ),
            embedded_at=(EMBEDDED_FACT_DEPTH,),
        ),
        states_fact="breaking-change",
        followup="The removal is documented three releases before it landed, which is why nobody "
        "saw it coming.",
    ),
    _tool(
        0.46,
        "Reading the lock file excerpt to confirm the pin and its hash.",
        OutputSpec(
            kind="lock",
            tool="read_file",
            target="requirements.lock",
            lines=LOCK_LINES_UPGRADE,
            width=34,
            arguments={"path": "requirements.lock"},
            embedded=(
                "httpx==0.28.1 --hash=sha256:9f2c41ab7e0d5b3c8f6a1e4d70c9b2a5",
            ),
            embedded_at=(EMBEDDED_FACT_DEPTH,),
        ),
        states_fact="lock-pin-line",
        followup="The hash matches the internal index, so the pin is reproducible offline.",
    ),
    _tool(
        0.62,
        "Checking the resolved dependency graph for conflicts.",
        OutputSpec(
            kind="run_log",
            tool="execute",
            target="pip check && pip install -r requirements.lock --dry-run",
            lines=PIP_CHECK_LINES_UPGRADE,
            width=60,
            arguments={"command": "pip check && pip install -r requirements.lock --dry-run"},
        ),
        followup="No conflict, but two transitive pins are unused and can be dropped later.",
    ),
    _turn(
        0.74,
        _assistant(
            "Only one call site passes the removed argument, in src/clients/http.py; the adapter "
            "in src/clients/retries.py is already on the new signature.",
        ),
    ),
    _turn(
        0.86,
        _user(
            "One constraint for the pull request, non-negotiable: the project declares "
            "requires-python >=3.11 and we are not lowering it for this upgrade.",
            states_fact="python-floor",
        ),
    ),
    _turn(
        0.90,
        _assistant(
            "Understood: the httpx bump ships alone, and the framework upgrade becomes a second, "
            "stacked pull request on top of this one.",
        ),
    ),
    _turn(
        0.93,
        _user(
            "And repeat the rule about majors so it lands in the description: never bump two "
            "majors in one pull request. Reviewers bounce them.",
            states_fact="one-major-rule",
        ),
    ),
    _turn(
        0.95,
        _assistant(
            "Last thing before I open it: the gate before opening the pull request is make smoke, "
            "which is the only offline check that exercises the streaming path.",
            states_fact="verify-command",
        ),
    ),
    _repeat(
        0.36,
        tool="execute",
        command="pip install -r requirements.lock --dry-run",
        output="would install httpx-0.28.1 httpcore-1.0.9\nno conflicting requirements found",
        reason="Resolving the lock file once more to be sure the index is not flaking.",
    ),
)

UPGRADE_TODOS = (
    _todos(
        0.20,
        "Board for the upgrade, one card per reviewable step.",
        (
            ("Read the changelog between the pin and the target", "in_progress"),
            ("Confirm the lock file pin and its hash", "pending"),
            ("Fix the removed argument at its single call site", "pending"),
            ("Run the offline gate", "pending"),
        ),
    ),
    _todos(
        0.54,
        "Board update after the lock file reading.",
        (
            ("Read the changelog between the pin and the target", "completed"),
            ("Confirm the lock file pin and its hash", "completed"),
            ("Fix the removed argument at its single call site", "in_progress"),
            ("Run the offline gate", "pending"),
        ),
    ),
    _todos(
        0.78,
        "Board update before the gate.",
        (
            ("Read the changelog between the pin and the target", "completed"),
            ("Confirm the lock file pin and its hash", "completed"),
            ("Fix the removed argument at its single call site", "completed"),
            ("Run the offline gate", "in_progress"),
        ),
    ),
)


def _case_dependency_upgrade() -> CaseSpec:
    return CaseSpec(
        index=5,
        slug="dependency-upgrade",
        domain="dependency-upgrade",
        description="A dependency upgrade session dominated by reading: a changelog that "
        "documents a removed argument and a lock file excerpt whose pinned line sits in the "
        "middle of more than two thousand lines.",
        task="Plan the HTTP client upgrade, read the lock file and the changelog, and prepare the "
        "smallest reviewable pull request.",
        notes="Stresses two facts that exist only inside large tool outputs - a changelog entry "
        "and a pinned hash line - plus a late constraint restated twice by the user.",
        message_target=72,
        contract="Keep the pull request reviewable: one major, one call site changed, and the "
        "offline gate green before you ask anyone to look at it.",
        vocabulary=UPGRADE_VOCAB,
        facts=UPGRADE_FACTS,
        beats=UPGRADE_BEATS,
        todos=UPGRADE_TODOS,
    )


# ---------------------------------------------------------------------------
# The dataset
# ---------------------------------------------------------------------------


def case_specs() -> tuple[CaseSpec, ...]:
    """The five cases, in the order the experiment runs them."""
    return (
        _case_api_service(),
        _case_frontend_refactor(),
        _case_pipeline_incident(),
        _case_flaky_ci(),
        _case_dependency_upgrade(),
    )


def validate_dataset(dataset: EvalDataset) -> None:
    """Dataset-level invariants: the ones no single case can express."""
    _require(
        len(dataset.cases) == CASE_COUNT,
        f"the dataset has {len(dataset.cases)} cases, the design needs {CASE_COUNT}",
    )
    domains = [case.metadata.get("domain") for case in dataset.cases]
    _require(
        len(set(domains)) == len(domains),
        f"two cases share a domain, so the dataset is not varied: {sorted(domains)}",
    )
    with_line_overflow = 0
    with_two_truncated = 0
    for case in dataset.cases:
        above_lines = 0
        truncated = 0
        for message in case.messages:
            if not message.is_tool_result():
                continue
            lines = message.text.count("\n") + 1
            size = len(message.text.encode("utf-8"))
            above_lines += int(lines > TOOL_LIMITS.max_lines)
            truncated += int(lines > TOOL_LIMITS.max_lines or size > TOOL_LIMITS.max_bytes)
        with_line_overflow += int(above_lines > 0)
        with_two_truncated += int(truncated >= MIN_OUTPUTS_TRUNCATED)
    _require(
        with_line_overflow >= MIN_CASES_WITH_LINE_OVERFLOW,
        f"only {with_line_overflow} cases hold a tool output above the "
        f"{TOOL_LIMITS.max_lines}-line ceiling, the design needs "
        f"{MIN_CASES_WITH_LINE_OVERFLOW}",
    )
    _require(
        with_two_truncated >= MIN_CASES_WITH_TWO_TRUNCATED_OUTPUTS,
        f"only {with_two_truncated} cases hold {MIN_OUTPUTS_TRUNCATED} tool outputs above a "
        f"truncation ceiling, the design needs "
        f"{MIN_CASES_WITH_TWO_TRUNCATED_OUTPUTS}",
    )
    sizes = [case.char_count for case in dataset.cases]
    _require(
        max(sizes) - min(sizes) >= MIN_SIZE_SPREAD_CHARS,
        f"the cases are all the same size ({sorted(sizes)} chars), so the experiment cannot "
        "show how the policies scale with history length",
    )


if __name__ == "__main__":
    raise SystemExit(main())
