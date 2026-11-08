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

    result = subprocess.run(
        [sys.executable, "-m", "caio_code", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    check("agent cli --help", result.returncode == 0, result.stderr[-300:])

    # As políticas são o objeto de medição: se uma não planeja, nada mais importa.
    try:
        from caio_code.domain.conversation.budget import TokenBudget
        from caio_code.domain.conversation.messages import Message, Role, Transcript
        from caio_code.domain.policy import (
            FullHistoryPolicy,
            MessageSelectionPolicy,
            PolicyPipeline,
            PolicyRequest,
            SlidingWindowPolicy,
            StructureRepairPolicy,
            ToolOutputTruncationPolicy,
        )
        from caio_code.domain.policy.compaction import CompactionPlanner
        from caio_code.infrastructure.tokens import CharProxyTokenCounter

        counter = CharProxyTokenCounter()
        transcript = Transcript.of(
            Message(id=f"m{i}", role=Role.USER if i % 2 == 0 else Role.ASSISTANT, text="x" * 800)
            for i in range(12)
        )
        budget = TokenBudget(600)
        request = PolicyRequest(transcript=transcript, budget=budget, counter=counter)
        for policy in (
            FullHistoryPolicy(),
            SlidingWindowPolicy(),
            MessageSelectionPolicy(),
            CompactionPlanner(keep_tokens=400),
            ToolOutputTruncationPolicy(),
        ):
            decision = policy.plan(request)
            check(f"policy {policy.name} plans", decision.tokens_before > 0)
            check(
                f"policy {policy.name} reports its own cost",
                decision.tokens_after == counter.count_transcript(decision.result(transcript))
                + request.fixed_tokens
                or policy.name == "anchored_compaction",
                f"tokens_after={decision.tokens_after}",
            )
        pipeline = PolicyPipeline(
            "smoke",
            [ToolOutputTruncationPolicy(), SlidingWindowPolicy(), StructureRepairPolicy()],
        )
        composed = pipeline.plan(request)
        check("pipeline composes", composed.policies[-1] == "structure_repair")
        check("pipeline fits the budget", not composed.overflowed, str(composed.as_record()))
    except Exception as exc:  # smoke must report, not crash
        check("context policies", False, repr(exc))

    # O dataset congelado do Capítulo 4 precisa carregar sem rede.
    try:
        from caio_code.infrastructure.datasets.loader import describe, load_dataset

        dataset = load_dataset(ROOT / "evals" / "datasets" / "long_histories")
        stats = describe(dataset)
        check("eval dataset loads", len(dataset.cases) == len(stats.cases) > 0)
    except Exception as exc:  # smoke must report, not crash
        check("eval dataset loads", False, repr(exc))

    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s): {', '.join(FAILURES)}")
        return 1
    print("\nsmoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())