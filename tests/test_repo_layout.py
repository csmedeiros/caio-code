"""Repository invariants.

These tests do not exercise the agent. They protect the conventions that the rest of the
repository depends on (AGENTS.md + CLAUDE.md symlink per documented directory, skill
frontmatter and routing, FEATURE_TREE.md, importable package), so that a broken convention
fails in CI instead of silently rotting.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOC_DIRS = [
    ".",
    "src",
    "src/caio_code",
    "tests",
    "scripts",
    "docs",
    ".claude",
    "evals",
    "datagen",
    # domain
    "src/caio_code/domain",
    "src/caio_code/domain/conversation",
    "src/caio_code/domain/evaluation",
    "src/caio_code/domain/policy",
    "src/caio_code/domain/ports",
    "src/caio_code/domain/todo",
    "src/caio_code/domain/usage",
    # application
    "src/caio_code/application",
    "src/caio_code/application/agent",
    "src/caio_code/application/compaction",
    "src/caio_code/application/evaluation",
    "src/caio_code/application/experiment",
    "src/caio_code/application/guardrails",
    "src/caio_code/application/metrics",
    "src/caio_code/application/selection",
    "src/caio_code/application/todos",
    # infrastructure
    "src/caio_code/infrastructure",
    "src/caio_code/infrastructure/datasets",
    "src/caio_code/infrastructure/llm",
    "src/caio_code/infrastructure/mappers",
    "src/caio_code/infrastructure/middleware",
    "src/caio_code/infrastructure/observability",
    "src/caio_code/infrastructure/persistence",
    "src/caio_code/infrastructure/pricing",
    "src/caio_code/infrastructure/tokens",
    "src/caio_code/infrastructure/tools",
    # presentation
    "src/caio_code/presentation",
    "src/caio_code/presentation/cli",
    "src/caio_code/presentation/cli/commands",
    "src/caio_code/presentation/tui",
    "src/caio_code/presentation/tui/driver",
    "src/caio_code/presentation/tui/widgets",
    # tests
    "tests/application",
    "tests/application/agent",
    "tests/application/compaction",
    "tests/application/evaluation",
    "tests/application/experiment",
    "tests/application/guardrails",
    "tests/application/metrics",
    "tests/application/selection",
    "tests/application/todos",
    "tests/context",
    "tests/domain",
    "tests/domain/conversation",
    "tests/domain/evaluation",
    "tests/domain/policy",
    "tests/datagen",
    "tests/evals",
    "tests/harness",
    "tests/infrastructure",
    "tests/infrastructure/datasets",
    "tests/infrastructure/llm",
    "tests/infrastructure/mappers",
    "tests/infrastructure/middleware",
    "tests/infrastructure/observability",
    "tests/infrastructure/persistence",
    "tests/infrastructure/pricing",
    "tests/infrastructure/tools",
    "tests/presentation",
    "tests/presentation/cli",
    "tests/presentation/tui",
    "tests/presentation/tui/driver",
    "tests/providers",
    "tests/scripts",
    "tests/state",
    "tests/tools",
]

SKILL_DIRS = sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    assert match, f"{path} has no YAML frontmatter"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def test_every_documented_directory_has_agents_and_claude() -> None:
    for rel in DOC_DIRS:
        directory = ROOT / rel
        agents = directory / "AGENTS.md"
        claude = directory / "CLAUDE.md"
        assert agents.is_file(), f"{rel}/AGENTS.md is missing"
        assert claude.is_symlink(), f"{rel}/CLAUDE.md must be a symlink to AGENTS.md"
        assert claude.resolve() == agents.resolve(), f"{rel}/CLAUDE.md points elsewhere"


def test_skills_have_name_and_description() -> None:
    assert SKILL_DIRS, "no skills found"
    for skill in SKILL_DIRS:
        fields = _frontmatter(skill)
        assert fields.get("name"), f"{skill} has no name"
        assert fields["name"] == skill.parent.name, (
            f"{skill}: name {fields['name']!r} does not match directory"
        )
        assert len(fields.get("description", "")) >= 40, (
            f"{skill}: description too short to route on"
        )


def test_router_skill_lists_every_other_skill() -> None:
    router = (ROOT / ".claude" / "skills" / "tcc" / "SKILL.md").read_text(encoding="utf-8")
    for skill in SKILL_DIRS:
        name = skill.parent.name
        if name == "tcc":
            continue
        assert name in router, f"router does not mention {name}"


def test_package_is_importable() -> None:
    import caio_code

    assert caio_code.__version__


def test_feature_tree_exists_with_flow_diagrams() -> None:
    feature_tree = ROOT / "FEATURE_TREE.md"
    assert feature_tree.is_file(), "FEATURE_TREE.md is missing"
    text = feature_tree.read_text(encoding="utf-8")
    assert "## FLOW" in text, "FEATURE_TREE.md has no flow diagram section"
    flow_count = text.count("## FLOW")
    assert flow_count >= 3, f"FEATURE_TREE.md documents {flow_count} flows, expected at least 3"
    assert "▶" in text or "-->" in text, "FEATURE_TREE.md flow diagrams have no arrows"