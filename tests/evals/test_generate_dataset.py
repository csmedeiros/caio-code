"""Gerador do dataset: determinismo, ids, validação do desenho e a CLI.

O gerador é um script, não um módulo importável: ele é carregado aqui por
caminho de arquivo (registrado em ``sys.modules`` antes de executar, que é o
que ``dataclasses`` exige para resolver anotações).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from caio_code.config import EvalConfig
from caio_code.domain.errors import DatasetError
from caio_code.domain.evaluation.cases import answer_matches
from caio_code.infrastructure.datasets.codec import case_to_dict, dataset_to_dict
from caio_code.infrastructure.datasets.loader import load_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPO_ROOT / "evals" / "generate_dataset.py"
COMMITTED_DIR = REPO_ROOT / EvalConfig().dataset_dir
MODULE_NAME = "caio_code_evals_generate_dataset"

FORBIDDEN_PATTERNS = (
    r"^import time",
    r"^from time",
    r"^import uuid",
    r"^from uuid",
    r"^import datetime",
    r"^from datetime",
    r"\brandom\.(seed|choice|random|randint|randrange|shuffle|sample|choices)\(",
)


def load_generator() -> ModuleType:
    """Importa ``evals/generate_dataset.py`` como módulo, uma vez por sessão."""
    if MODULE_NAME in sys.modules:
        return sys.modules[MODULE_NAME]
    spec = importlib.util.spec_from_file_location(MODULE_NAME, GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen() -> ModuleType:
    return load_generator()


@pytest.fixture(scope="module")
def dataset(gen: ModuleType):
    return gen.build_dataset()


# ---------------------------------------------------------------------------
# Determinismo
# ---------------------------------------------------------------------------


def test_same_seed_produces_byte_identical_json(gen: ModuleType) -> None:
    first = gen.build_dataset(seed=gen.DEFAULT_SEED)
    second = gen.build_dataset(seed=gen.DEFAULT_SEED)
    assert gen.dumps(dataset_to_dict(first)) == gen.dumps(dataset_to_dict(second))
    for before, after in zip(first.cases, second.cases, strict=True):
        assert gen.dumps(case_to_dict(before)) == gen.dumps(case_to_dict(after))


def test_a_different_seed_produces_different_content(gen: ModuleType) -> None:
    base = gen.build_dataset(seed=gen.DEFAULT_SEED)
    other = gen.build_dataset(seed=gen.DEFAULT_SEED + 1)
    assert [case.id for case in base.cases] == [case.id for case in other.cases]
    differing = [
        before.id
        for before, after in zip(base.cases, other.cases, strict=True)
        if gen.dumps(case_to_dict(before)) != gen.dumps(case_to_dict(after))
    ]
    assert differing, "two seeds produced the same dataset"


def test_the_seed_is_recorded_in_the_manifest_and_in_every_case(gen: ModuleType, dataset) -> None:
    assert dataset.seed == gen.DEFAULT_SEED == EvalConfig().seed
    for case, spec in zip(dataset.cases, gen.case_specs(), strict=True):
        assert case.metadata["seed"] == gen.DEFAULT_SEED
        assert case.metadata["case_seed"] == gen.case_seed(gen.DEFAULT_SEED, spec)


def test_per_case_seeds_are_independent_of_case_order(gen: ModuleType) -> None:
    specs = gen.case_specs()
    for spec in specs:
        assert gen.case_seed(gen.DEFAULT_SEED, spec) == gen.DEFAULT_SEED + spec.index


def test_committed_files_are_the_generators_output(gen: ModuleType) -> None:
    """O que está versionado é reproduzível: ninguém editou JSON na mão."""
    fresh = gen.build_dataset(seed=gen.DEFAULT_SEED)
    assert gen.dumps(dataset_to_dict(fresh)) == (COMMITTED_DIR / "dataset.json").read_text(
        encoding="utf-8"
    )
    for case in fresh.cases:
        path = COMMITTED_DIR / f"{case.id}.json"
        assert path.is_file(), f"{path} is missing"
        assert gen.dumps(case_to_dict(case)) == path.read_text(encoding="utf-8"), (
            f"{path.name} does not match a fresh generation; regenerate the dataset"
        )


def test_serialization_sorts_keys_and_ends_with_a_newline(gen: ModuleType, dataset) -> None:
    text = gen.dumps(case_to_dict(dataset.cases[0]))
    assert text.endswith("\n")
    payload = json.loads(text)
    assert list(payload) == sorted(payload)
    assert list(payload["messages"][0]) == sorted(payload["messages"][0])


def test_the_generator_source_has_no_nondeterminism(gen: ModuleType) -> None:
    source = GENERATOR_PATH.read_text(encoding="utf-8")
    for pattern in FORBIDDEN_PATTERNS:
        assert not re.search(pattern, source, re.MULTILINE), f"generator uses {pattern!r}"
    assert "random.Random(" in source


# ---------------------------------------------------------------------------
# Identifiers and shape
# ---------------------------------------------------------------------------


def test_case_ids_slugs_and_file_names(gen: ModuleType) -> None:
    specs = gen.case_specs()
    assert len(specs) == gen.CASE_COUNT
    assert [spec.index for spec in specs] == list(range(1, len(specs) + 1))
    assert len({spec.slug for spec in specs}) == len(specs)
    assert len({spec.domain for spec in specs}) == len(specs)
    for spec in specs:
        assert spec.case_id == f"case-{spec.index:02d}-{spec.slug}"
        assert spec.file_name == f"{spec.case_id}.json"


def test_specs_respect_the_design_bounds(gen: ModuleType) -> None:
    for spec in gen.case_specs():
        assert gen.MIN_MESSAGES <= spec.message_target <= gen.MAX_MESSAGES
        assert gen.MIN_FACTS <= len(spec.facts) <= gen.MAX_FACTS
        assert gen.MIN_TODO_STEPS <= len(spec.todos) <= gen.MAX_TODO_STEPS
        assert len({fact.slug for fact in spec.facts}) == len(spec.facts)
        positions = [fact.position for fact in spec.facts]
        for position in gen.POSITIONS:
            assert positions.count(position) >= gen.MIN_FACTS_PER_POSITION, spec.case_id
        probed = [fact for fact in spec.facts if fact.probed]
        assert gen.MIN_PROBES <= len(probed) <= gen.MAX_PROBES, spec.case_id
        for fact in spec.facts:
            assert gen.MIN_ALIASES <= len(fact.aliases) <= gen.MAX_ALIASES
            assert fact.question.endswith("?")


def test_message_and_tool_call_ids_follow_the_templates(gen: ModuleType, dataset) -> None:
    for case in dataset.cases:
        for index, message in enumerate(case.messages):
            assert message.id == gen.MESSAGE_ID_TEMPLATE.format(case_id=case.id, index=index)
        calls = [call.id for message in case.messages for call in message.tool_calls]
        for position, call_id in enumerate(calls, start=1):
            assert call_id == gen.TOOL_CALL_ID_TEMPLATE.format(case_id=case.id, index=position)


def test_every_fact_answer_appears_in_its_own_message(gen: ModuleType, dataset) -> None:
    for case in dataset.cases:
        for fact in case.facts:
            carrier = case.messages[fact.message_index or 0]
            assert answer_matches(carrier.text, fact.acceptable_answers), f"{case.id} {fact.id}"


# ---------------------------------------------------------------------------
# Position arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("total", "early", "late"),
    [(60, 12, 48), (84, 17, 68), (96, 20, 77), (128, 26, 103), (140, 28, 112)],
)
def test_position_boundaries_are_the_outer_fifths(gen: ModuleType, total: int, early: int, late: int) -> None:
    assert gen.early_boundary(total) == early
    assert gen.late_boundary(total) == late
    assert gen.position_for(0, total) == "early"
    assert gen.position_for(early - 1, total) == "early"
    assert gen.position_for(early, total) == "middle"
    assert gen.position_for(late - 1, total) == "middle"
    assert gen.position_for(late, total) == "late"
    assert gen.position_for(total - 1, total) == "late"


def test_position_for_rejects_nothing_but_reports_every_band(gen: ModuleType) -> None:
    assert {gen.position_for(index, 100) for index in range(100)} == set(gen.POSITIONS)


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------


def test_unknown_output_kind_raises(gen: ModuleType) -> None:
    import random

    spec = gen.OutputSpec(kind="hologram", tool="execute", target="x", lines=10, width=40)
    with pytest.raises(DatasetError) as excinfo:
        gen.render_output(random.Random(1), spec, gen.case_specs()[0].vocabulary)
    assert "hologram" in str(excinfo.value)


def test_embedded_lines_land_where_the_spec_says(gen: ModuleType) -> None:
    import random

    spec = gen.case_specs()[0]
    output = gen.OutputSpec(
        kind="run_log",
        tool="execute",
        target="a command",
        lines=400,
        width=60,
        embedded=("MARKER the line we hide",),
        embedded_at=(0.5,),
    )
    text = gen.render_output(random.Random(3), output, spec.vocabulary)
    lines = text.splitlines()
    assert "MARKER the line we hide" in lines
    assert abs(lines.index("MARKER the line we hide") - 200) <= 2


# ---------------------------------------------------------------------------
# Validation: the generator refuses a dataset that breaks the design
# ---------------------------------------------------------------------------


def broken_specs(gen: ModuleType) -> dict[str, object]:
    """One mutation per invariant, each of which must be rejected."""
    spec = gen.case_specs()[0]
    facts = spec.facts
    return {
        "answer_absent": replace(
            spec,
            facts=(replace(facts[0], answer="an answer nobody ever wrote down"), *facts[1:]),
        ),
        "too_few_messages": replace(spec, message_target=gen.MIN_MESSAGES - 1),
        "too_many_messages": replace(spec, message_target=gen.MAX_MESSAGES + 1),
        "no_late_fact": replace(
            spec,
            facts=tuple(
                replace(fact, position="middle") if fact.position == "late" else fact
                for fact in facts
            ),
        ),
        "probe_without_question": replace(
            spec, facts=(replace(facts[0], question=""), *facts[1:])
        ),
    }


MUTATIONS = (
    "answer_absent",
    "no_late_fact",
    "probe_without_question",
    "too_few_messages",
    "too_many_messages",
)


@pytest.mark.parametrize("mutation", MUTATIONS)
def test_a_broken_spec_is_rejected_by_name(gen: ModuleType, mutation: str) -> None:
    spec = broken_specs(gen)[mutation]
    with pytest.raises(DatasetError) as excinfo:
        gen.build_case(spec, gen.DEFAULT_SEED)  # type: ignore[arg-type]
    message = str(excinfo.value)
    assert spec.case_id in message  # type: ignore[attr-defined]
    if mutation == "answer_absent":
        assert "does not appear" in message
    if mutation == "too_few_messages":
        assert "messages" in message
    if mutation == "too_many_messages":
        assert "messages" in message
    if mutation == "no_late_fact":
        assert "late" in message
    if mutation == "probe_without_question":
        assert "probe" in message.lower() or "probes" in message


def test_a_repeated_fact_slug_is_rejected_when_the_spec_is_built(gen: ModuleType) -> None:
    spec = gen.case_specs()[0]
    with pytest.raises(DatasetError) as excinfo:
        replace(spec, facts=(spec.facts[0], *spec.facts))
    assert "slug" in str(excinfo.value)


def test_a_case_cannot_be_padded_below_the_filler_floor(gen: ModuleType) -> None:
    squeezed = replace(gen.case_specs()[0], message_target=gen.MIN_MESSAGES - 20)
    with pytest.raises(DatasetError) as excinfo:
        gen.build_case(squeezed, gen.DEFAULT_SEED)
    assert "filler" in str(excinfo.value)


def test_dataset_validation_rejects_a_missing_case(gen: ModuleType) -> None:
    from caio_code.domain.evaluation.cases import EvalDataset

    specs = gen.case_specs()
    cases = tuple(gen.build_case(spec, gen.DEFAULT_SEED) for spec in specs[:-1])
    dataset = EvalDataset(name=gen.DATASET_NAME, cases=cases, seed=gen.DEFAULT_SEED)
    with pytest.raises(DatasetError) as excinfo:
        gen.validate_dataset(dataset)
    assert "cases" in str(excinfo.value)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_the_cases_and_the_manifest(gen: ModuleType, tmp_path: Path) -> None:
    out = tmp_path / "long_histories"
    assert gen.main(["--out", str(out), "--seed", str(gen.DEFAULT_SEED)]) == 0

    expected = sorted([*[spec.file_name for spec in gen.case_specs()], "dataset.json"])
    assert sorted(path.name for path in out.iterdir()) == expected

    loaded = load_dataset(out)
    assert len(loaded.cases) == gen.CASE_COUNT
    assert loaded.seed == gen.DEFAULT_SEED
    for path in out.iterdir():
        assert path.read_text(encoding="utf-8").endswith("\n")


def test_cli_dry_run_writes_nothing(gen: ModuleType, tmp_path: Path, capsys) -> None:
    out = tmp_path / "untouched"
    assert gen.main(["--out", str(out), "--dry-run"]) == 0
    assert not out.exists()
    captured = capsys.readouterr()
    assert "case-01-api-service-debug" in captured.out


def test_cli_honours_a_custom_seed(gen: ModuleType, tmp_path: Path) -> None:
    out = tmp_path / "seeded"
    assert gen.main(["--out", str(out), "--seed", "7"]) == 0
    manifest = json.loads((out / "dataset.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == 7
    case = json.loads((out / "case-01-api-service-debug.json").read_text(encoding="utf-8"))
    assert case["metadata"]["seed"] == 7
    assert load_dataset(out).cases[0].char_count == case["metadata"]["char_count"]
