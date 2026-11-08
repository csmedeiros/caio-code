"""Typed driver steps and the plain-text script parser.

A step is a frozen dataclass with a ``describe()`` line for logs and reports.
Scripts are plain text, one step per line; ``#`` starts a comment::

    send fix the bug
    assert-text within=#transcript Done
    assert-todo completed=2
    assert-footer cache
    snapshot after-send
    assert-widget #transcript
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields

from caio_code.presentation.tui.driver.errors import ScriptError

COMMENT_PREFIX = "#"
KEYWORD_SEPARATOR = "="
ALL_SCENARIOS = "all"
STEP_VERBS: tuple[str, ...] = (
    "type",
    "key",
    "wait",
    "send",
    "assert-text",
    "assert-todo",
    "assert-footer",
    "snapshot",
    "assert-widget",
)
SAFE_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


@dataclass(frozen=True, slots=True)
class Step:
    """Base of every driver step."""

    def describe(self) -> str:
        values = ", ".join(
            f"{f.name}={getattr(self, f.name)!r}"
            for f in fields(self)
            if getattr(self, f.name) is not None
        )
        return f"{type(self).__name__}({values})"


@dataclass(frozen=True, slots=True)
class Type(Step):
    """Insert text into the focused composer (no Enter)."""

    text: str


@dataclass(frozen=True, slots=True)
class Key(Step):
    """Press one key by Textual name: ``enter``, ``escape``, ``ctrl+t``, ..."""

    name: str


@dataclass(frozen=True, slots=True)
class Wait(Step):
    """Let the event loop run for ``ms`` milliseconds (pilot pause)."""

    ms: int


@dataclass(frozen=True, slots=True)
class Send(Step):
    """Type text and press Enter."""

    text: str


@dataclass(frozen=True, slots=True)
class AssertText(Step):
    """Expect ``expected`` in the screen text, or in one widget when scoped."""

    expected: str
    within: str | None = None


@dataclass(frozen=True, slots=True)
class AssertTodo(Step):
    """Expect sidebar counts; ``None`` fields are not checked."""

    count: int | None = None
    in_progress: int | None = None
    completed: int | None = None


@dataclass(frozen=True, slots=True)
class AssertFooter(Step):
    """Expect every string in ``contains`` inside the usage footer text."""

    contains: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Snapshot(Step):
    """Write ``NNN-name.svg`` and ``NNN-name.txt`` into the reports dir."""

    name: str


@dataclass(frozen=True, slots=True)
class AssertWidget(Step):
    """Expect a CSS selector to match (or not to match) exactly one widget."""

    query: str
    exists: bool = True


DriverStep = (
    Type
    | Key
    | Wait
    | Send
    | AssertText
    | AssertTodo
    | AssertFooter
    | Snapshot
    | AssertWidget
)
Scenario = Sequence[DriverStep]


def _require(value: str, verb: str, line_number: int | None) -> str:
    if not value:
        where = f" (line {line_number})" if line_number is not None else ""
        msg = f"{verb} needs an argument{where}"
        raise ScriptError(msg)
    return value


def _require_int(raw: str, verb: str, line_number: int | None) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        where = f" (line {line_number})" if line_number is not None else ""
        msg = f"{verb} needs an integer argument, got {raw!r}{where}"
        raise ScriptError(msg) from exc


def _keywords(tokens: list[str], allowed: Iterable[str], verb: str, line_number: int | None) -> tuple[dict[str, str], list[str]]:
    """Split leading ``key=value`` tokens from positional ones."""
    keywords: dict[str, str] = {}
    positional: list[str] = []
    allowed_set = set(allowed)
    for token in tokens:
        key, sep, value = token.partition(KEYWORD_SEPARATOR)
        if sep and key in allowed_set:
            keywords[key] = value
        else:
            positional.append(token)
    return keywords, positional


def _check_snapshot_name(name: str, line_number: int | None) -> str:
    if not name or not set(name) <= SAFE_NAME_CHARS:
        where = f" (line {line_number})" if line_number is not None else ""
        msg = f"snapshot name must use letters, digits, '-' or '_', got {name!r}{where}"
        raise ScriptError(msg)
    return name


def parse_line(line: str, *, line_number: int | None = None) -> DriverStep:
    """Parse one script line into a typed step."""
    stripped = line.strip()
    if not stripped:
        msg = "empty step line"
        raise ScriptError(msg)
    if stripped.startswith(COMMENT_PREFIX):
        msg = "comment line is not a step; parse_script skips comments"
        raise ScriptError(msg)
    verb, _, rest = stripped.partition(" ")
    rest = rest.strip()
    match verb:
        case "type":
            return Type(_require(rest, verb, line_number))
        case "key":
            return Key(_require(rest, verb, line_number))
        case "wait":
            return Wait(_require_int(_require(rest, verb, line_number), verb, line_number))
        case "send":
            return Send(_require(rest, verb, line_number))
        case "assert-text":
            tokens = shlex.split(_require(rest, verb, line_number))
            keywords, positional = _keywords(tokens, ("within",), verb, line_number)
            if not positional:
                msg = f"assert-text needs the expected text (line {line_number})"
                raise ScriptError(msg)
            return AssertText(expected=" ".join(positional), within=keywords.get("within"))
        case "assert-todo":
            tokens = shlex.split(_require(rest, verb, line_number))
            keywords, positional = _keywords(
                tokens, ("count", "in_progress", "completed"), verb, line_number
            )
            if positional:
                msg = f"assert-todo takes only count=, in_progress=, completed= (line {line_number})"
                raise ScriptError(msg)
            return AssertTodo(
                count=_optional_int(keywords.get("count"), verb, line_number),
                in_progress=_optional_int(keywords.get("in_progress"), verb, line_number),
                completed=_optional_int(keywords.get("completed"), verb, line_number),
            )
        case "assert-footer":
            tokens = shlex.split(_require(rest, verb, line_number))
            return AssertFooter(contains=tuple(tokens))
        case "snapshot":
            return Snapshot(_check_snapshot_name(_require(rest, verb, line_number), line_number))
        case "assert-widget":
            tokens = shlex.split(_require(rest, verb, line_number))
            keywords, positional = _keywords(tokens, ("exists",), verb, line_number)
            if len(positional) != 1:
                msg = f"assert-widget needs exactly one selector (line {line_number})"
                raise ScriptError(msg)
            exists_raw = keywords.get("exists", "true").lower()
            if exists_raw not in {"true", "false"}:
                msg = f"assert-widget exists= takes true or false, got {exists_raw!r} (line {line_number})"
                raise ScriptError(msg)
            return AssertWidget(query=positional[0], exists=exists_raw == "true")
        case _:
            msg = (
                f"unknown step verb {verb!r}"
                + (f" (line {line_number})" if line_number is not None else "")
                + f"; known verbs: {', '.join(STEP_VERBS)}"
            )
            raise ScriptError(msg)


def _optional_int(raw: str | None, verb: str, line_number: int | None) -> int | None:
    if raw is None:
        return None
    return _require_int(raw, verb, line_number)


def parse_script(text: str) -> list[DriverStep]:
    """Parse a whole script file; blank lines and ``#`` comments are skipped."""
    steps: list[DriverStep] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(COMMENT_PREFIX):
            continue
        steps.append(parse_line(stripped, line_number=number))
    if not steps:
        msg = "script has no steps"
        raise ScriptError(msg)
    return steps
