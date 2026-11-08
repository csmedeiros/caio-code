"""Codec do dataset de avaliação: round trip, schema e erros que nomeiam o campo."""

from __future__ import annotations

import json
from typing import Any

import pytest

from caio_code.domain.conversation.messages import Message, Role, ToolCall
from caio_code.domain.errors import DatasetError
from caio_code.domain.evaluation.cases import CriticalFact, EvalDataset, HistoryCase, Probe
from caio_code.infrastructure.datasets.codec import (
    CASE_FIELDS,
    DATASET_FIELDS,
    FACT_FIELDS,
    MESSAGE_FIELDS,
    PROBE_FIELDS,
    TOOL_CALL_FIELDS,
    case_from_dict,
    case_to_dict,
    dataset_from_dict,
    dataset_to_dict,
    fact_from_dict,
    fact_to_dict,
    message_from_dict,
    message_to_dict,
    probe_from_dict,
    probe_to_dict,
    tool_call_from_dict,
    tool_call_to_dict,
)


def jsonable(value: Any) -> Any:
    """A mesma conversão que o codec aplica: tuplas viram listas JSON."""
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    return value


def sample_case() -> HistoryCase:
    """Um caso pequeno que exercita tudo: pinned, tool call, metadata, três posições."""
    return HistoryCase(
        id="case-99-codec",
        description="caso de teste do codec",
        task="Encontre o bug e corrija.",
        source="synthetic",
        metadata={"seed": 20261031, "tags": ("early", "late"), "nested": {"a": [1, 2]}},
        messages=(
            Message(
                id="case-99-codec-m000",
                role=Role.USER,
                text="Encontre o bug e corrija.",
                pinned=True,
                metadata={"role_in_case": "task"},
            ),
            Message(
                id="case-99-codec-m001",
                role=Role.ASSISTANT,
                text="",
                tool_calls=(
                    ToolCall(id="case-99-codec-tc001", name="read_file", arguments='{"path":"a"}'),
                ),
                metadata={"filler": "small_tool_run"},
            ),
            Message(
                id="case-99-codec-m002",
                role=Role.TOOL,
                text="retry limit 5 with a 250 ms backoff",
                tool_call_id="case-99-codec-tc001",
                name="read_file",
                metadata={"edits": ("tool_output_truncated",), "tool_output_lines": 1},
            ),
            Message(
                id="case-99-codec-m003",
                role=Role.USER,
                text="never touch migrations/",
                pinned=True,
                metadata={"role_in_case": "contract"},
            ),
        ),
        facts=(
            CriticalFact(
                id="case-99-codec-f00",
                statement="O limite de tentativas é 5 com backoff de 250 ms.",
                answer="retry limit 5 with a 250 ms backoff",
                aliases=("MAX_RETRIES = 5",),
                position="middle",
                message_index=2,
            ),
            CriticalFact(
                id="case-99-codec-f01",
                statement="Nada em migrations/ pode ser editado.",
                answer="never touch migrations/",
                aliases=("migrations/ is off limits",),
                position="late",
                message_index=3,
            ),
        ),
        probes=(
            Probe(
                id="case-99-codec-p00",
                fact_id="case-99-codec-f00",
                question="What retry limit did the team settle on?",
                expected="5",
                aliases=("five",),
            ),
        ),
    )


def test_case_round_trip_preserves_every_field() -> None:
    original = sample_case()
    restored = case_from_dict(case_to_dict(original))

    assert restored.id == original.id
    assert restored.description == original.description
    assert restored.task == original.task
    assert restored.source == original.source
    # tuples inside metadata are documented to come back as JSON lists
    assert restored.metadata == jsonable(original.metadata)
    assert restored.facts == original.facts
    assert restored.probes == original.probes
    assert len(restored.messages) == len(original.messages)
    for before, after in zip(original.messages, restored.messages, strict=True):
        assert after.id == before.id
        assert after.role is before.role
        assert after.text == before.text
        assert after.tool_calls == before.tool_calls
        assert after.tool_call_id == before.tool_call_id
        assert after.name == before.name
        assert after.pinned is before.pinned
        assert after.metadata == jsonable(before.metadata)
        assert after.tokens is None


