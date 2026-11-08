"""The spill-to-file derivation: the ``spill`` variant of a case.

Truncation in this thesis is not head-and-tail cutting; it is relocation. A tool
output above the byte ceiling leaves the context entirely and becomes a file the
agent can read back when it needs the detail. Deriving the variant from the same
committed case file -- instead of shipping a second dataset -- is what keeps the
two variants byte-identical everywhere except the spilled outputs, so any
retention difference is attributable to the truncation and to nothing else.

The derivation is pure and deterministic: same case, same ceiling, same spill
files, same pointer texts.
"""

from __future__ import annotations

from caio_code.domain.conversation.messages import Message
from caio_code.domain.errors import DatasetError
from caio_code.domain.evaluation.cases import HistoryCase, SpillFile

SPILL_POINTER_TEMPLATE = (
    "... output saved to {path} ({bytes} bytes, {lines} lines); "
    "read it with read_file if you need its content ..."
)
SPILL_PATH_TEMPLATE = "spill/{case_id}/{message_id}.txt"
SPILL_EDIT_MARKER = "spilled-to-file"


def spill_path(case_id: str, message_id: str) -> str:
    """The virtual path a spilled output is served from during replay."""
    return SPILL_PATH_TEMPLATE.format(case_id=case_id, message_id=message_id)


def derive_spill_case(case: HistoryCase, *, max_bytes: int) -> HistoryCase:
    """The ``spill`` variant of ``case`` under a byte ceiling.

    Every tool result whose text exceeds ``max_bytes`` is replaced by a pointer
    message; the full text moves into an in-memory :class:`SpillFile` keyed by
    the pointer's path. Messages below the ceiling, and everything that is not a
    tool result, survive by identity, so the shaped context differs from the
    ``full`` variant only where the truncation acted.
    """
    if max_bytes <= 0:
        msg = f"max_bytes must be positive, got {max_bytes}"
        raise DatasetError(msg)
    if case.variant != "full":
        msg = f"case {case.id!r} is already variant {case.variant!r}; only full cases derive"
        raise DatasetError(msg)

    messages: list[Message] = []
    spill_files: list[SpillFile] = []
    for message in case.messages:
        encoded = len(message.text.encode("utf-8"))
        if not message.is_tool_result() or encoded <= max_bytes:
            messages.append(message)
            continue
        path = spill_path(case.id, message.id)
        spill_files.append(
            SpillFile(
                path=path,
                text=message.text,
                source_message_id=message.id,
                tool_name=message.name or "",
                byte_count=encoded,
                line_count=message.text.count("\n") + 1,
            )
        )
        messages.append(
            message.with_text(
                SPILL_POINTER_TEMPLATE.format(
                    path=path,
                    bytes=encoded,
                    lines=message.text.count("\n") + 1,
                ),
                marker=SPILL_EDIT_MARKER,
            )
        )

    return HistoryCase(
        id=case.id,
        description=case.description,
        messages=tuple(messages),
        facts=case.facts,
        probes=case.probes,
        task=case.task,
        source=case.source,
        variant="spill",
        spill_files=tuple(spill_files),
        metadata={**case.metadata, "spill_max_bytes": max_bytes},
    )


def variant_case(case: HistoryCase, variant: str, *, max_bytes: int) -> HistoryCase:
    """The case as the requested variant; ``full`` passes through unchanged."""
    if variant == "full":
        if case.variant != "full":
            msg = f"case {case.id!r} is variant {case.variant!r}, not full"
            raise DatasetError(msg)
        return case
    if variant == "spill":
        return derive_spill_case(case, max_bytes=max_bytes)
    msg = f"unknown variant {variant!r}; expected 'full' or 'spill'"
    raise DatasetError(msg)


__all__ = [
    "SPILL_EDIT_MARKER",
    "SPILL_PATH_TEMPLATE",
    "SPILL_POINTER_TEMPLATE",
    "derive_spill_case",
    "spill_path",
    "variant_case",
]
