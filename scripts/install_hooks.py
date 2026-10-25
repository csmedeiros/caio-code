#!/usr/bin/env python3
"""Point git at .githooks/ and make the hooks executable where possible."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    hooks_dir = ROOT / ".githooks"
    if not hooks_dir.is_dir():
        print(f"missing {hooks_dir}", file=sys.stderr)
        return 1

    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=ROOT,
        check=True,
    )

    if os.name != "nt":
        for hook in hooks_dir.iterdir():
            if hook.is_file() and not hook.name.endswith(".md"):
                mode = hook.stat().st_mode
                hook.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    else:
        print(
            "Windows: core.hooksPath set. Git for Windows executes these hooks "
            "through its bundled sh; if `make setup` skipped it, run git-bash once.",
            file=sys.stderr,
        )

    print("git hooks installed (.githooks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())