"""Stores de arquivo: JSONL de resultados e envelope de transcrições."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caio_code.domain.conversation.messages import Message, Role, ToolCall, Transcript
from caio_code.domain.errors import StorageError
from caio_code.domain.ports.storage import ResultRecord, ResultStore, TranscriptStore
from caio_code.infrastructure.persistence.jsonl import JsonlResultStore, JsonTranscriptStore


@pytest.fixture()
def results(tmp_path: Path) -> JsonlResultStore:
    return JsonlResultStore(tmp_path / "results")


@pytest.fixture()
def transcripts(tmp_path: Path) -> JsonTranscriptStore:
    return JsonTranscriptStore(tmp_path / "transcripts")


def sample_transcript() -> Transcript:
    return Transcript.of(
        [
            Message(id="m1", role=Role.USER, text="task", pinned=True),
            Message(
                id="m2",
                role=Role.ASSISTANT,
                tool_calls=(ToolCall(id="t1", name="grep", arguments='{"pattern": "x"}'),),
                metadata={"edits": ("a", "b")},
            ),
            Message(id="m3", role=Role.TOOL, text="hit", tool_call_id="t1", name="grep"),
        ]
    )


# ---------------------------------------------------------------- ResultStore


def test_result_store_implements_the_port(results: JsonlResultStore) -> None:
    assert isinstance(results, ResultStore)


def test_append_then_read_keeps_write_order(results: JsonlResultStore) -> None:
    results.append("run1", ResultRecord(kind="metric", payload={"tokens": 10}))
    results.append("run1", ResultRecord(kind="metric", payload={"tokens": 20}))
    records = results.read("run1")
    assert [record.payload["tokens"] for record in records] == [10, 20]
    assert [record.kind for record in records] == ["metric", "metric"]


def test_append_flushes_to_disk(results: JsonlResultStore) -> None:
    results.append("run1", ResultRecord(kind="x"))
    lines = results.path_of("run1").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"kind": "x", "payload": {}}


def test_path_of_is_root_run_id_jsonl(results: JsonlResultStore, tmp_path: Path) -> None:
    assert results.path_of("run1") == tmp_path / "results" / "run1.jsonl"


def test_read_missing_run_raises_naming_it(results: JsonlResultStore) -> None:
    with pytest.raises(StorageError, match="no result file for run 'ghost'"):
        results.read("ghost")


def test_corrupt_line_raises_naming_file_and_line(results: JsonlResultStore) -> None:
    results.append("run1", ResultRecord(kind="x"))
    results.append("run1", ResultRecord(kind="y"))
    path = results.path_of("run1")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{corrupt\n")
    with pytest.raises(StorageError) as excinfo:
        results.read("run1")
    message = str(excinfo.value)
    assert str(path) in message
    assert ":3:" in message


def test_record_without_kind_raises_naming_the_field(results: JsonlResultStore) -> None:
    path = results.path_of("run1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"payload": {}}\n', encoding="utf-8")
    with pytest.raises(StorageError, match="field 'kind'"):
        results.read("run1")


def test_unsafe_run_id_is_refused(results: JsonlResultStore) -> None:
    with pytest.raises(StorageError, match=r"got '\.\./evil'"):
        results.path_of("../evil")


def test_unserializable_payload_raises(results: JsonlResultStore) -> None:
    with pytest.raises(StorageError, match="not JSON-serializable"):
        results.append("run1", ResultRecord(kind="x", payload={"set": {1, 2}}))


# ------------------------------------------------------------ TranscriptStore


def test_transcript_store_implements_the_port(transcripts: JsonTranscriptStore) -> None:
    assert isinstance(transcripts, TranscriptStore)


def test_transcript_round_trip_preserves_pinned_tool_calls_metadata(
    transcripts: JsonTranscriptStore,
) -> None:
    original = sample_transcript()
    path = transcripts.save("sess-1", original)
    assert path.name == "sess-1.json"
    restored = transcripts.load("sess-1")
    assert len(restored) == 3
    assert restored[0].pinned is True
    assert restored[1].tool_calls == original[1].tool_calls
    assert isinstance(restored[1].tool_calls, tuple)
    assert restored[1].metadata["edits"] == ["a", "b"]
    assert restored[2].tool_call_id == "t1"


def test_save_leaves_no_temporary_file(transcripts: JsonTranscriptStore) -> None:
    transcripts.save("sess-1", sample_transcript())
    assert not list(transcripts.path_of("sess-1").parent.glob("*.tmp"))


def test_load_missing_session_raises_naming_it(transcripts: JsonTranscriptStore) -> None:
    with pytest.raises(StorageError, match="no transcript for session 'ghost'"):
        transcripts.load("ghost")


def test_load_corrupt_file_raises_naming_the_file(transcripts: JsonTranscriptStore) -> None:
    path = transcripts.save("sess-1", sample_transcript())
    path.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(StorageError, match="invalid JSON"):
        transcripts.load("sess-1")


def test_load_unknown_version_raises(transcripts: JsonTranscriptStore) -> None:
    path = transcripts.save("sess-1", sample_transcript())
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["version"] = 7
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(StorageError, match="unknown envelope version: 7"):
        transcripts.load("sess-1")


def test_list_sessions_is_sorted(transcripts: JsonTranscriptStore) -> None:
    for session in ("sess-b", "sess-a", "sess-c"):
        transcripts.save(session, sample_transcript())
    assert list(transcripts.list_sessions()) == ["sess-a", "sess-b", "sess-c"]


def test_list_sessions_on_empty_root_is_empty(tmp_path: Path) -> None:
    store = JsonTranscriptStore(tmp_path / "absent")
    assert list(store.list_sessions()) == []


def test_unsafe_session_id_is_refused(transcripts: JsonTranscriptStore) -> None:
    with pytest.raises(StorageError, match="bare filename"):
        transcripts.save("../evil", sample_transcript())


def test_load_with_session_id_returns_stored_id(transcripts: JsonTranscriptStore) -> None:
    transcripts.save("sess-9", sample_transcript())
    stored_id, transcript = transcripts.load_with_session_id("sess-9")
    assert stored_id == "sess-9"
    assert len(transcript) == 3
