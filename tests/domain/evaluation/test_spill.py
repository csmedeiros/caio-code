"""Offline tests for the spill-to-file case derivation (the truncation factor)."""

from __future__ import annotations

import pytest

from caio_code.domain.conversation.messages import Message, Role, ToolCall
from caio_code.domain.errors import DatasetError
from caio_code.domain.evaluation.cases import (
    CriticalFact,
    HistoryCase,
    Probe,
    SpillFile,
)
from caio_code.domain.evaluation.spill import (
    SPILL_EDIT_MARKER,
    derive_spill_case,
    spill_path,
    variant_case,
)

MAX_BYTES = 200
BIG_OUTPUT = "line of test output\n" * 60  # 1200 bytes, above the ceiling
SMALL_OUTPUT = "ok\n"


def _case() -> HistoryCase:
    messages = (
        Message(id="c1-task", role=Role.USER, text="fix the bug", pinned=True),
        Message(
            id="c1-m1",
            role=Role.ASSISTANT,
            text="running the tests",
            tool_calls=(ToolCall(id="c1-tc1", name="run_tests", arguments="{}"),),
        ),
        Message(
            id="c1-m2",
            role=Role.TOOL,
            text=BIG_OUTPUT,
            tool_call_id="c1-tc1",
            name="run_tests",
        ),
        Message(
            id="c1-m3",
            role=Role.ASSISTANT,
            text="checking lint",
            tool_calls=(ToolCall(id="c1-tc2", name="shell", arguments="{}"),),
        ),
        Message(
            id="c1-m4",
            role=Role.TOOL,
            text=SMALL_OUTPUT,
            tool_call_id="c1-tc2",
            name="shell",
        ),
        Message(id="c1-m5", role=Role.ASSISTANT, text="the port is 9142"),
    )
    return HistoryCase(
        id="c1",
        description="synthetic",
        messages=messages,
        facts=(
            CriticalFact(id="c1-f1", statement="the port", answer="9142", position="late"),
        ),
        probes=(
            Probe(id="c1-p1", fact_id="c1-f1", question="What is the port?", expected="9142"),
        ),
        task="fix the bug",
    )


def test_big_tool_output_moves_to_a_spill_file_and_leaves_a_pointer() -> None:
    derived = derive_spill_case(_case(), max_bytes=MAX_BYTES)

    assert derived.variant == "spill"
    assert len(derived.spill_files) == 1
    spill = derived.spill_files[0]
    assert spill.path == spill_path("c1", "c1-m2")
    assert spill.text == BIG_OUTPUT
    assert spill.source_message_id == "c1-m2"
    assert spill.tool_name == "run_tests"
    assert spill.byte_count == len(BIG_OUTPUT.encode("utf-8"))
    assert spill.line_count == BIG_OUTPUT.count("\n") + 1

    pointer = derived.messages[2]
    assert pointer.text != BIG_OUTPUT
    assert spill.path in pointer.text
    assert str(spill.byte_count) in pointer.text
    assert pointer.tool_call_id == "c1-tc1"  # pairing survives for structure repair


def test_untouched_messages_survive_by_identity() -> None:
    original = _case()
    derived = derive_spill_case(original, max_bytes=MAX_BYTES)

    for index, message in enumerate(original.messages):
        if index == 2:
            continue
        assert derived.messages[index] is message


def test_derivation_is_pure_and_deterministic() -> None:
    original = _case()
    first = derive_spill_case(original, max_bytes=MAX_BYTES)
    second = derive_spill_case(original, max_bytes=MAX_BYTES)

    assert first == second
    assert first.metadata["spill_max_bytes"] == MAX_BYTES
    assert original.variant == "full"
    assert original.spill_files == ()


def test_only_full_cases_derive() -> None:
    derived = derive_spill_case(_case(), max_bytes=MAX_BYTES)
    with pytest.raises(DatasetError):
        derive_spill_case(derived, max_bytes=MAX_BYTES)


def test_max_bytes_must_be_positive() -> None:
    with pytest.raises(DatasetError):
        derive_spill_case(_case(), max_bytes=0)


def test_variant_case_passes_full_through_and_dispatches_spill() -> None:
    original = _case()
    assert variant_case(original, "full", max_bytes=MAX_BYTES) is original
    assert variant_case(original, "spill", max_bytes=MAX_BYTES).variant == "spill"
    with pytest.raises(DatasetError):
        variant_case(original, "truncated", max_bytes=MAX_BYTES)


def test_full_variant_refuses_spill_files() -> None:
    with pytest.raises(DatasetError):
        HistoryCase(
            id="c2",
            description="synthetic",
            messages=(Message(id="c2-m1", role=Role.USER, text="hi"),),
            facts=(CriticalFact(id="c2-f1", statement="s", answer="a"),),
            probes=(Probe(id="c2-p1", fact_id="c2-f1", question="q?", expected="a"),),
            variant="full",
            spill_files=(
                SpillFile(
                    path="spill/c2/c2-m1.txt",
                    text="x",
                    source_message_id="c2-m1",
                    tool_name="run_tests",
                    byte_count=1,
                    line_count=1,
                ),
            ),
        )


def test_spill_pointer_is_marked_as_a_visible_edit() -> None:
    derived = derive_spill_case(_case(), max_bytes=MAX_BYTES)
    pointer = derived.messages[2]
    # o marcador vive na trilha de auditoria da mensagem, não no texto
    assert SPILL_EDIT_MARKER in pointer.metadata.get("edits", ())
    assert pointer.text != BIG_OUTPUT
