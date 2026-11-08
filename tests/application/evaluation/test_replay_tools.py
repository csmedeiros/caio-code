"""Offline tests for the replay tool server: recorded hits, spill reads, misses."""

from __future__ import annotations

from caio_code.application.evaluation.replay_tools import (
    READ_FILE_TOOL,
    ReplayToolServer,
    canonical_arguments,
)
from caio_code.domain.conversation.messages import Message, Role, ToolCall
from caio_code.domain.evaluation.cases import CriticalFact, HistoryCase, Probe, SpillFile

SPILL_TEXT = "the port is 9142\n" + "filler line\n" * 40
SPILL_PATH = "spill/c1/c1-m2.txt"


def _case(*, with_spill: bool = False) -> HistoryCase:
    messages = [
        Message(id="c1-task", role=Role.USER, text="fix the bug", pinned=True),
        Message(
            id="c1-m1",
            role=Role.ASSISTANT,
            text="running the tests",
            tool_calls=(
                ToolCall(id="c1-tc1", name="run_tests", arguments='{"suite": "pay"}'),
            ),
        ),
        Message(
            id="c1-m2",
            role=Role.TOOL,
            text="3 passed, 1 failed",
            tool_call_id="c1-tc1",
            name="run_tests",
        ),
    ]
    spill_files: tuple[SpillFile, ...] = ()
    if with_spill:
        spill_files = (
            SpillFile(
                path=SPILL_PATH,
                text=SPILL_TEXT,
                source_message_id="c1-m2",
                tool_name="run_tests",
                byte_count=len(SPILL_TEXT.encode("utf-8")),
                line_count=SPILL_TEXT.count("\n") + 1,
            ),
        )
    return HistoryCase(
        id="c1",
        description="synthetic",
        messages=tuple(messages),
        facts=(CriticalFact(id="c1-f1", statement="the port", answer="9142"),),
        probes=(Probe(id="c1-p1", fact_id="c1-f1", question="port?", expected="9142"),),
        variant="spill" if with_spill else "full",
        spill_files=spill_files,
    )


def _call(name: str, arguments: str, call_id: str = "tc-x") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


def test_recorded_interaction_is_served_by_canonical_arguments() -> None:
    server = ReplayToolServer(_case())

    outcome = server.serve(_call("run_tests", '{ "suite": "pay" }'))

    assert outcome.kind == "recorded"
    assert outcome.text == "3 passed, 1 failed"
    assert outcome.bytes_served == len(b"3 passed, 1 failed")
    assert server.stats.recorded_hits == 1
    assert server.stats.calls == 1


def test_repeated_identical_call_is_served_the_same_recorded_result() -> None:
    server = ReplayToolServer(_case())

    first = server.serve(_call("run_tests", '{"suite": "pay"}', call_id="a"))
    second = server.serve(_call("run_tests", '{"suite": "pay"}', call_id="b"))

    assert first.text == second.text == "3 passed, 1 failed"
    assert server.stats.recorded_hits == 2


def test_unmatched_call_is_a_visible_typed_miss() -> None:
    server = ReplayToolServer(_case())

    outcome = server.serve(_call("grep", '{"pattern": "nope"}'))

    assert outcome.kind == "miss"
    assert outcome.error == "ToolUnavailableInReplay"
    assert "ToolUnavailableInReplay" in outcome.text
    assert "c1" in outcome.text
    assert server.stats.misses == 1
    assert outcome.bytes_served == 0


def test_spill_read_serves_the_full_spilled_text() -> None:
    server = ReplayToolServer(_case(with_spill=True))

    outcome = server.serve(_call(READ_FILE_TOOL, f'{{"path": "{SPILL_PATH}"}}'))

    assert outcome.kind == "spill"
    assert outcome.text == SPILL_TEXT
    assert server.stats.spill_reads == 1
    assert server.stats.bytes_served == len(SPILL_TEXT.encode("utf-8"))


def test_unknown_spill_path_is_a_miss() -> None:
    server = ReplayToolServer(_case(with_spill=True))

    outcome = server.serve(_call(READ_FILE_TOOL, '{"path": "spill/c1/other.txt"}'))

    assert outcome.kind == "miss"
    assert server.stats.spill_reads == 0


def test_tool_schemas_cover_recorded_tools_and_read_file_only_with_spill() -> None:
    plain = ReplayToolServer(_case())
    assert [tool.name for tool in plain.tool_schemas] == ["run_tests"]

    spilled = ReplayToolServer(_case(with_spill=True))
    names = [tool.name for tool in spilled.tool_schemas]
    assert names == ["run_tests", READ_FILE_TOOL]
    read_file = spilled.tool_schemas[-1]
    assert read_file.parameters["properties"]["path"]["type"] == "string"


def test_schema_properties_are_inferred_from_recorded_arguments() -> None:
    server = ReplayToolServer(_case())
    (schema,) = server.tool_schemas
    assert schema.parameters["properties"] == {"suite": {"type": "string"}}


def test_canonical_arguments_sorts_json_keys_and_falls_back_to_raw() -> None:
    assert canonical_arguments('{"b": 1, "a": 2}') == '{"a": 2, "b": 1}'
    assert canonical_arguments("  not json ") == "not json"


def test_assistant_call_without_result_is_not_indexed() -> None:
    server = ReplayToolServer(_case())

    outcome = server.serve(_call("run_tests", '{"suite": "other"}'))

    assert outcome.kind == "miss"
