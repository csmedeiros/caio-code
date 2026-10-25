#!/usr/bin/env python3
"""Offline smoke test, run on Linux, macOS and Windows by CI.

Today it checks that the repository is healthy and that the package imports.
Once `caio_code.cli` exists, the last step also runs the agent end to end with
the stub provider — no network, no API key.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"ok   {label}")
    else:
        print(f"FAIL {label}{': ' + detail if detail else ''}")
        FAILURES.append(label)


def main() -> int:
    print(f"smoke: {sys.platform} / python {sys.version.split()[0]}")

    check("Makefile present", (ROOT / "Makefile").is_file())
    check("pyproject present", (ROOT / "pyproject.toml").is_file())

    for rel in (".", "src", "tests", "scripts", "docs", ".claude"):
        agents = ROOT / rel / "AGENTS.md"
        claude = ROOT / rel / "CLAUDE.md"
        check(
            f"{rel}/AGENTS.md",
            agents.is_file() and claude.is_symlink(),
            "missing AGENTS.md or CLAUDE.md symlink",
        )

    skills = sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))
    check("skills found", len(skills) >= 5, f"{len(skills)} found")
    for skill in skills:
        text = skill.read_text(encoding="utf-8")
        check(
            f"skill {skill.parent.name}",
            bool(re.match(r"\A---\n.*?name:.*?\n.*?description:.*?\n---", text, re.S)),
            "invalid frontmatter",
        )

    sys.path.insert(0, str(ROOT / "src"))
    try:
        import caio_code

        check("import caio_code", bool(caio_code.__version__))
    except Exception as exc:  # smoke must report, not crash
        check("import caio_code", False, repr(exc))

    cli = ROOT / "src" / "caio_code" / "cli.py"
    if cli.is_file():
        result = subprocess.run(
            [sys.executable, "-m", "caio_code", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        check("agent cli --help", result.returncode == 0, result.stderr[-300:])
    else:
        print("skip agent cli --help (cli.py not written yet)")

    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s): {', '.join(FAILURES)}")
        return 1
    print("\nsmoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())