"""File-backed stores: JSONL for experiment results, JSON for transcripts.

``JsonlResultStore`` appends one JSON object per line and fsyncs on every
append, so a crash keeps the records already written. ``JsonTranscriptStore``
writes the whole envelope atomically (temporary file + ``os.replace``) through
:mod:`caio_code.infrastructure.persistence.codec`. Both name the offending
value — file, line number, session id — in every ``StorageError``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from caio_code.domain.conversation.messages import Transcript
from caio_code.domain.errors import StorageError
from caio_code.domain.ports.storage import ResultRecord
from caio_code.infrastructure.persistence.codec import (
    envelope_session_id,
    transcript_from_dict,
    transcript_from_json,
    transcript_to_json,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
"""A run/session id must be a bare filename: no separators, no dots-only names."""

_TRANSCRIPT_SUFFIX = ".json"
_RESULT_SUFFIX = ".jsonl"


def _check_id(kind: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.match(value) or value in {".", ".."}:
        msg = f"{kind} must be a bare filename matching {_SAFE_ID.pattern}, got {value!r}"
        raise StorageError(msg)
    return value


class JsonlResultStore:
    """One ``<run_id>.jsonl`` file per experiment run."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def path_of(self, run_id: str) -> Path:
        """Where a run's records live."""
        _check_id("run_id", run_id)
        return self._root / f"{run_id}{_RESULT_SUFFIX}"

    def append(self, run_id: str, record: ResultRecord) -> None:
        """Append one record, flushing and fsyncing so a crash keeps it."""
        path = self.path_of(run_id)
        try:
            line = json.dumps(
                {"kind": record.kind, "payload": record.payload}, ensure_ascii=False
            )
        except (TypeError, ValueError) as exc:
            msg = f"record for run {run_id!r} is not JSON-serializable: {exc}"
            raise StorageError(msg) from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
            handle.flush()
            os.fsync(handle.fileno())

    def read(self, run_id: str) -> Sequence[ResultRecord]:
        """Every record of a run, in write order.

        Raises ``StorageError`` naming the file and line number on a corrupt
        line, and when the run has no file at all.
        """
        path = self.path_of(run_id)
        if not path.is_file():
            msg = f"no result file for run {run_id!r}: expected {str(path)!r}"
            raise StorageError(msg)
        records: list[ResultRecord] = []
        with path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    raw: Any = json.loads(line)
                except json.JSONDecodeError as exc:
                    msg = f"{path}:{lineno}: invalid JSON: {exc}"
                    raise StorageError(msg) from exc
                records.append(_record_from(raw, path, lineno))
        return records


def _record_from(raw: Any, path: Path, lineno: int) -> ResultRecord:
    where = f"{path}:{lineno}"
    if not isinstance(raw, dict):
        msg = f"{where}: record must be an object, got {type(raw).__name__}"
        raise StorageError(msg)
    kind = raw.get("kind")
    if not isinstance(kind, str):
        msg = f"{where}: field 'kind' must be a string, got {kind!r}"
        raise StorageError(msg)
    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        msg = f"{where}: field 'payload' must be an object, got {payload!r}"
        raise StorageError(msg)
    return ResultRecord(kind=kind, payload=payload)


class JsonTranscriptStore:
    """One ``<session_id>.json`` envelope per session."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def path_of(self, session_id: str) -> Path:
        _check_id("session_id", session_id)
        return self._root / f"{session_id}{_TRANSCRIPT_SUFFIX}"

    def save(self, session_id: str, transcript: Transcript) -> Path:
        """Persist a transcript atomically and return where it went."""
        path = self.path_of(session_id)
        text = transcript_to_json(transcript, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return path

    def load(self, session_id: str) -> Transcript:
        """Load a transcript; raises ``StorageError`` when absent or corrupt."""
        path = self.path_of(session_id)
        if not path.is_file():
            msg = f"no transcript for session {session_id!r}: expected {str(path)!r}"
            raise StorageError(msg)
        transcript = transcript_from_json(path.read_text(encoding="utf-8"), source=str(path))
        return transcript

    def load_with_session_id(self, session_id: str) -> tuple[str, Transcript]:
        """Like :meth:`load`, plus the ``session_id`` recorded in the envelope."""
        path = self.path_of(session_id)
        if not path.is_file():
            msg = f"no transcript for session {session_id!r}: expected {str(path)!r}"
            raise StorageError(msg)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            msg = f"{path}: invalid JSON: {exc}"
            raise StorageError(msg) from exc
        return envelope_session_id(raw), transcript_from_dict(raw)

    def list_sessions(self) -> Sequence[str]:
        """Known session ids, sorted."""
        if not self._root.is_dir():
            return []
        return sorted(path.stem for path in self._root.glob(f"*{_TRANSCRIPT_SUFFIX}"))


__all__ = ["JsonTranscriptStore", "JsonlResultStore"]
