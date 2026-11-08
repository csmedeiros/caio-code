"""JSON codec for evaluation cases: the envelope the eval harness relies on.

Case keys::

    id, description, task, source, metadata,
    messages [{id, role, text, tool_calls [{id, name, arguments}],
               tool_call_id, name, pinned, metadata}],
    facts    [{id, statement, answer, aliases, position, message_index}],
    probes   [{id, fact_id, question, expected, aliases}]

Dataset (manifest) keys::

    name, seed, generator, cases [<case id>, ...]

This is deliberately *not* :mod:`caio_code.infrastructure.persistence.codec`:
that module serializes a live session transcript under a version envelope and
raises ``StorageError``; this one serializes a frozen, hand-auditable benchmark
artifact and raises :class:`~caio_code.domain.errors.DatasetError`. Sharing the
two would couple the benchmark format to the persistence format, and a change
in one would silently invalidate the other's committed files.

``Message.tokens`` is a cache and is never serialized. Tuples inside
``metadata`` are written as JSON lists; only the dataclass tuple fields
(``messages``, ``facts``, ``probes``, ``aliases``, ``tool_calls``) come back as
tuples, because that is what the frozen dataclasses expect.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from caio_code.domain.conversation.messages import Message, Role, ToolCall
from caio_code.domain.errors import DatasetError
from caio_code.domain.evaluation.cases import (
    POSITIONS,
    CriticalFact,
    EvalDataset,
    HistoryCase,
    Probe,
)

CASE_FIELDS = ("id", "description", "task", "source", "metadata", "messages", "facts", "probes")
MESSAGE_FIELDS = (
    "id",
    "role",
    "text",
    "tool_calls",
    "tool_call_id",
    "name",
    "pinned",
    "metadata",
)
TOOL_CALL_FIELDS = ("id", "name", "arguments")
FACT_FIELDS = ("id", "statement", "answer", "aliases", "position", "message_index")
PROBE_FIELDS = ("id", "fact_id", "question", "expected", "aliases")
DATASET_FIELDS = ("name", "seed", "generator", "cases")


def _to_jsonable(value: Any) -> Any:
    """Tuples become lists, recursively; anything else passes through json."""
    if isinstance(value, tuple | list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def _bad(where: str, field: str, detail: str, value: Any) -> DatasetError:
    return DatasetError(f"{where}: field {field!r} {detail}, got {value!r}")


def _require_mapping(raw: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise DatasetError(f"{where}: expected an object, got {type(raw).__name__}")
    return raw


def _require_fields(raw: Mapping[str, Any], fields: Sequence[str], where: str) -> None:
    for field in fields:
        if field not in raw:
            raise DatasetError(f"{where}: missing field {field!r}")


def _require_str(raw: Mapping[str, Any], field: str, where: str) -> str:
    value = raw[field]
    if not isinstance(value, str):
        raise _bad(where, field, "must be a string", value)
    return value


def _require_str_or_none(raw: Mapping[str, Any], field: str, where: str) -> str | None:
    value = raw[field]
    if value is None:
        return None
    if not isinstance(value, str):
        raise _bad(where, field, "must be a string or null", value)
    return value


def _require_bool(raw: Mapping[str, Any], field: str, where: str) -> bool:
    value = raw[field]
    if not isinstance(value, bool):
        raise _bad(where, field, "must be a boolean", value)
    return value


def _require_int(raw: Mapping[str, Any], field: str, where: str) -> int:
    value = raw[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(where, field, "must be an integer", value)
    return value


def _require_int_or_none(raw: Mapping[str, Any], field: str, where: str) -> int | None:
    value = raw[field]
    if value is None:
        return None
    return _require_int(raw, field, where)


def _require_str_tuple(raw: Mapping[str, Any], field: str, where: str) -> tuple[str, ...]:
    value = raw[field]
    if not isinstance(value, list):
        raise _bad(where, field, "must be a list of strings", value)
    items: list[str] = []
    for position, item in enumerate(value):
        if not isinstance(item, str):
            raise _bad(f"{where}, {field}[{position}]", field, "must be a string", item)
        items.append(item)
    return tuple(items)


def _require_metadata(raw: Mapping[str, Any], field: str, where: str) -> dict[str, Any]:
    value = raw[field]
    if not isinstance(value, Mapping):
        raise _bad(where, field, "must be an object", value)
    return {str(key): item for key, item in value.items()}


def tool_call_to_dict(call: ToolCall) -> dict[str, Any]:
    """Serialize one tool call with the canonical key set."""
    return {"id": call.id, "name": call.name, "arguments": call.arguments}


def tool_call_from_dict(raw: Any, *, where: str) -> ToolCall:
    """Rebuild a tool call; raises ``DatasetError`` naming the bad field."""
    call = _require_mapping(raw, where)
    _require_fields(call, TOOL_CALL_FIELDS, where)
    return ToolCall(
        id=_require_str(call, "id", where),
        name=_require_str(call, "name", where),
        arguments=_require_str(call, "arguments", where),
    )


def message_to_dict(message: Message) -> dict[str, Any]:
    """Serialize one message with the canonical key set."""
    return {
        "id": message.id,
        "role": str(message.role.value),
        "text": message.text,
        "tool_calls": [tool_call_to_dict(call) for call in message.tool_calls],
        "tool_call_id": message.tool_call_id,
        "name": message.name,
        "pinned": message.pinned,
        "metadata": _to_jsonable(message.metadata),
    }


def message_from_dict(raw: Any, *, where: str = "message") -> Message:
    """Rebuild a message; raises ``DatasetError`` naming the bad field."""
    message = _require_mapping(raw, where)
    _require_fields(message, MESSAGE_FIELDS, where)

    role_raw = message["role"]
    try:
        role = Role(role_raw)
    except ValueError as exc:
        raise _bad(where, "role", "has an unknown value", role_raw) from exc

    calls_raw = message["tool_calls"]
    if not isinstance(calls_raw, list):
        raise _bad(where, "tool_calls", "must be a list", calls_raw)
    tool_calls = tuple(
        tool_call_from_dict(call, where=f"{where}, tool_calls[{position}]")
        for position, call in enumerate(calls_raw)
    )

    return Message(
        id=_require_str(message, "id", where),
        role=role,
        text=_require_str(message, "text", where),
        tool_calls=tool_calls,
        tool_call_id=_require_str_or_none(message, "tool_call_id", where),
        name=_require_str_or_none(message, "name", where),
        pinned=_require_bool(message, "pinned", where),
        tokens=None,
        metadata=_require_metadata(message, "metadata", where),
    )


def fact_to_dict(fact: CriticalFact) -> dict[str, Any]:
    """Serialize one critical fact with the canonical key set."""
    return {
        "id": fact.id,
        "statement": fact.statement,
        "answer": fact.answer,
        "aliases": list(fact.aliases),
        "position": fact.position,
        "message_index": fact.message_index,
    }


def fact_from_dict(raw: Any, *, where: str = "fact") -> CriticalFact:
    """Rebuild a fact; raises ``DatasetError`` naming the bad field."""
    fact = _require_mapping(raw, where)
    _require_fields(fact, FACT_FIELDS, where)

    position = _require_str(fact, "position", where)
    if position not in POSITIONS:
        raise _bad(where, "position", f"must be one of {list(POSITIONS)}", position)

    index = _require_int_or_none(fact, "message_index", where)
    if index is not None and index < 0:
        raise _bad(where, "message_index", "must be non-negative", index)

    return CriticalFact(
        id=_require_str(fact, "id", where),
        statement=_require_str(fact, "statement", where),
        answer=_require_str(fact, "answer", where),
        aliases=_require_str_tuple(fact, "aliases", where),
        position=position,  # type: ignore[arg-type]
        message_index=index,
    )


def probe_to_dict(probe: Probe) -> dict[str, Any]:
    """Serialize one probe with the canonical key set."""
    return {
        "id": probe.id,
        "fact_id": probe.fact_id,
        "question": probe.question,
        "expected": probe.expected,
        "aliases": list(probe.aliases),
    }


def probe_from_dict(raw: Any, *, where: str = "probe") -> Probe:
    """Rebuild a probe; raises ``DatasetError`` naming the bad field."""
    probe = _require_mapping(raw, where)
    _require_fields(probe, PROBE_FIELDS, where)
    return Probe(
        id=_require_str(probe, "id", where),
        fact_id=_require_str(probe, "fact_id", where),
        question=_require_str(probe, "question", where),
        expected=_require_str(probe, "expected", where),
        aliases=_require_str_tuple(probe, "aliases", where),
    )


def case_to_dict(case: HistoryCase) -> dict[str, Any]:
    """Serialize a whole case with the canonical key set."""
    return {
        "id": case.id,
        "description": case.description,
        "task": case.task,
        "source": case.source,
        "metadata": _to_jsonable(case.metadata),
        "messages": [message_to_dict(message) for message in case.messages],
        "facts": [fact_to_dict(fact) for fact in case.facts],
        "probes": [probe_to_dict(probe) for probe in case.probes],
    }


def case_from_dict(raw: Any, *, source: str = "<case>") -> HistoryCase:
    """Rebuild a case; raises ``DatasetError`` naming the bad field."""
    case = _require_mapping(raw, source)
    _require_fields(case, CASE_FIELDS, source)

    case_id = _require_str(case, "id", source)
    where = f"{source} case {case_id!r}" if case_id else source

    messages_raw = case["messages"]
    if not isinstance(messages_raw, list):
        raise _bad(where, "messages", "must be a list", messages_raw)
    facts_raw = case["facts"]
    if not isinstance(facts_raw, list):
        raise _bad(where, "facts", "must be a list", facts_raw)
    probes_raw = case["probes"]
    if not isinstance(probes_raw, list):
        raise _bad(where, "probes", "must be a list", probes_raw)

    return HistoryCase(
        id=case_id,
        description=_require_str(case, "description", where),
        task=_require_str(case, "task", where),
        source=_require_str(case, "source", where),
        metadata=_require_metadata(case, "metadata", where),
        messages=tuple(
            message_from_dict(item, where=f"{where}, messages[{position}]")
            for position, item in enumerate(messages_raw)
        ),
        facts=tuple(
            fact_from_dict(item, where=f"{where}, facts[{position}]")
            for position, item in enumerate(facts_raw)
        ),
        probes=tuple(
            probe_from_dict(item, where=f"{where}, probes[{position}]")
            for position, item in enumerate(probes_raw)
        ),
    )


def dataset_to_dict(dataset: EvalDataset) -> dict[str, Any]:
    """Serialize the manifest: name, seed, generator and the case ids."""
    return {
        "name": dataset.name,
        "seed": dataset.seed,
        "generator": dataset.generator,
        "cases": [case.id for case in dataset.cases],
    }


def dataset_from_dict(
    raw: Any,
    cases: Sequence[HistoryCase],
    *,
    source: str = "<dataset>",
    require_all_listed: bool = True,
) -> EvalDataset:
    """Rebuild a dataset from its manifest plus the already-decoded cases.

    The manifest holds only case ids, so the cases arrive decoded; the ids are
    cross-checked against them, which is what catches a directory where a case
    file was renamed or deleted after the manifest was written. A partial load
    (``require_all_listed=False``) skips that check, because loading fewer cases
    than the manifest lists is the point of ``load_dataset(..., limit=n)``.
    """
    manifest = _require_mapping(raw, source)
    _require_fields(manifest, DATASET_FIELDS, source)

    name = _require_str(manifest, "name", source)
    seed = _require_int(manifest, "seed", source)
    generator = _require_str(manifest, "generator", source)
    listed = manifest["cases"]
    if not isinstance(listed, list):
        raise _bad(source, "cases", "must be a list of case ids", listed)
    for position, item in enumerate(listed):
        if not isinstance(item, str):
            raise _bad(f"{source}, cases[{position}]", "cases", "must be a string", item)

    present = {case.id for case in cases}
    missing = [case_id for case_id in listed if case_id not in present]
    if missing and require_all_listed:
        raise DatasetError(f"{source}: manifest lists cases with no file: {sorted(missing)}")
    unlisted = sorted(present - set(listed))
    if unlisted:
        raise DatasetError(f"{source}: case files absent from the manifest: {unlisted}")
    if len(listed) != len(set(listed)):
        raise DatasetError(f"{source}: manifest lists duplicate case ids: {sorted(listed)}")

    order = {case_id: position for position, case_id in enumerate(listed)}
    ordered = tuple(sorted(cases, key=lambda case: order[case.id]))
    return EvalDataset(name=name, cases=ordered, seed=seed, generator=generator)


__all__ = [
    "CASE_FIELDS",
    "DATASET_FIELDS",
    "FACT_FIELDS",
    "MESSAGE_FIELDS",
    "PROBE_FIELDS",
    "TOOL_CALL_FIELDS",
    "case_from_dict",
    "case_to_dict",
    "dataset_from_dict",
    "dataset_to_dict",
    "fact_from_dict",
    "fact_to_dict",
    "message_from_dict",
    "message_to_dict",
    "probe_from_dict",
    "probe_to_dict",
    "tool_call_from_dict",
    "tool_call_to_dict",
]
