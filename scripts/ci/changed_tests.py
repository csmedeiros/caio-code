#!/usr/bin/env python3
"""Map a diff to the tests that cover it.

The mapping is intentionally conservative: a change to shared infrastructure
(``pyproject.toml``, ``Makefile``, ``scripts/ci/``) runs the whole suite, and a
change to a package runs that package's tests. When in doubt, run more.

Usage:
    python scripts/ci/changed_tests.py              # list targets
    python scripts/ci/changed_tests.py --json       # for a GitHub Actions matrix
    python scripts/ci/changed_tests.py --run        # run pytest on them
    python scripts/ci/changed_tests.py --base origin/main
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = Path("src/caio_code")
TESTS = Path("tests")

GLOBAL_PATHS = {
    "pyproject.toml",
    "Makefile",
    ".github",
    "scripts/ci",
}


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else ""


def default_base() -> str:
    for candidate in ("origin/main", "main"):
        if git("rev-parse", "--verify", "--quiet", candidate).strip():
            return candidate
    return "HEAD~1"


def changed_files(base: str) -> list[str]:
    files: set[str] = set()
    for args in (
        ("diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"),
        ("diff", "--name-only", "--diff-filter=ACMR", base),
        ("diff", "--name-only", "--cached"),
        ("ls-files", "--others", "--exclude-standard"),
    ):
        files.update(line.strip() for line in git(*args).splitlines() if line.strip())
    return sorted(files)


def targets_for(files: list[str]) -> list[str]:
    if not files:
        return []

    targets: set[str] = set()
    for path in files:
        if path in GLOBAL_PATHS or path.startswith(("scripts/ci/", ".github/")):
            return [str(TESTS)]

        if path.startswith(f"{SRC}/"):
            remainder = path[len(str(SRC)) + 1 :]
            parts = remainder.split("/")
            module = parts[0] if len(parts) > 1 else ""
            if module.endswith(".py"):
                targets.add(str(TESTS))
            else:
                candidate = TESTS / module
                targets.add(str(candidate) if candidate.is_dir() else str(TESTS))
            continue

        if path.startswith(f"{TESTS}/"):
            parts = path.split("/")
            if len(parts) >= 3:
                candidate = Path("/".join(parts[:2]))
                targets.add(str(candidate) if candidate.is_dir() else str(TESTS))
            else:
                targets.add(path)
            continue

        if path.startswith("scripts/"):
            candidate = TESTS / "scripts"
            targets.add(str(candidate) if candidate.is_dir() else str(TESTS))
            continue

        if path.startswith(".claude/"):
            targets.add(str(TESTS))
            continue

    return sorted(targets) or []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)

    base = args.base or default_base()
    files = changed_files(base)
    targets = targets_for(files)

    if args.json:
        print(json.dumps({"base": base, "changed": files, "targets": targets}))
    elif not args.run:
        print("\n".join(targets) if targets else "no tests selected")

    if args.run:
        if not targets:
            print(f"nothing to test against {base}", file=sys.stderr)
            return 0
        print(f"pytest {' '.join(targets)}", file=sys.stderr)
        return subprocess.run(
            [sys.executable, "-m", "pytest", *targets], cwd=ROOT, check=False
        ).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())