def test_round_trip_survives_json_text() -> None:
    original = sample_case()
    text = json.dumps(case_to_dict(original), sort_keys=True)
    restored = case_from_dict(json.loads(text))
    assert case_to_dict(restored) == case_to_dict(original)


def test_case_keys_are_the_documented_schema() -> None:
    payload = case_to_dict(sample_case())
    assert set(payload) == set(CASE_FIELDS)
    assert set(payload["messages"][0]) == set(MESSAGE_FIELDS)
    assert set(payload["facts"][0]) == set(FACT_FIELDS)
    assert set(payload["probes"][0]) == set(PROBE_FIELDS)
    assert set(payload["messages"][1]["tool_calls"][0]) == set(TOOL_CALL_FIELDS)


def test_tuples_come_back_as_tuples() -> None:
    restored = case_from_dict(case_to_dict(sample_case()))
    assert isinstance(restored.messages, tuple)
    assert isinstance(restored.facts, tuple)
    assert isinstance(restored.probes, tuple)
    assert isinstance(restored.facts[0].aliases, tuple)
    assert isinstance(restored.probes[0].aliases, tuple)
    assert isinstance(restored.messages[1].tool_calls, tuple)


def test_piecewise_codecs_round_trip() -> None:
    case = sample_case()
    assert message_from_dict(message_to_dict(case.messages[1]), where="m") == case.messages[1]
    assert fact_from_dict(fact_to_dict(case.facts[0]), where="f") == case.facts[0]
    assert probe_from_dict(probe_to_dict(case.probes[0]), where="p") == case.probes[0]
    call = case.messages[1].tool_calls[0]
    assert tool_call_from_dict(tool_call_to_dict(call), where="tc") == call


def test_dataset_manifest_round_trip() -> None:
    case = sample_case()
    dataset = EvalDataset(name="long_histories", cases=(case,), seed=20261031, generator="g@v1")
    manifest = dataset_to_dict(dataset)
    assert manifest == {
        "name": "long_histories",
        "seed": 20261031,
        "generator": "g@v1",
        "cases": ["case-99-codec"],
    }
    assert set(manifest) == set(DATASET_FIELDS)
    restored = dataset_from_dict(manifest, (case,))
    assert restored.name == dataset.name
    assert restored.seed == dataset.seed
    assert restored.generator == dataset.generator
    assert restored.cases == dataset.cases


def test_manifest_order_wins_over_file_order() -> None:
    case = sample_case()
    other = HistoryCase(
        id="case-98-other",
        description="segundo caso",
        task="t",
        messages=case.messages,
        facts=case.facts,
        probes=case.probes,
    )
    manifest = {"name": "n", "seed": 1, "generator": "g", "cases": ["case-98-other", "case-99-codec"]}
    restored = dataset_from_dict(manifest, (case, other))
    assert [item.id for item in restored.cases] == ["case-98-other", "case-99-codec"]


def test_partial_load_accepts_a_manifest_with_more_cases() -> None:
    case = sample_case()
    manifest = {
        "name": "n",
        "seed": 1,
        "generator": "g",
        "cases": ["case-99-codec", "case-98-missing"],
    }
    restored = dataset_from_dict(manifest, (case,), require_all_listed=False)
    assert [item.id for item in restored.cases] == ["case-99-codec"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 7),
        ("description", None),
        ("task", ["not", "a", "string"]),
        ("source", 1.5),
        ("metadata", "not-an-object"),
        ("messages", "not-a-list"),
        ("facts", {"id": "f"}),
        ("probes", 3),
    ],
)
def test_malformed_case_field_raises_naming_it(field: str, value: Any) -> None:
    payload = case_to_dict(sample_case())
    payload[field] = value
    with pytest.raises(DatasetError) as excinfo:
        case_from_dict(payload, source="case-99.json")
    assert field in str(excinfo.value)
    assert "case-99.json" in str(excinfo.value)


