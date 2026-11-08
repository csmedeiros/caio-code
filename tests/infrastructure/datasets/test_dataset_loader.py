"""Loader e estatísticas do dataset: diretórios, limite e a tabela do Capítulo 4."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caio_code.config import EvalConfig, WindowConfig
from caio_code.domain.conversation.messages import Message, Role
from caio_code.domain.errors import DatasetError
from caio_code.domain.evaluation.cases import CriticalFact, EvalDataset, HistoryCase, Probe
from caio_code.infrastructure.datasets.codec import case_to_dict, dataset_to_dict
from caio_code.infrastructure.datasets.loader import (
    CASE_GLOB,
    MANIFEST_NAME,
    case_ids,
    describe,
    describe_case,
    format_stats,
    largest_tool_output,
    load_dataset,
    validate_positions,
)
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED_DIR = REPO_ROOT / EvalConfig().dataset_dir


def tiny_case(case_id: str = "case-90-tiny", *, positions: tuple[str, ...] = ("early", "middle", "late")) -> HistoryCase:
    """Um caso mínimo, com um fato por posição pedida."""
    messages = tuple(
        Message(id=f"{case_id}-m{index:03d}", role=Role.USER, text=f"turn {index}")
        for index in range(len(positions) + 2)
    )
    facts = tuple(
        CriticalFact(
            id=f"{case_id}-f{index:02d}",
            statement=f"fact {index}",
            answer=f"answer-{index}",
            aliases=(f"alias-{index}",),
            position=position,  # type: ignore[arg-type]
            message_index=index + 1,
        )
        for index, position in enumerate(positions)
    )
    return HistoryCase(
        id=case_id,
        description="caso mínimo",
        task="task",
        messages=messages,
        facts=facts,
        probes=(
            Probe(
                id=f"{case_id}-p00",
                fact_id=facts[0].id,
                question="What is the answer?",
                expected="answer-0",
            ),
        ),
    )


def write_dataset(directory: Path, cases: tuple[HistoryCase, ...], *, manifest: bool = True) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for case in cases:
        path = directory / f"{case.id}.json"
        path.write_text(json.dumps(case_to_dict(case), sort_keys=True) + "\n", encoding="utf-8")
    if manifest:
        dataset = EvalDataset(name="tiny", cases=cases, seed=20261031, generator="tests")
        (directory / MANIFEST_NAME).write_text(
            json.dumps(dataset_to_dict(dataset), sort_keys=True) + "\n", encoding="utf-8"
        )


def test_committed_dataset_loads_with_its_manifest() -> None:
    dataset = load_dataset(COMMITTED_DIR)
    assert dataset.name == "long_histories"
    assert dataset.seed == EvalConfig().seed
    assert dataset.generator.startswith("evals/generate_dataset.py")
    assert len(dataset.cases) == EvalConfig().max_cases
    assert case_ids(dataset) == tuple(sorted(case_ids(dataset)))


def test_committed_case_files_match_the_glob() -> None:
    files = sorted(path.name for path in COMMITTED_DIR.glob(CASE_GLOB))
    assert len(files) == EvalConfig().max_cases
    assert all(name.endswith(".json") for name in files)
    assert (COMMITTED_DIR / MANIFEST_NAME).is_file()


def test_limit_keeps_the_first_cases_in_sorted_order() -> None:
    dataset = load_dataset(COMMITTED_DIR, limit=2)
    assert len(dataset.cases) == 2
    assert dataset.cases[0].id == load_dataset(COMMITTED_DIR).cases[0].id


def test_missing_directory_raises() -> None:
    with pytest.raises(DatasetError) as excinfo:
        load_dataset(Path("evals/datasets/does-not-exist"))
    assert "does not exist" in str(excinfo.value)


def test_empty_directory_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DatasetError) as excinfo:
        load_dataset(empty)
    assert CASE_GLOB in str(excinfo.value)


def test_directory_without_a_manifest_still_loads(tmp_path: Path) -> None:
    directory = tmp_path / "no-manifest"
    write_dataset(directory, (tiny_case(),), manifest=False)
    dataset = load_dataset(directory)
    assert dataset.name == "no-manifest"
    assert len(dataset.cases) == 1


def test_corrupt_case_file_names_the_file(tmp_path: Path) -> None:
    directory = tmp_path / "corrupt"
    write_dataset(directory, (tiny_case(),))
    (directory / "case-90-tiny.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(DatasetError) as excinfo:
        load_dataset(directory)
    assert "case-90-tiny.json" in str(excinfo.value)


def test_invalid_case_file_names_the_field(tmp_path: Path) -> None:
    directory = tmp_path / "invalid"
    write_dataset(directory, (tiny_case(),))
    payload = case_to_dict(tiny_case())
    payload["facts"][0]["position"] = "sideways"
    (directory / "case-90-tiny.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetError) as excinfo:
        load_dataset(directory)
    assert "position" in str(excinfo.value)


def test_manifest_disagreeing_with_the_files_raises(tmp_path: Path) -> None:
    directory = tmp_path / "mismatch"
    write_dataset(directory, (tiny_case(),))
    manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["cases"] = ["case-90-tiny", "case-91-ghost"]
    (directory / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DatasetError) as excinfo:
        load_dataset(directory)
    assert "case-91-ghost" in str(excinfo.value)


def test_non_positive_limit_raises(tmp_path: Path) -> None:
    directory = tmp_path / "limited"
    write_dataset(directory, (tiny_case(),))
    with pytest.raises(DatasetError) as excinfo:
        load_dataset(directory, limit=0)
    assert "limit" in str(excinfo.value)


def test_describe_counts_what_the_counter_counts() -> None:
    dataset = load_dataset(COMMITTED_DIR)
    stats = describe(dataset)
    counter = CharProxyTokenCounter()

    assert stats.window_tokens == WindowConfig().tokens
    assert stats.counter_name == counter.name
    assert stats.case_count == len(dataset.cases)
    for case, case_stats in zip(dataset.cases, stats.cases, strict=True):
        assert case_stats.case_id == case.id
        assert case_stats.messages == len(case.messages)
        assert case_stats.chars == case.char_count
        assert case_stats.proxy_tokens == counter.count_transcript(case.transcript)
        assert case_stats.probes == len(case.probes)
        assert case_stats.total_facts == len(case.facts)
        assert sum(case_stats.facts_by_position.values()) == len(case.facts)
        assert case_stats.tool_results == sum(
            1 for message in case.messages if message.is_tool_result()
        )
        assert case_stats.pinned_messages == len(case.transcript.pinned_indices())
    assert stats.total_proxy_tokens == counter.count_messages(
        [message for case in dataset.cases for message in case.messages]
    )


def test_describe_reports_the_largest_tool_output() -> None:
    dataset = load_dataset(COMMITTED_DIR)
    stats = describe(dataset)
    for case, case_stats in zip(dataset.cases, stats.cases, strict=True):
        texts = [m.text for m in case.messages if m.is_tool_result()]
        assert case_stats.largest_tool_output is not None
        assert case_stats.largest_tool_output.chars == max(len(text) for text in texts)
        assert largest_tool_output(case) == case_stats.largest_tool_output


def test_describe_uses_the_window_it_is_given() -> None:
    dataset = load_dataset(COMMITTED_DIR)
    stats = describe(dataset, window_tokens=1_000)
    assert stats.window_tokens == 1_000
    assert stats.cases[0].window_multiples == pytest.approx(
        stats.cases[0].proxy_tokens / 1_000, abs=0.01
    )


def test_describe_rejects_a_negative_window() -> None:
    dataset = load_dataset(COMMITTED_DIR)
    with pytest.raises(DatasetError) as excinfo:
        describe(dataset, window_tokens=-1)
    assert "window_tokens" in str(excinfo.value)


def test_describe_without_a_window_uses_the_configured_one() -> None:
    stats = describe(load_dataset(COMMITTED_DIR))
    assert stats.window_tokens == WindowConfig().tokens


def test_describe_case_of_a_case_without_tool_results() -> None:
    stats = describe_case(tiny_case(), window_tokens=WindowConfig().tokens)
    assert stats.tool_results == 0
    assert stats.largest_tool_output is None
    assert stats.facts_by_position == {"early": 1, "middle": 1, "late": 1}


def test_format_stats_has_one_row_per_case_and_a_total() -> None:
    stats = describe(load_dataset(COMMITTED_DIR))
    table = format_stats(stats)
    lines = table.splitlines()
    assert lines[0].startswith("dataset 'long_histories'")
    assert "char_proxy" in lines[1]
    for case in stats.cases:
        assert any(line.startswith(case.case_id) for line in lines)
    assert any(line.startswith("TOTAL") for line in lines)
    assert "window multiples" in lines[-1]


def test_validate_positions_accepts_the_committed_dataset() -> None:
    validate_positions(load_dataset(COMMITTED_DIR).cases)


def test_validate_positions_rejects_a_case_without_a_late_fact() -> None:
    case = tiny_case(positions=("early", "middle"))
    with pytest.raises(DatasetError) as excinfo:
        validate_positions((case,))
    assert "late" in str(excinfo.value)
