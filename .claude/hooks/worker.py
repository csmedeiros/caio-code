#!/usr/bin/env python3
"""Runs the headless consolidator behind a SessionEnd hook.

Two jobs, both best-effort:

* ``learn``  — read the transcript, extract at most three lessons, and open a
  PR that edits only skills and AGENTS/CLAUDE files.
* ``linear`` — read the transcript and post one progress comment to the card.

Nothing here may modify ``src/`` or ``tests/``: consolidation is about how the
repository is worked on, never about the code under work.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MAX_TRANSCRIPT_BYTES = 2_000
TIMEOUT_SECONDS = 900

LEARN_PROMPT = """\
You are the session consolidator for the repository at {root}.
A Claude Code session just ended; its transcript is at {transcript}.

Extract at most THREE concrete lessons about how work should be done here, and
encode them. Be strict: a lesson only counts if it would have prevented a real
mistake or saved real work. If nothing qualifies, print NO_CHANGE and stop.

Allowed files: .claude/skills/**, .claude/agents/**, CLAUDE.md, docs/**.
The per-directory AGENTS.md files are the sources; CLAUDE.md is a symlink to
AGENTS.md — never replace the symlink with a regular file.

Forbidden: src/**, tests/**, scripts/**, pyproject.toml, Makefile, .github/**.
Never touch Linear, never commit a secret, never open more than one PR.

If a change is warranted:
1. git switch -c learn/{stamp}-<slug> main
2. make the minimal edit (one lesson)
3. python -m ruff check . (best effort) and make lint if the venv exists
4. git add <files> && git commit -m "learn: <lesson in one line>"
5. git push -u origin HEAD
6. gh pr create --base main --title "learn: <lesson>" --body "<why, evidence from the transcript>"
If any step fails, stop and describe the failure; do not retry with force.

Finish with at most 10 lines: what you changed (or NO_CHANGE) and why.
"""

LINEAR_PROMPT = """\
You are the progress consolidator for the repository at {root}.
A Claude Code session just ended; its transcript is at {transcript}.

Record what actually advanced in Linear. Rules:

1. If LINEAR_API_KEY is unset, print LINEAR_SKIPPED and stop.
2. Identify the active card: read docs/linear-workflow.md, then run
   `python scripts/linear.py issues --project "$LINEAR_PROJECT_ID"` and pick the
   In Progress card matching this session's work. If none matches, create one
   with `python scripts/linear.py create --title "<feature>" --description "<scope>"`.
3. Post exactly ONE comment with `python scripts/linear.py comment --issue <ID>
   --body "..."`. Make it factual: what changed, how it was verified (exact
   commands and their result), what remains. Never claim a test passed unless the
   transcript shows it passing. Never include secrets.
4. Move the card to Done only if the work is merged into main AND documented.
   Otherwise leave it In Progress.
5. Do not edit any file in the repository.

Finish with at most 10 lines: card, action taken, anything left open.
"""


def load_payload(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def transcript_from(payload: dict, root: Path) -> Path | None:
    raw = payload.get("transcript_path") or payload.get("transcriptPath")
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_file():
        return None
    if path.stat().st_size < MAX_TRANSCRIPT_BYTES:
        return None
    return path


def run_claude(prompt: str, root: Path, allowed: list[str]) -> int:
    claude = shutil.which("claude")
    if claude is None:
        print("claude binary not found; skipping")
        return 0

    command = [claude, "-p", prompt, "--output-format", "text"]
    if allowed:
        command += ["--allowedTools", *allowed]

    env = dict(os.environ)
    env["CAIO_CODE_HOOK_DEPTH"] = "1"

    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"claude timed out after {TIMEOUT_SECONDS}s")
        return 1

    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: worker.py learn|linear <payload.json> <repo>", file=sys.stderr)
        return 2

    kind, payload_path, root_raw = argv[1], argv[2], argv[3]
    root = Path(root_raw).resolve()
    payload = load_payload(Path(payload_path))
    transcript = transcript_from(payload, root)

    if transcript is None:
        print("no transcript (missing, unreadable or too short); nothing to do")
        return 0

    if kind == "learn":
        prompt = LEARN_PROMPT.format(
            root=root,
            transcript=transcript,
            stamp=payload.get("session_id", "session")[:12],
        )
        allowed = ["Read", "Grep", "Glob", "Edit", "Write", "Bash(git:*)", "Bash(gh:*)"]
    elif kind == "linear":
        prompt = LINEAR_PROMPT.format(root=root, transcript=transcript)
        allowed = ["Read", "Grep", "Glob", "Bash(python:*)", "Bash(python3:*)"]
    else:
        print(f"unknown kind {kind!r}", file=sys.stderr)
        return 2

    return run_claude(prompt, root, allowed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))