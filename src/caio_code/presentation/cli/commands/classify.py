"""``caio-code classify``: the smallest possible live check of the decision model.

Sends one state string and a small set of typed questions to the decision model
and prints every answer with its probabilities, confidence and token usage. With
``--provider stub`` it runs fully offline; with ``--provider typesafe`` it is the
cheapest way to confirm Jev is reachable. No secret is ever printed.

Question argument formats (each flag may repeat):

- ``--noul id=yes/no question``
- ``--choice id=question|label=description|label=description`` (at least 2 labels)
- ``--score id=question|level 0 description|level 1 description`` (at least 2 levels)
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable, Sequence
from dataclasses import replace

from caio_code.config import Settings, load_settings
from caio_code.domain.errors import ConfigurationError
from caio_code.domain.ports.decision import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionAnswers,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
)
from caio_code.infrastructure.decision.factory import build_decision_model

MIN_CHOICE_LABELS = 2
MIN_SCORE_LEVELS = 2
DECISION_PROVIDER_CHOICES: tuple[str, ...] = ("stub", "typesafe")


def _split_question_id(spec: str, *, kind: str) -> tuple[str, str, list[str]]:
    question_id, separator, rest = spec.partition("=")
    if not separator or not question_id.strip() or not rest.strip():
        msg = f"--{kind} expects 'id=question', got {spec!r}"
        raise ConfigurationError(msg)
    parts = rest.split("|")
    return question_id.strip(), parts[0].strip(), [part.strip() for part in parts[1:]]


def parse_noul(spec: str) -> tuple[str, NoulQuestion]:
    question_id, instructions, _extra = _split_question_id(spec, kind="noul")
    return question_id, NoulQuestion(instructions=instructions)


def parse_choice(spec: str) -> tuple[str, ChoiceQuestion]:
    question_id, instructions, labels = _split_question_id(spec, kind="choice")
    criteria: dict[str, str] = {}
    for label in labels:
        name, separator, description = label.partition("=")
        if not separator or not name.strip():
            msg = f"--choice labels expect 'label=description', got {label!r}"
            raise ConfigurationError(msg)
        criteria[name.strip()] = description.strip()
    if len(criteria) < MIN_CHOICE_LABELS:
        msg = f"--choice {question_id!r} needs at least {MIN_CHOICE_LABELS} labels"
        raise ConfigurationError(msg)
    return question_id, ChoiceQuestion(instructions=instructions, criteria=criteria)


def parse_score(spec: str) -> tuple[str, ScoreQuestion]:
    question_id, instructions, levels = _split_question_id(spec, kind="score")
    levels = [level for level in levels if level]
    if len(levels) < MIN_SCORE_LEVELS:
        msg = f"--score {question_id!r} needs at least {MIN_SCORE_LEVELS} ordered levels"
        raise ConfigurationError(msg)
    return question_id, ScoreQuestion(instructions=instructions, criteria=levels)


def parse_questions(args: Namespace) -> dict[str, Question]:
    """All questions from the command line, in flag order; duplicate ids are an error."""
    questions: dict[str, Question] = {}
    parsers: Sequence[tuple[str, Callable[[str], tuple[str, Question]]]] = (
        *[(spec, parse_noul) for spec in args.noul],
        *[(spec, parse_choice) for spec in args.choice],
        *[(spec, parse_score) for spec in args.score],
    )
    for spec, parser in parsers:
        question_id, question = parser(spec)
        if question_id in questions:
            msg = f"duplicate question id {question_id!r}"
            raise ConfigurationError(msg)
        questions[question_id] = question
    if not questions:
        msg = "classify needs at least one question: --noul, --choice or --score"
        raise ConfigurationError(msg)
    return questions


def _print_answers(answers: DecisionAnswers, questions: dict[str, Question]) -> None:
    for question_id in questions:
        answer = answers.answers.get(question_id)
        if isinstance(answer, NoulAnswer):
            print(f"{question_id} [noul]: p(yes)={answer.probability:.4f}")
        elif isinstance(answer, ChoiceAnswer):
            distribution = ", ".join(
                f"{label}={probability:.4f}" for label, probability in answer.probabilities.items()
            )
            print(
                f"{question_id} [choice]: {answer.choice} "
                f"(confidence={answer.confidence:.4f}; {distribution})"
            )
        elif isinstance(answer, ScoreAnswer):
            distribution = ", ".join(
                f"{level}={probability:.4f}" for level, probability in answer.probabilities.items()
            )
            print(
                f"{question_id} [score]: {answer.score:.4f} "
                f"(confidence={answer.confidence:.4f}; {distribution})"
            )
        else:
            print(f"{question_id}: no answer")


def classify_command(args: Namespace) -> int:
    settings: Settings = load_settings()
    if args.provider:
        settings = replace(settings, decision=replace(settings.decision, provider=args.provider))
    questions = parse_questions(args)
    model = build_decision_model(settings)
    answers = model.classify(args.state, questions)
    _print_answers(answers, questions)
    print(f"model: {answers.model}")
    print(
        f"usage: input_tokens={answers.usage.input_tokens} "
        f"output_tokens={answers.usage.output_tokens}"
    )
    if answers.request_id:
        print(f"request_id: {answers.request_id}")
    return 0


__all__ = ["classify_command", "parse_choice", "parse_noul", "parse_questions", "parse_score"]
