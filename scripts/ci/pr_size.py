#!/usr/bin/env python3
"""Keep pull requests reviewable: fail above MAX files, warn below MIN."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIN_FILES = 5
MAX_FILES = 20


def changed(base: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--max", type=int, default=MAX_FILES)
    parser.add_argument("--min", type=int, default=MIN_FILES)
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args(argv)

    files = changed(args.base)
    count = len(files)
    print(f"{count} file(s) changed against {args.base}")

    if count == 0:
        print("empty diff: nothing to review", file=sys.stderr)
        return 0

    if count > args.max:
        print(
            f"PR too large: {count} > {args.max}. Split it into stacked PRs.",
            file=sys.stderr,
        )
        return 0 if args.warn_only else 1

    if count < args.min:
        print(
            f"note: {count} < {args.min} files. Fine for a fix; a feature "
            "usually carries its test and its AGENTS.md update.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())