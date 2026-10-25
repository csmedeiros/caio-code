#!/usr/bin/env python3
"""Create a stacked branch or open the PR for the current branch.

Stacking is plain git: each PR targets the branch below it, and the first one
targets `main`. Merging happens bottom-up.

    python scripts/ci/open_pr.py --stack --name window --card CM-31
    python scripts/ci/open_pr.py --card CM-31
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, check=check
    )


def current_branch() -> str:
    return run("git", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def branch_exists(name: str) -> bool:
    return bool(run("git", "rev-parse", "--verify", "--quiet", name, check=False).stdout.strip())


def stack(name: str, card: str, base: str) -> int:
    slug = f"feat/{card.lower()}-{name}"
    if branch_exists(slug):
        print(f"branch {slug} already exists", file=sys.stderr)
        return 1
    run("git", "switch", "-c", slug, base)
    print(f"created {slug} from {base}")
    print(f"next: commit your changes, then run `make pr CARD={card}`")
    return 0


def open_pr(card: str, title: str | None, base: str | None) -> int:
    branch = current_branch()
    if branch in {"main", "master"}:
        print("refusing to open a PR from main", file=sys.stderr)
        return 1

    resolved_base = base or run(
        "git", "config", f"branch.{branch}.merge", check=False
    ).stdout.strip().removeprefix("refs/heads/") or "main"

    ahead = run("git", "rev-list", "--count", f"{resolved_base}..HEAD").stdout.strip()
    if ahead in {"", "0"}:
        print(f"no commits ahead of {resolved_base}; commit first", file=sys.stderr)
        return 1

    run("git", "push", "-u", "origin", branch)
    body = (
        f"Linear: {card}\n\n"
        "## What changed\n\n## How it was verified\n\n"
        "- [ ] `make check` passes\n"
        "- [ ] tests added or updated for the changed module\n"
        "- [ ] `AGENTS.md`/`CLAUDE.md` updated if the layout changed\n"
        "- [ ] Linear card updated with a progress comment\n"
        "- [ ] diff has between 5 and 20 files\n"
    )
    result = run(
        "gh",
        "pr",
        "create",
        "--base",
        resolved_base,
        "--title",
        title or f"{card}: {branch}",
        "--body",
        body,
        check=False,
    )
    print(result.stdout or result.stderr)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card", required=True)
    parser.add_argument("--stack", action="store_true")
    parser.add_argument("--name")
    parser.add_argument("--base")
    parser.add_argument("--title")
    args = parser.parse_args(argv)

    if args.stack:
        if not args.name:
            parser.error("--stack requires --name")
        return stack(args.name, args.card, args.base or "main")
    return open_pr(args.card, args.title, args.base)


if __name__ == "__main__":
    raise SystemExit(main())