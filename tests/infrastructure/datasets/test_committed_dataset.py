"""Invariantes do dataset congelado: o que o Capítulo 4 mede, verificado por arquivo.

Estes testes leem os JSON commitados em ``evals/datasets/long_histories/`` e
não o gerador: se alguém regenerar o dataset com um gerador quebrado, é aqui
que falha. Os limites abaixo são os do desenho experimental (60-140 mensagens,
60k-200k caracteres, 6-8 fatos, 3-5 sondas), e os tetos de truncagem vêm de
``config.ToolOutputConfig`` para não divergir do agente.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from caio_code.config import EvalConfig, GuardrailConfig, ToolOutputConfig, WindowConfig
from caio_code.domain.conversation.messages import Message, Role
from caio_code.domain.evaluation.cases import POSITIONS, HistoryCase, answer_matches
from caio_code.domain.evaluation.spill import derive_spill_case
from caio_code.domain.policy.tool_output import TruncationLimits, truncate_text
from caio_code.infrastructure.datasets.loader import load_dataset
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET_DIR = REPO_ROOT / EvalConfig().dataset_dir

CASE_COUNT = EvalConfig().max_cases
MIN_MESSAGES = 60
MAX_MESSAGES = 140
MIN_CHARS = 60_000
MAX_CHARS = 200_000
MIN_WINDOW_MULTIPLES = 2.0
MAX_WINDOW_MULTIPLES = 6.0
EARLY_FRACTION = 0.20
LATE_FRACTION = 0.20
MIN_FACTS = 6
MAX_FACTS = 8
MIN_FACTS_PER_POSITION = 2
MIN_ALIASES = 1
MAX_ALIASES = 3
MIN_PROBES = 3
MAX_PROBES = 5
MIN_PROBE_POSITIONS = 2
MIN_TOOL_RESULTS = 4
MIN_OUTPUTS_ABOVE_A_CEILING = 2
MIN_FACTS_DESTROYED_BY_TRUNCATION = 1
MIN_TRAPS = 1
MIN_NEAR_DUPLICATES = 2
REPEATED_CALLS = GuardrailConfig().max_repeats
MIN_TODO_CALLS = 2
MAX_TODO_CALLS = 4
TODO_TOOL = "write_todos"
TODO_STATUSES = ("pending", "in_progress", "completed")
LIMITS = TruncationLimits(
    max_lines=ToolOutputConfig().max_lines, max_bytes=ToolOutputConfig().max_bytes
)

DATASET = load_dataset(DATASET_DIR)
CASES = DATASET.cases


def position_of(index: int, total: int) -> str:
    """A mesma aritmética do gerador: primeiro e último quinto do histórico."""
    if index < math.ceil(total * EARLY_FRACTION):
        return "early"
    if index >= total - math.floor(total * LATE_FRACTION):
        return "late"
    return "middle"


def tool_results(case: HistoryCase) -> list[Message]:
    return [message for message in case.messages if message.is_tool_result()]


def truncated_outputs(case: HistoryCase) -> list[Message]:
    return [
        message
        for message in tool_results(case)
        if message.text.count("\n") + 1 > LIMITS.max_lines
        or len(message.text.encode("utf-8")) > LIMITS.max_bytes
    ]


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def test_dataset_has_the_five_frozen_cases() -> None:
    assert len(CASES) == CASE_COUNT
    assert [case.id for case in CASES] == [
        "case-01-api-service-debug",
        "case-02-frontend-refactor",
        "case-03-pipeline-migration-incident",
        "case-04-flaky-ci-test",
        "case-05-dependency-upgrade",
    ]


def test_cases_differ_in_domain_and_in_size() -> None:
    domains = [case.metadata["domain"] for case in CASES]
    assert len(set(domains)) == len(domains)
    sizes = [case.char_count for case in CASES]
    assert max(sizes) - min(sizes) >= 20_000, f"cases are all the same size: {sizes}"


def test_every_case_file_ends_with_a_newline_and_is_valid_json() -> None:
    for path in sorted(DATASET_DIR.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n"), f"{path.name} does not end with a newline"
        json.loads(text)


def test_manifest_lists_exactly_the_case_files() -> None:
    manifest = json.loads((DATASET_DIR / "dataset.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "long_histories"
    assert manifest["seed"] == EvalConfig().seed
    assert manifest["cases"] == [case.id for case in CASES]
    for path in sorted(DATASET_DIR.glob("case-*.json")):
        assert path.stem in manifest["cases"]


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_case_is_long_enough_to_overflow_the_window(case: HistoryCase) -> None:
    assert MIN_MESSAGES <= len(case.messages) <= MAX_MESSAGES
    assert MIN_CHARS <= case.char_count <= MAX_CHARS
    tokens = CharProxyTokenCounter().count_transcript(case.transcript)
    multiples = tokens / WindowConfig().tokens
    assert MIN_WINDOW_MULTIPLES <= multiples <= MAX_WINDOW_MULTIPLES, (
        f"{case.id}: {tokens} tokens is {multiples:.2f}x the window"
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_message_and_tool_call_ids_follow_their_templates(case: HistoryCase) -> None:
    expected_messages = [f"{case.id}-m{index:03d}" for index in range(len(case.messages))]
    assert [message.id for message in case.messages] == expected_messages

    calls = [call.id for message in case.messages for call in message.tool_calls]
    assert calls == [f"{case.id}-tc{index:03d}" for index in range(1, len(calls) + 1)]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_every_tool_result_answers_a_tool_call(case: HistoryCase) -> None:
    for index, message in enumerate(case.messages):
        if message.role is not Role.TOOL:
            continue
        assert message.tool_call_id, f"{message.id} has no tool_call_id"
        assert message.name, f"{message.id} has no tool name"
        previous = case.messages[index - 1]
        assert message.tool_call_id in [call.id for call in previous.tool_calls], (
            f"{message.id} answers a call that is not in {previous.id}"
        )


# ---------------------------------------------------------------------------
# Pinning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_the_task_statement_is_the_first_message_and_is_pinned(case: HistoryCase) -> None:
    first = case.messages[0]
    assert first.role is Role.USER
    assert first.pinned is True
    assert first.text == case.task
    assert first.metadata["role_in_case"] == "task"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_one_late_contract_message_is_pinned_too(case: HistoryCase) -> None:
    contracts = [
        index
        for index, message in enumerate(case.messages)
        if message.pinned and message.metadata.get("role_in_case") == "contract"
    ]
    assert len(contracts) == 1, f"{case.id}: pinned contracts at {contracts}"
    index = contracts[0]
    assert case.messages[index].role is Role.USER
    assert position_of(index, len(case.messages)) == "late"
    assert len(case.transcript.pinned_indices()) == 2


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_the_contract_does_not_restate_a_fact(case: HistoryCase) -> None:
    """Senão uma política que só preserva mensagens fixadas acertaria a sonda."""
    contract = next(
        message
        for message in case.messages
        if message.metadata.get("role_in_case") == "contract"
    )
    for fact in case.facts:
        assert not answer_matches(contract.text, fact.acceptable_answers), (
            f"{case.id}: the contract restates fact {fact.id} ({fact.answer!r})"
        )


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_facts_are_spread_over_the_three_positions(case: HistoryCase) -> None:
    assert MIN_FACTS <= len(case.facts) <= MAX_FACTS
    total = len(case.messages)
    counts = {position: 0 for position in POSITIONS}
    for fact in case.facts:
        assert fact.message_index is not None
        assert 0 <= fact.message_index < total
        assert fact.position == position_of(fact.message_index, total)
        counts[fact.position] += 1
    for position in POSITIONS:
        assert counts[position] >= MIN_FACTS_PER_POSITION, f"{case.id}: {counts}"
    assert counts == case.metadata["fact_positions"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_every_answer_is_findable_in_the_message_that_states_it(case: HistoryCase) -> None:
    for fact in case.facts:
        carrier = case.messages[fact.message_index or 0]
        assert answer_matches(carrier.text, fact.acceptable_answers), (
            f"{case.id}: {fact.answer!r} does not appear in {carrier.id}"
        )
        assert MIN_ALIASES <= len(fact.aliases) <= MAX_ALIASES
        assert fact.statement.strip()


def rendered(message: Message) -> str:
    """O que o modelo vê: o texto mais a chamada de ferramenta que o produziu."""
    return " ".join(
        [message.text, *(call.name + " " + call.arguments for call in message.tool_calls)]
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_each_answer_appears_exactly_once_in_the_history(case: HistoryCase) -> None:
    """A propriedade central do desenho: reter a mensagem certa é o que decide a sonda.

    Se a resposta de um fato aparece em outra mensagem — no filler, num alvo de
    ferramenta, numa decisão duplicada —, qualquer política que preserve essa
    outra mensagem acerta a sonda sem ter retido o original, e o número medido
    não significa nada.
    """
    for fact in case.facts:
        carrier = case.messages[fact.message_index or 0]
        hits = [
            message.id
            for message in case.messages
            if answer_matches(rendered(message), fact.acceptable_answers)
        ]
        assert hits == [carrier.id], (
            f"{case.id}: {fact.answer!r} also appears in "
            f"{[hit for hit in hits if hit != carrier.id]}"
        )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_answers_are_distinct_and_not_common_words(case: HistoryCase) -> None:
    answers = [fact.answer for fact in case.facts]
    assert len(set(answers)) == len(answers)
    for answer in answers:
        assert len(answer) >= 5, f"{case.id}: answer {answer!r} is too short to be checkable"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_a_superseded_decision_precedes_its_correction(case: HistoryCase) -> None:
    traps = [
        (index, message)
        for index, message in enumerate(case.messages)
        if message.metadata.get("trap_for")
    ]
    assert len(traps) >= MIN_TRAPS, f"{case.id}: no superseded decision to distract with"
    for index, message in traps:
        slug = message.metadata["trap_for"]
        corrected = next(
            fact
            for fact in case.facts
            if case.messages[fact.message_index or 0].metadata.get("states_fact") == slug
        )
        assert index < (corrected.message_index or 0), (
            f"{case.id}: trap {message.id} comes after the correction of {corrected.id}"
        )
        assert not answer_matches(message.text, corrected.acceptable_answers), (
            f"{case.id}: trap {message.id} already contains the answer of {corrected.id}"
        )


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_probes_target_existing_facts_and_cover_positions(case: HistoryCase) -> None:
    assert MIN_PROBES <= len(case.probes) <= MAX_PROBES
    fact_ids = {fact.id for fact in case.facts}
    targeted = [probe.fact_id for probe in case.probes]
    assert len(set(targeted)) == len(targeted)
    positions = set()
    for probe in case.probes:
        assert probe.fact_id in fact_ids
        fact = case.fact(probe.fact_id)
        carrier = case.messages[fact.message_index or 0]
        assert answer_matches(carrier.text, probe.acceptable_answers), (
            f"{case.id}: {probe.id} expects {probe.expected!r}, absent from {carrier.id}"
        )
        assert len(probe.question.split()) >= 5
        assert probe.question.endswith("?")
        positions.add(fact.position)
    assert len(positions) >= MIN_PROBE_POSITIONS, f"{case.id}: probes cover {sorted(positions)}"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_probe_ids_are_unique_and_ordered(case: HistoryCase) -> None:
    assert [probe.id for probe in case.probes] == [
        f"{case.id}-p{index:02d}" for index in range(len(case.probes))
    ]
    assert [fact.id for fact in case.facts] == [
        f"{case.id}-f{index:02d}" for index in range(len(case.facts))
    ]


# ---------------------------------------------------------------------------
# Tool outputs and truncation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_case_carries_large_tool_outputs(case: HistoryCase) -> None:
    results = tool_results(case)
    assert len(results) >= MIN_TOOL_RESULTS
    assert len(truncated_outputs(case)) >= MIN_OUTPUTS_ABOVE_A_CEILING
    assert any(len(message.text.encode("utf-8")) > LIMITS.max_bytes for message in results)
    assert case.metadata["tool_results"] == len(results)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_the_largest_tool_output_matches_the_metadata(case: HistoryCase) -> None:
    largest = max(tool_results(case), key=lambda message: len(message.text))
    assert case.metadata["largest_tool_output_chars"] == len(largest.text)
    assert case.metadata["largest_tool_output_lines"] == largest.text.count("\n") + 1
    assert case.metadata["largest_tool_output_message"] == largest.id
    assert len(largest.text) > LIMITS.max_bytes


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_truncation_destroys_a_fact_that_only_lived_in_the_output(case: HistoryCase) -> None:
    destroyed = 0
    for message in truncated_outputs(case):
        truncated, changed = truncate_text(message.text, LIMITS)
        assert changed
        for fact in case.facts:
            if case.messages[fact.message_index or 0].id != message.id:
                continue
            assert not answer_matches(truncated, fact.acceptable_answers), (
                f"{case.id}: truncating {message.id} still leaves fact {fact.id} readable"
            )
            elsewhere = [
                other.id
                for other in case.messages
                if other.id != message.id
                and answer_matches(other.text, fact.acceptable_answers)
            ]
            assert not elsewhere, (
                f"{case.id}: fact {fact.id} is restated in {elsewhere}, so the truncation arm "
                "would not lose it"
            )
            destroyed += 1
    assert destroyed >= MIN_FACTS_DESTROYED_BY_TRUNCATION, f"{case.id}: {destroyed} destroyed"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_small_tool_outputs_survive_truncation(case: HistoryCase) -> None:
    """Nem tudo pode ser cortado: o braço de truncagem precisa de contraste."""
    kept = [
        message
        for message in tool_results(case)
        if message.text.count("\n") + 1 <= LIMITS.max_lines
        and len(message.text.encode("utf-8")) <= LIMITS.max_bytes
    ]
    assert kept, f"{case.id}: every tool output would be truncated"
    for message in kept:
        assert truncate_text(message.text, LIMITS)[1] is False


# ---------------------------------------------------------------------------
# Distractors and todos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_the_history_repeats_itself(case: HistoryCase) -> None:
    duplicates = [
        message for message in case.messages if message.metadata.get("filler") == "duplicate"
    ]
    assert len(duplicates) >= MIN_NEAR_DUPLICATES
    assert case.metadata["near_duplicate_messages"] == len(duplicates)
    for message in duplicates:
        assert sum(1 for other in case.messages if other.text == message.text) >= 2


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_a_tool_call_repeats_with_identical_arguments(case: HistoryCase) -> None:
    """O padrão que o guardrail de loop existe para pegar."""
    seen: dict[tuple[str, str], int] = {}
    for message in case.messages:
        for call in message.tool_calls:
            key = (call.name, call.arguments)
            seen[key] = seen.get(key, 0) + 1
    repeated = [key for key, count in seen.items() if count >= REPEATED_CALLS]
    assert repeated, f"{case.id}: no call repeats {REPEATED_CALLS} times: {sorted(seen)}"
    assert case.metadata["repeated_tool_calls"] >= REPEATED_CALLS * 2


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_todo_boards_evolve(case: HistoryCase) -> None:
    calls = [
        message
        for message in case.messages
        if any(call.name == TODO_TOOL for call in message.tool_calls)
    ]
    assert MIN_TODO_CALLS <= len(calls) <= MAX_TODO_CALLS
    assert case.metadata["todo_steps"] == len(calls)

    completed_before = -1
    contents: list[tuple[str, ...]] = []
    for message in calls:
        payload = json.loads(message.tool_calls[0].arguments)
        items = payload["todos"]
        assert items
        for item in items:
            assert item["status"] in TODO_STATUSES
            assert item["content"]
        assert sum(1 for item in items if item["status"] == "in_progress") <= 1
        completed = sum(1 for item in items if item["status"] == "completed")
        assert completed > completed_before, f"{case.id}: the board does not advance"
        completed_before = completed
        contents.append(tuple(item["content"] for item in items))
    assert len(set(contents)) == 1, f"{case.id}: the board items change between updates"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_metadata_records_the_audit_trail(case: HistoryCase) -> None:
    metadata = case.metadata
    for key in (
        "generator",
        "seed",
        "message_count",
        "char_count",
        "largest_tool_output_chars",
        "fact_positions",
        "notes",
        "domain",
        "proxy_tokens",
    ):
        assert key in metadata, f"{case.id}: metadata has no {key!r}"
    assert metadata["generator"] == "evals/generate_dataset.py"
    assert metadata["seed"] == EvalConfig().seed
    assert metadata["message_count"] == len(case.messages)
    assert metadata["char_count"] == case.char_count
    assert metadata["proxy_tokens"] == CharProxyTokenCounter().count_transcript(case.transcript)
    assert metadata["notes"].strip()
    assert case.source == "synthetic"
    assert case.task and case.description


# ---------------------------------------------------------------------------
# Spill variant (chat-replay do Capítulo 4, v5)
# ---------------------------------------------------------------------------

DATASET_128K_DIR = REPO_ROOT / "evals" / "datasets" / "long_histories_128k"
# O desenho do dataset garante >=2 saídas acima de UM teto (linhas OU bytes);
# a variante spill atua só no teto de bytes, então o mínimo aqui é 1 por caso.
MIN_BYTE_SPILLS = 1


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_spill_variant_derives_from_the_committed_case(case: HistoryCase) -> None:
    """A variante spill é derivada em runtime; o arquivo commitado não muda."""
    derived = derive_spill_case(case, max_bytes=LIMITS.max_bytes)

    assert derived.variant == "spill"
    assert len(derived.spill_files) >= MIN_BYTE_SPILLS
    assert len(derived.messages) == len(case.messages)
    # o pareamento tool call/resultado sobrevive, senão o structure repair do
    # replay descartaria os ponteiros
    for original, replaced in zip(case.messages, derived.messages, strict=True):
        assert replaced.role is original.role
        assert replaced.tool_call_id == original.tool_call_id
        assert replaced.tool_calls == original.tool_calls
    for spill in derived.spill_files:
        pointer = next(
            message for message in derived.messages if message.id == spill.source_message_id
        )
        assert spill.path in pointer.text
        assert spill.byte_count > LIMITS.max_bytes


@pytest.mark.skipif(not DATASET_128K_DIR.is_dir(), reason="dataset 128k ausente")
def test_128k_cases_also_derive_a_nonempty_spill_variant() -> None:
    dataset = load_dataset(DATASET_128K_DIR)
    for case in dataset.cases:
        derived = derive_spill_case(case, max_bytes=LIMITS.max_bytes)
        assert derived.spill_files, f"{case.id}: nenhuma saída acima do teto"
