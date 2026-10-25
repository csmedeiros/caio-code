"""Repository invariants.

These tests do not exercise the agent — the agent does not exist yet. They
protect the conventions that the rest of the repository depends on, so that a
broken convention fails in CI instead of silently rotting.
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