@pytest.mark.parametrize("field", sorted(CASE_FIELDS))
def test_missing_case_field_raises_naming_it(field: str) -> None:
    payload = case_to_dict(sample_case())
    del payload[field]
    with pytest.raises(DatasetError) as excinfo:
        case_from_dict(payload)
    assert f"missing field {field!r}" in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", "bot"),
        ("pinned", "yes"),
        ("tool_calls", "read_file"),
        ("tool_call_id", 12),
        ("name", 12),
        ("metadata", ["not", "an", "object"]),
        ("text", None),
        ("id", None),
    ],
)
def test_malformed_message_field_raises_naming_it(field: str, value: Any) -> None:
    payload = case_to_dict(sample_case())
    payload["messages"][2][field] = value
    with pytest.raises(DatasetError) as excinfo:
        case_from_dict(payload, source="case-99.json")
    assert field in str(excinfo.value)
    assert "messages[2]" in str(excinfo.value)


def test_malformed_tool_call_raises_naming_the_index() -> None:
    payload = case_to_dict(sample_case())
    payload["messages"][1]["tool_calls"][0]["arguments"] = {"path": "a"}
    with pytest.raises(DatasetError) as excinfo:
        case_from_dict(payload)
    assert "tool_calls[0]" in str(excinfo.value)
    assert "arguments" in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("position", "beginning"),
        ("message_index", "2"),
        ("message_index", -1),
        ("aliases", "MAX_RETRIES = 5"),
        ("aliases", [5]),
        ("answer", 5),
        ("statement", None),
    ],
)
def test_malformed_fact_field_raises_naming_it(field: str, value: Any) -> None:
    payload = case_to_dict(sample_case())
    payload["facts"][0][field] = value
    with pytest.raises(DatasetError) as excinfo:
        case_from_dict(payload)
    assert "facts[0]" in str(excinfo.value)
    assert field in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fact_id", 3),
        ("question", None),
        ("expected", ["5"]),
        ("aliases", "five"),
    ],
)
def test_malformed_probe_field_raises_naming_it(field: str, value: Any) -> None:
    payload = case_to_dict(sample_case())
    payload["probes"][0][field] = value
    with pytest.raises(DatasetError) as excinfo:
        case_from_dict(payload)
    assert "probes[0]" in str(excinfo.value)
    assert field in str(excinfo.value)


def test_probe_pointing_at_an_unknown_fact_is_rejected() -> None:
    payload = case_to_dict(sample_case())
    payload["probes"][0]["fact_id"] = "case-99-codec-f99"
    with pytest.raises(DatasetError) as excinfo:
        case_from_dict(payload)
    assert "case-99-codec-f99" in str(excinfo.value)


def test_non_object_payload_names_the_type() -> None:
    with pytest.raises(DatasetError) as excinfo:
        case_from_dict(["not", "a", "case"])
    assert "list" in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", 7),
        ("seed", "20261031"),
        ("generator", None),
        ("cases", "case-99-codec"),
        ("cases", [7]),
    ],
)
def test_malformed_manifest_field_raises_naming_it(field: str, value: Any) -> None:
    manifest = dataset_to_dict(
        EvalDataset(name="n", cases=(sample_case(),), seed=1, generator="g")
    )
    manifest[field] = value
    with pytest.raises(DatasetError) as excinfo:
        dataset_from_dict(manifest, (sample_case(),))
    assert field in str(excinfo.value)


def test_manifest_listing_an_absent_case_is_rejected() -> None:
    manifest = {"name": "n", "seed": 1, "generator": "g", "cases": ["case-98-missing"]}
    with pytest.raises(DatasetError) as excinfo:
        dataset_from_dict(manifest, (sample_case(),))
    assert "case-98-missing" in str(excinfo.value)


def test_case_file_absent_from_the_manifest_is_rejected() -> None:
    manifest = {"name": "n", "seed": 1, "generator": "g", "cases": []}
    with pytest.raises(DatasetError) as excinfo:
        dataset_from_dict(manifest, (sample_case(),))
    assert "case-99-codec" in str(excinfo.value)
