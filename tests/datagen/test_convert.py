"""Testes offline de `datagen/scripts/convert.py`.

O Data Designer fornece conteúdo; `convert.py` impõe estrutura. Estes testes
cobrem exatamente as invariantes que, se quebradas, fariam o Capítulo 4 medir
algo falso em vez de falhar em voz alta:

- pareamento `tool_calls` <-> `tool_call_id` e ids sequenciais;
- seleção de fatos por unicidade medida (o coração da pontuabilidade);
- expansão de saídas de ferramenta acima dos tetos de truncagem;
- mensagem de contrato dentro do último quinto, fora dos índices reservados.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path
from types import ModuleType

import pytest

from caio_code.domain.conversation.messages import Message, Role

ROOT = Path(__file__).resolve().parents[2]
CONVERT_PATH = ROOT / "datagen" / "scripts" / "convert.py"
MODULE_NAME = "datagen_convert"

ASSEMBLY = {
    "first_message_pinned": True,
    "tool_output_line_ceiling": 2_000,
    "tool_output_byte_ceiling": 51_200,
}


def load_convert() -> ModuleType:
    """Importa `datagen/scripts/convert.py` como módulo, uma vez por sessão."""
    if MODULE_NAME in sys.modules:
        return sys.modules[MODULE_NAME]
    spec = importlib.util.spec_from_file_location(MODULE_NAME, CONVERT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def conv() -> ModuleType:
    return load_convert()


def _pool(count: int, size: int, prefix: str) -> list[str]:
    return [f"{prefix}{i} " + "x" * (size - len(f"{prefix}{i} ") - 1) for i in range(count)]


def _tools(count: int, size: int) -> list[tuple[str, str]]:
    return [("read_file", body) for body in _pool(count, size, "tool")]


def _build(conv: ModuleType, *, probability: float = 0.5) -> tuple[list[Message], list[int]]:
    # char_target é deliberadamente inalcançável: quem encerra o laço é o
    # esgotamento dos pools. As duas saídas expandidas acima dos tetos somam
    # ~200 KB sozinhas, então um alvo pequeno pararia o transcript antes do
    # piso de 40 mensagens que `_build_messages` exige.
    return conv._build_messages(
        "case-test",
        task="the task statement",
        user_pool=_pool(30, 100, "user"),
        assistant_pool=_pool(30, 100, "asst"),
        tool_pool=_tools(30, 40),
        char_target=500_000,
        tool_call_probability=probability,
        rng=random.Random(20261107),
        assembly=ASSEMBLY,
    )


def _candidate(answer: str, *aliases: str, facet: str = "a TCP port") -> dict[str, object]:
    """Varargs de propósito: ``("x")`` é uma string, não tupla, e iterar uma
    string produz aliases de uma letra que casam com qualquer mensagem."""
    return {
        "facet": facet,
        "statement": f"the value in use is {answer}",
        "answer": answer,
        "question": f"what was the agreed value for {facet}?",
        "aliases": aliases,
    }


def test_build_messages_emits_sequential_ids_and_a_pinned_task(conv: ModuleType) -> None:
    messages, _ = _build(conv)

    assert [m.id for m in messages] == [f"case-test-m{i:03d}" for i in range(len(messages))]
    assert messages[0].role is Role.USER
    assert messages[0].pinned is True
    assert messages[0].text == "the task statement"


def test_every_tool_result_is_paired_with_an_earlier_tool_call(conv: ModuleType) -> None:
    messages, _ = _build(conv, probability=1.0)

    open_calls: set[str] = set()
    tool_results = 0
    for message in messages:
        for call in message.tool_calls:
            assert call.id not in open_calls, f"tool_call id duplicado: {call.id}"
            open_calls.add(call.id)
        if message.role is Role.TOOL:
            tool_results += 1
            assert message.tool_call_id in open_calls, "tool result órfão"
    assert tool_results > 0, "nenhum tool result gerado: o pareamento não foi exercitado"


def test_expand_over_ceilings_exceeds_both_truncation_ceilings(conv: ModuleType) -> None:
    expanded = conv._expand_over_ceilings(
        "alpha\nbravo\ncharlie", line_ceiling=2_000, byte_ceiling=51_200
    )

    assert expanded.count("\n") + 1 > 2_000
    assert len(expanded.encode("utf-8")) > 51_200


def test_build_messages_plants_outputs_above_the_ceilings(conv: ModuleType) -> None:
    messages, expanded_indices = _build(conv, probability=1.0)

    assert len(expanded_indices) == 2
    for index in expanded_indices:
        text = messages[index].text
        assert text.count("\n") + 1 > ASSEMBLY["tool_output_line_ceiling"]
        assert len(text.encode("utf-8")) > ASSEMBLY["tool_output_byte_ceiling"]


def test_select_facts_rejects_an_answer_that_occurs_elsewhere(conv: ModuleType) -> None:
    # `--workers` aparece no filler: uma política que mantivesse a mensagem
    # errada ainda acertaria a sonda, então o fato não é pontuável.
    messages = [
        Message(id="m0", role=Role.USER, text="the task"),
        Message(id="m1", role=Role.ASSISTANT, text="run uvicorn --workers 4"),
    ]
    candidates = [
        _candidate("--workers", "workers", "-w", facet="a command-line flag"),
        _candidate("payments_ledger", "the payments_ledger schema", "ledger database", facet="a database name"),
    ]

    selected = conv._select_facts(candidates, messages, needed=1, contract_text="restate the task")

    assert [c["answer"] for c in selected] == ["payments_ledger"]


def test_select_facts_rejects_answers_that_are_substrings_of_each_other(conv: ModuleType) -> None:
    messages = [Message(id="m0", role=Role.USER, text="the task")]
    candidates = [
        _candidate("8000", "port 8000", "tcp/8000"),
        _candidate("80", "port 80", "tcp/80"),
    ]

    # "80" é subcadena de "8000": uma resposta certa para um fato também seria
    # aceita para o outro, então os dois não podem coexistir no mesmo caso.
    assert conv._ambiguous(candidates[0], candidates[1]) is True
    with pytest.raises(conv.ConvertError, match="pontuáveis"):
        conv._select_facts(candidates, messages, needed=2, contract_text="restate the task")


def test_select_facts_rejects_an_answer_the_contract_already_reveals(conv: ModuleType) -> None:
    messages = [Message(id="m0", role=Role.USER, text="the task")]
    candidates = [_candidate("payments_ledger", "the payments_ledger schema", "ledger database", facet="a database name")]

    with pytest.raises(conv.ConvertError, match="pontuáveis"):
        conv._select_facts(
            candidates,
            messages,
            needed=1,
            contract_text="restate the task and confirm the payments_ledger schema",
        )


def test_select_facts_raises_when_the_pool_has_too_few_unique_facts(conv: ModuleType) -> None:
    messages = [Message(id="m0", role=Role.USER, text="uvicorn --workers 4")]
    candidates = [_candidate("--workers", "workers", facet="a command-line flag")]

    with pytest.raises(conv.ConvertError, match="pontuáveis"):
        conv._select_facts(candidates, messages, needed=4, contract_text="restate the task")


def test_select_facts_prefers_distinct_facets(conv: ModuleType) -> None:
    messages = [Message(id="m0", role=Role.USER, text="the task")]
    candidates = [
        _candidate("8000", "port 8000"),
        _candidate("8001", "port 8001"),
        _candidate("payments_ledger", "the ledger schema", facet="a database name"),
    ]

    selected = conv._select_facts(candidates, messages, needed=2, contract_text="restate the task")

    assert {c["facet"] for c in selected} == {"a TCP port", "a database name"}


def test_contract_lands_in_the_last_fifth_on_a_free_user_message(conv: ModuleType) -> None:
    messages, _ = _build(conv)
    reserved = {len(messages) - 1}

    index = conv._place_contract(messages, "the task statement", reserved=reserved)

    assert index >= len(messages) - max(2, len(messages) // 5)
    assert index not in reserved
    assert messages[index].role is Role.USER
    assert messages[index].metadata["role_in_case"] == "contract"
    assert messages[index].pinned is False


def test_embed_facts_never_overwrites_the_contract_message(conv: ModuleType) -> None:
    messages, _ = _build(conv)
    selected = [
        _candidate(f"value-{i}", f"alias-{i}a", f"alias-{i}b", facet=f"facet {i}") for i in range(12)
    ]
    fractions = {
        "early": [0.08, 0.12, 0.16, 0.20],
        "middle": [0.44, 0.48, 0.52, 0.56],
        "late": [0.84, 0.88, 0.92, 0.96],
    }
    contract_index = conv._place_contract(messages, "the task statement", reserved=set())

    facts, probes = conv._embed_facts(
        "case-test", messages, selected, fractions, reserved={contract_index}
    )

    assert len(facts) == 12 and len(probes) == 12
    assert contract_index not in [f.message_index for f in facts]
    assert len({f.message_index for f in facts}) == 12, "dois fatos na mesma mensagem"
    assert messages[contract_index].metadata["role_in_case"] == "contract"


def test_embed_facts_puts_the_statement_in_the_message_it_points_at(conv: ModuleType) -> None:
    messages, _ = _build(conv)
    selected = [
        _candidate(f"value-{i}", f"alias-{i}a", f"alias-{i}b", facet=f"facet {i}") for i in range(12)
    ]
    fractions = {
        "early": [0.08, 0.12, 0.16, 0.20],
        "middle": [0.44, 0.48, 0.52, 0.56],
        "late": [0.84, 0.88, 0.92, 0.96],
    }

    facts, _ = conv._embed_facts("case-test", messages, selected, fractions, reserved=set())

    for fact in facts:
        carrier = messages[fact.message_index or 0]
        assert fact.statement in carrier.text
        assert carrier.metadata["carries_fact"] == fact.id
