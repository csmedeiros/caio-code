"""The replay tool server: the probe round's only tool surface.

During probing the agent may go back to the session's tools -- most importantly
to read a spilled output file -- but nothing is executed: every call is matched
against the case's own recorded interactions. A call that matches is served the
recorded result; a call that matches a spill path is served the full spilled
text; anything else gets a visible typed miss
(:class:`~caio_code.domain.errors.ToolUnavailableInReplay`) that the model sees
and the report counts. Deterministic by construction: same case, same calls,
same results, no clock and no filesystem.

The server also derives the function schemas offered to the model, so the agent
only ever sees tools that actually exist in the replay surface.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from caio_code.domain.conversation.messages import Message, Role, ToolCall
from caio_code.domain.errors import ToolUnavailableInReplay
from caio_code.domain.evaluation.cases import HistoryCase
from caio_code.domain.ports.gateway import ToolSchema

READ_FILE_TOOL = "read_file"
READ_FILE_DESCRIPTION = (
    "Read a file from the session workspace. Tool outputs that were too large "
    "for the context were saved here; their pointers name the exact path."
)
SPILL_PATH_ARGUMENT = "path"
ToolCallKind = Literal["recorded", "spill", "miss"]

MISS_TEMPLATE = (
    "ToolUnavailableInReplay: no recorded {tool} interaction with these arguments "
    "exists in this session replay (case {case_id}). Answer from the conversation "
    "content you have."
)


def canonical_arguments(arguments: str) -> str:
    """Normalize tool-call arguments so formatting drift cannot cause a miss.

    JSON arguments are re-serialized with sorted keys; anything unparseable is
    matched on its stripped raw form.
    """
    stripped = arguments.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    return json.dumps(parsed, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class ToolCallOutcome:
    """What one served call produced."""

    kind: ToolCallKind
    tool_name: str
    arguments: str
    text: str
    bytes_served: int
    error: str | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "bytes_served": self.bytes_served,
            "error": self.error,
        }


@dataclass(slots=True)
class ReplayToolStats:
    """Every call the server saw, split by outcome. Misses are first-class."""

    calls: int = 0
    recorded_hits: int = 0
    spill_reads: int = 0
    misses: int = 0
    bytes_served: int = 0
    outcomes: list[ToolCallOutcome] = field(default_factory=list)

    def record(self, outcome: ToolCallOutcome) -> None:
        self.calls += 1
        self.bytes_served += outcome.bytes_served
        if outcome.kind == "recorded":
            self.recorded_hits += 1
        elif outcome.kind == "spill":
            self.spill_reads += 1
        else:
            self.misses += 1
        self.outcomes.append(outcome)

    def as_record(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "recorded_hits": self.recorded_hits,
            "spill_reads": self.spill_reads,
            "misses": self.misses,
            "bytes_served": self.bytes_served,
            "outcomes": [outcome.as_record() for outcome in self.outcomes],
        }


def _schema_for_argument(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    return {"type": "string"}


def _infer_properties(arguments: Sequence[str]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for raw in arguments:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        for key, value in parsed.items():
            properties.setdefault(str(key), _schema_for_argument(value))
    return properties


class ReplayToolServer:
    """Serves probe-round tool calls from the case's recorded interactions."""

    def __init__(self, case: HistoryCase) -> None:
        self._case_id = case.id
        self._recorded: dict[tuple[str, str], list[str]] = {}
        self._argument_samples: dict[str, list[str]] = {}
        self._spill = {spill.path: spill.text for spill in case.spill_files}
        self._tool_names: list[str] = []
        self.stats = ReplayToolStats()
        self._index(case.messages)

    def _index(self, messages: Sequence[Message]) -> None:
        results_by_call_id: dict[str, str] = {}
        for message in messages:
            if message.role is Role.TOOL and message.tool_call_id:
                results_by_call_id[message.tool_call_id] = message.text
        for message in messages:
            for call in message.tool_calls:
                if call.name not in self._tool_names:
                    self._tool_names.append(call.name)
                self._argument_samples.setdefault(call.name, []).append(call.arguments)
                result = results_by_call_id.get(call.id)
                if result is None:
                    continue
                key = (call.name, canonical_arguments(call.arguments))
                self._recorded.setdefault(key, []).append(result)

    @property
    def tool_schemas(self) -> tuple[ToolSchema, ...]:
        """The function surface offered to the model during the probe round."""
        schemas = [
            ToolSchema(
                name=name,
                description=(
                    f"Replay of the session's {name} tool: a call whose arguments "
                    "match a recorded interaction is served its recorded result."
                ),
                parameters={
                    "type": "object",
                    "properties": _infer_properties(self._argument_samples.get(name, ())),
                    "additionalProperties": True,
                },
            )
            for name in self._tool_names
        ]
        if self._spill:
            schemas.append(
                ToolSchema(
                    name=READ_FILE_TOOL,
                    description=READ_FILE_DESCRIPTION,
                    parameters={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "additionalProperties": False,
                    },
                )
            )
        return tuple(schemas)

    @property
    def has_surface(self) -> bool:
        return bool(self._tool_names or self._spill)

    def serve(self, call: ToolCall) -> ToolCallOutcome:
        """Serve one call: spill read, recorded hit, or visible typed miss."""
        outcome = self._serve(call)
        self.stats.record(outcome)
        return outcome

    def _serve(self, call: ToolCall) -> ToolCallOutcome:
        spill_text = self._spill_read(call)
        if spill_text is not None:
            return ToolCallOutcome(
                kind="spill",
                tool_name=call.name,
                arguments=call.arguments,
                text=spill_text,
                bytes_served=len(spill_text.encode("utf-8")),
            )
        key = (call.name, canonical_arguments(call.arguments))
        recorded = self._recorded.get(key)
        if recorded:
            # Repeats of the same call are served the same recorded result: the
            # replay is about content recovery, not about call ordering.
            text = recorded[0]
            return ToolCallOutcome(
                kind="recorded",
                tool_name=call.name,
                arguments=call.arguments,
                text=text,
                bytes_served=len(text.encode("utf-8")),
            )
        error = ToolUnavailableInReplay(
            MISS_TEMPLATE.format(tool=call.name, case_id=self._case_id)
        )
        return ToolCallOutcome(
            kind="miss",
            tool_name=call.name,
            arguments=call.arguments,
            text=str(error),
            bytes_served=0,
            error=type(error).__name__,
        )

    def _spill_read(self, call: ToolCall) -> str | None:
        """Full text of a spilled output, when the call asks for one."""
        if not self._spill:
            return None
        try:
            parsed = json.loads(call.arguments)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        requested = parsed.get(SPILL_PATH_ARGUMENT, "")
        if not isinstance(requested, str):
            return None
        return self._spill.get(requested.strip())


__all__ = [
    "MISS_TEMPLATE",
    "READ_FILE_DESCRIPTION",
    "READ_FILE_TOOL",
    "ReplayToolServer",
    "ReplayToolStats",
    "ToolCallOutcome",
    "canonical_arguments",
]
