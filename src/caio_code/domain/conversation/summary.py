"""The anchored summary: sections, template, and tolerant parsing.

The structure is deliberately the one opencode ships, because a compaction is
only useful if the next turn can find things in it. Five sections, fixed order,
kept even when empty:

    ## Objective          what the user is trying to accomplish
    ## Important Details  constraints, decisions and why, assumptions
    ## Work State         ### Completed / ### Active / ### Blocked
    ## Next Move          the immediate concrete action, numbered
    ## Relevant Files     path: why it matters
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

SECTION_HEADINGS: tuple[str, ...] = (
    "Objective",
    "Important Details",
    "Work State",
    "Next Move",
    "Relevant Files",
)
WORK_STATE_SUBSECTIONS: tuple[str, ...] = ("Completed", "Active", "Blocked")
EMPTY_MARKER = "(none)"

SUMMARY_TEMPLATE = """\
Reply with the Markdown structure inside <template>, in this exact order, without the
<template> tags.
<template>
## Objective
- [what the user is trying to accomplish, in one or two sentences]
## Important Details
- [constraints, decisions and their reasons, assumptions, and any exact value needed to
  continue; write "(none)" when there is nothing to record]
## Work State
### Completed
- [work finished and verified, changes already made, or "(none)"]
### Active
- [work in progress, partial changes, open investigation, or "(none)"]
### Blocked
- [blockers, failing commands, unknowns, or "(none)"]
## Next Move
1. [the immediate concrete action, or "(none)"]
2. [the action after that, if known, or "(none)"]
## Relevant Files
- [path: why it matters, or "(none)"]
</template>
Rules:
- Keep every section, including the empty ones.
- Write terse bullets, never prose paragraphs.
- Copy file paths, symbols, commands, error strings, URLs and identifiers exactly.
- Never mention summarizing, compacting, or the context window."""

NEW_SUMMARY_INSTRUCTION = (
    "Write an anchored summary of the conversation inside the <conversation> tags, detailed "
    "enough for another coding agent to continue the work without reading the original."
)

PRIOR_SUMMARY_INSTRUCTION = """\
<prior-summary> covers everything that happened before <conversation>. Produce one summary that
merges both. The prior summary is discarded afterwards: whatever you do not carry over is lost.
When merging:
- Carry objectives, constraints, user directives, decisions and parallel workstreams from the
  prior summary forward even if the conversation does not mention them again. Drop only what is
  finished and no longer needed.
- The conversation is more recent. Where the two disagree, the conversation wins: state the
  corrected fact and drop the old one.
- Add the new progress, decisions and constraints the conversation introduced.
- Move work that finished from "Active" to "Completed".
- When a blocker was resolved, record that, keeping whatever detail is still needed to continue.
- Rewrite "Objective" and "Next Move" so they describe the present state of the work."""

SUMMARY_MESSAGE_PREFIX = "[Anchored summary of the conversation so far]"

_HEADING_RE = re.compile(r"^\s{0,3}(#{2,3})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class SummarySection:
    """One section of the anchored summary, sub-sections included."""

    heading: str
    level: int
    body: str

    def is_empty(self) -> bool:
        stripped = self.body.strip()
        return not stripped or stripped == EMPTY_MARKER or stripped == f"- {EMPTY_MARKER}"

    def render(self) -> str:
        prefix = "#" * self.level
        body = self.body.strip() or f"- {EMPTY_MARKER}"
        return f"{prefix} {self.heading}\n{body}"


@dataclass(frozen=True, slots=True)
class AnchoredSummary:
    """A parsed summary plus the raw text the model produced."""

    sections: tuple[SummarySection, ...]
    raw: str

    def render(self) -> str:
        if not self.sections:
            return self.raw.strip()
        return "\n".join(section.render() for section in self.sections)

    def section(self, heading: str) -> SummarySection | None:
        lowered = heading.strip().lower()
        for candidate in self.sections:
            if candidate.heading.strip().lower() == lowered:
                return candidate
        return None

    def text_of(self, heading: str) -> str:
        found = self.section(heading)
        return found.body.strip() if found else ""

    def missing_sections(self) -> tuple[str, ...]:
        present = {section.heading.strip().lower() for section in self.sections}
        expected = {heading.lower() for heading in SECTION_HEADINGS}
        expected.update(sub.lower() for sub in WORK_STATE_SUBSECTIONS)
        return tuple(sorted(expected - present))

    @property
    def is_well_formed(self) -> bool:
        return not self.missing_sections()


def parse_summary(text: str) -> AnchoredSummary:
    """Parse a summary tolerantly: unknown headings are kept, order is preserved."""
    cleaned = text.strip()
    if not cleaned:
        return AnchoredSummary(sections=(), raw="")

    matches = list(_HEADING_RE.finditer(cleaned))
    if not matches:
        return AnchoredSummary(sections=(), raw=cleaned)

    sections: list[SummarySection] = []
    for position, match in enumerate(matches):
        start = match.end()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(cleaned)
        sections.append(
            SummarySection(
                heading=match.group(2).strip(),
                level=len(match.group(1)),
                body=cleaned[start:end].strip(),
            )
        )
    return AnchoredSummary(sections=tuple(sections), raw=cleaned)


def empty_summary() -> AnchoredSummary:
    """A summary with every section present and empty, for the first turn."""
    sections: list[SummarySection] = []
    for heading in SECTION_HEADINGS:
        if heading == "Work State":
            sections.append(SummarySection(heading=heading, level=2, body=""))
            sections.extend(
                SummarySection(heading=sub, level=3, body=f"- {EMPTY_MARKER}")
                for sub in WORK_STATE_SUBSECTIONS
            )
            continue
        sections.append(SummarySection(heading=heading, level=2, body=f"- {EMPTY_MARKER}"))
    return AnchoredSummary(sections=tuple(sections), raw="")


def summarizer_prompt(
    *,
    conversation: Sequence[str],
    previous_summary: str | None = None,
) -> str:
    """Assemble the compaction prompt exactly as opencode does."""
    body = "\n".join(part for part in conversation if part)
    head = f"Here is the conversation so far:\n<conversation>\n{body}\n</conversation>"
    if not previous_summary:
        return "\n".join([head, NEW_SUMMARY_INSTRUCTION, SUMMARY_TEMPLATE])
    prior = (
        "Here is the summary of the conversation before the <conversation> above:\n"
        f"<prior-summary>\n{previous_summary}\n</prior-summary>"
    )
    return "\n".join([head, prior, PRIOR_SUMMARY_INSTRUCTION, SUMMARY_TEMPLATE])


def summary_sections_as_mapping(summary: AnchoredSummary) -> Mapping[str, str]:
    """Heading -> body, for tests, reports and the TUI inspector."""
    return {section.heading: section.body for section in summary.sections}
