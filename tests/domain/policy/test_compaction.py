"""Offline tests for the compaction planner and the verbatim-tail boundary."""

from __future__ import annotations

from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Message, Role, Transcript
from caio_code.domain.conversation.summary import (
    PRIOR_SUMMARY_INSTRUCTION,
    SECTION_HEADINGS,
    SUMMARY_MESSAGE_PREFIX,
    WORK_STATE_SUBSECTIONS,
    empty_summary,
)
from caio_code.domain.policy.base import PolicyRequest
from caio_code.domain.policy.compaction import SUMMARY_PLACEHOLDER, CompactionPlanner, tail_boundary
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

COUNTER = CharProxyTokenCounter()
BUDGET = TokenBudget(10_000)
FILLER = "alpha bravo charlie delta " * 4  # 100 chars -> 25 proxy tokens


def _transcript() -> Transcript:
    messages = [Message(id="task", role=Role.USER, text="the task", pinned=True)]
    messages.extend(
        Message(id=f"m{i}", role=Role.USER, text=f"{FILLER}{i}") for i in range(6)
    )
    return Transcript.of(messages)


def _request(transcript: Transcript, **kwargs: object) -> PolicyRequest:
    return PolicyRequest(transcript=transcript, budget=BUDGET, counter=COUNTER, **kwargs)  # type: ignore[arg-type]


def test_tail_boundary_keeps_the_newest_messages_within_keep_tokens() -> None:
    assert tail_boundary([10, 20, 30, 40], keep_tokens=70) == 2
    assert tail_boundary([10, 20, 30, 40], keep_tokens=40) == 3


def test_tail_boundary_keeps_a_single_newest_message_larger_than_keep_tokens() -> None:
    assert tail_boundary([5, 5, 100], keep_tokens=10) == 2


def test_tail_boundary_of_empty_costs_is_zero() -> None:
    assert tail_boundary([], keep_tokens=10) == 0


def test_boundary_zero_means_nothing_to_compact_and_everything_is_kept() -> None:
    transcript = _transcript()

    decision = CompactionPlanner(keep_tokens=10_000).plan(_request(transcript))

    assert decision.kept_indices == tuple(range(len(transcript)))
    assert decision.injected == ()
    assert decision.detail["compacted"] is False
    assert any(note.startswith("nothing to compact") for note in decision.notes)


def test_injected_summary_message_is_pinned_and_carries_prompt_and_placeholder() -> None:
    decision = CompactionPlanner(keep_tokens=60).plan(_request(_transcript()))

    assert len(decision.injected) == 1
    summary_message = decision.injected[0]
    assert summary_message.pinned
    # O resumo entra como mensagem do ASSISTANT: ele representa o que o próprio
    # agente condensou do seu contexto anterior, não uma instrução do usuário.
    assert summary_message.role is Role.ASSISTANT
    assert SUMMARY_PLACEHOLDER in summary_message.text
    assert summary_message.text.startswith(SUMMARY_MESSAGE_PREFIX)
    prompt = summary_message.metadata["compaction_prompt"]
    assert isinstance(prompt, str) and prompt.strip()


def test_summary_message_from_keeps_the_assistant_role_contract() -> None:
    from caio_code.domain.conversation.summary import empty_summary
    from caio_code.domain.policy.compaction import summary_message_from

    decision = CompactionPlanner(keep_tokens=60).plan(_request(_transcript()))

    message = summary_message_from(decision, empty_summary())

    assert message.role is Role.ASSISTANT
    assert message.pinned
    assert message.text.startswith(SUMMARY_MESSAGE_PREFIX)


def test_result_places_summary_after_pinned_head_and_before_verbatim_tail() -> None:
    transcript = _transcript()

    decision = CompactionPlanner(keep_tokens=60).plan(_request(transcript))
    result = decision.result(transcript)

    boundary = decision.detail["boundary"]
    assert boundary == 5
    assert result[0] is transcript[0]  # pinned task survives
    assert result[1] is decision.injected[0]
    assert result[2] is transcript[5]
    assert result[3] is transcript[6]
    assert len(result) == 4


def test_summarizer_prompt_contains_the_five_section_headings() -> None:
    decision = CompactionPlanner(keep_tokens=60).plan(_request(_transcript()))

    prompt = decision.injected[0].metadata["compaction_prompt"]

    for heading in SECTION_HEADINGS:
        assert f"## {heading}" in prompt
    for sub in WORK_STATE_SUBSECTIONS:
        assert f"### {sub}" in prompt


def test_summarizer_prompt_carries_prior_summary_instructions_on_recompaction() -> None:
    previous = empty_summary()

    decision = CompactionPlanner(keep_tokens=60).plan(
        _request(_transcript(), previous_summary=previous)
    )

    prompt = decision.injected[0].metadata["compaction_prompt"]
    assert "<prior-summary>" in prompt
    assert PRIOR_SUMMARY_INSTRUCTION in prompt
    assert previous.render() in prompt


def test_summary_allowance_shrinks_the_verbatim_tail_so_the_summary_still_fits() -> None:
    # O resumo que substitui a cabeça também é enviado, então ele sai da mesma
    # janela. Com keep_tokens igual à janela e o resumo empilhado por cima, o
    # plano estoura por construção -- foi o que invalidou 40% dos trials de
    # compactação do chapter4-main-v4. Reservar o allowance é o que torna
    # "cabe na janela" propriedade da política, e não esperança sobre o
    # tamanho da saída do modelo.
    transcript = _transcript()
    request = PolicyRequest(transcript=transcript, budget=TokenBudget(100), counter=COUNTER)
    costs = request.costs()
    allowance = 40

    naive = CompactionPlanner(keep_tokens=100).plan(request)
    reserved = CompactionPlanner(keep_tokens=100, summary_allowance_tokens=allowance).plan(request)

    # custos: [2, 26, 26, 26, 26, 26, 26] -- task pinned + seis fillers de 101 chars
    assert naive.detail["boundary"] == 4
    assert reserved.detail["boundary"] == 5

    naive_tail = sum(costs[naive.detail["boundary"] :])
    reserved_tail = sum(costs[reserved.detail["boundary"] :])
    assert naive_tail + allowance > request.budget.tokens
    assert reserved_tail + allowance <= request.budget.tokens


def test_summary_allowance_larger_than_the_window_degrades_to_the_minimal_tail() -> None:
    # Um allowance maior que a janela disponível não pode produzir budget
    # negativo: o piso em zero degrada para a cauda mínima (só a mensagem mais
    # recente sobrevive, como garante tail_boundary) em vez de quebrar.
    transcript = _transcript()
    request = PolicyRequest(
        transcript=transcript, budget=TokenBudget(30), counter=COUNTER, fixed_tokens=10
    )

    decision = CompactionPlanner(keep_tokens=30, summary_allowance_tokens=4096).plan(request)

    assert decision.detail["compacted"] is True
    assert decision.detail["boundary"] == len(transcript) - 1
    assert decision.kept_indices == (0, len(transcript) - 1)
