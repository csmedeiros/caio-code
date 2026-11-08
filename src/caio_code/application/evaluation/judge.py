"""The LLM judge: binary grading of probe answers, and its calibration gate.

The judge sees exactly three things per probe -- the question, the gold answer
with its aliases, and the agent's reply -- and never the conversation. That
separation is the point: a grader that reads the context can answer the probe
itself and grade the agent against knowledge the agent no longer has, which
would measure the judge instead of the policy.

The prompt is a versioned file (``evals/prompts/judge_v1.md``); a revision is a
new file, never an edit, so every run states which judge text produced its
numbers. Before a full run the judge must pass a calibration gate against
hand-labelled answers: agreement at or above ``EvalConfig.judge_min_agreement``.
A judge that fails is rewritten, not tuned per answer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from caio_code.domain.conversation.messages import Message, Role
from caio_code.domain.errors import DatasetError, EvaluationError
from caio_code.domain.evaluation.cases import Probe
from caio_code.domain.ports.gateway import ModelGateway, ModelReply
from caio_code.domain.usage.accounting import TokenUsage

PAYLOAD_PLACEHOLDER = "[[PAYLOAD]]"
VERDICT_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


@dataclass(frozen=True, slots=True)
class JudgeItem:
    """One probe to grade: question, gold and the reply, nothing else."""

    probe_id: str
    question: str
    gold_answer: str
    aliases: tuple[str, ...]
    agent_reply: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "question": self.question,
            "gold_answer": self.gold_answer,
            "aliases": list(self.aliases),
            "agent_reply": self.agent_reply,
        }


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """The judge's binary decision on one probe."""

    probe_id: str
    correct: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class JudgeOutcome:
    """All verdicts of one grading call, with what the call cost."""

    verdicts: tuple[JudgeVerdict, ...]
    usage: TokenUsage
    model: str
    latency_ms: int = 0

    def verdict_for(self, probe_id: str) -> JudgeVerdict | None:
        for verdict in self.verdicts:
            if verdict.probe_id == probe_id:
                return verdict
        return None


@dataclass(frozen=True, slots=True)
class LabeledAnswer:
    """One hand-labelled answer, the unit of the calibration set."""

    item: JudgeItem
    human_correct: bool


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Judge-vs-human agreement over the labelled pilot answers."""

    total: int
    agreements: int
    disagreements: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def agreement_ratio(self) -> float:
        if self.total == 0:
            return 0.0
        return self.agreements / self.total

    def passed(self, min_agreement: float) -> bool:
        return self.total > 0 and self.agreement_ratio >= min_agreement

    def as_record(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "agreements": self.agreements,
            "agreement_ratio": round(self.agreement_ratio, 4),
            "disagreements": list(self.disagreements),
        }


def judge_items_for(probes: Sequence[Probe], agent_reply: str) -> tuple[JudgeItem, ...]:
    """The grading items of one probe round: same reply, one item per probe."""
    return tuple(
        JudgeItem(
            probe_id=probe.id,
            question=probe.question,
            gold_answer=probe.expected,
            aliases=probe.aliases,
            agent_reply=agent_reply,
        )
        for probe in probes
    )


def render_judge_prompt(template: str, items: Sequence[JudgeItem]) -> str:
    """Fill the versioned template with the JSON payload."""
    if PAYLOAD_PLACEHOLDER not in template:
        msg = (
            f"judge prompt has no {PAYLOAD_PLACEHOLDER!r} placeholder; "
            "the template is versioned, so fix it in a new judge_vN.md"
        )
        raise EvaluationError(msg)
    payload = json.dumps(
        [item.as_payload() for item in items], indent=2, ensure_ascii=False
    )
    return template.replace(PAYLOAD_PLACEHOLDER, payload)


def parse_verdicts(text: str, *, expected_ids: Sequence[str]) -> tuple[JudgeVerdict, ...]:
    """Parse the judge's JSON reply; raises ``EvaluationError`` naming the defect.

    A verdict the judge omitted is not silently counted as incorrect: the parse
    fails, the trial records the error, and the run stays honest about what was
    graded.
    """
    payload = _find_json_object(text)
    if payload is None:
        msg = f"judge reply is not a JSON object: {text[:200]!r}"
        raise EvaluationError(msg)
    raw_verdicts = payload.get("verdicts")
    if not isinstance(raw_verdicts, list):
        msg = "judge reply has no 'verdicts' list"
        raise EvaluationError(msg)
    verdicts: list[JudgeVerdict] = []
    for entry in raw_verdicts:
        if not isinstance(entry, dict):
            msg = f"judge verdict is not an object: {entry!r}"
            raise EvaluationError(msg)
        probe_id = entry.get("probe_id")
        correct = entry.get("correct")
        if not isinstance(probe_id, str) or not isinstance(correct, bool):
            msg = f"judge verdict lacks probe_id/correct: {entry!r}"
            raise EvaluationError(msg)
        reason = entry.get("reason", "")
        verdicts.append(
            JudgeVerdict(
                probe_id=probe_id,
                correct=correct,
                reason=reason if isinstance(reason, str) else str(reason),
            )
        )
    by_id = {verdict.probe_id: verdict for verdict in verdicts}
    missing = [probe_id for probe_id in expected_ids if probe_id not in by_id]
    if missing:
        msg = f"judge returned no verdict for probes: {missing}"
        raise EvaluationError(msg)
    return tuple(by_id[probe_id] for probe_id in expected_ids)


def _find_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    candidates: list[str] = []
    start = cleaned.find("{")
    while start != -1 and len(candidates) <= 5:
        end = cleaned.rfind("}")
        if end > start:
            candidates.append(cleaned[start : end + 1])
        start = cleaned.find("{", start + 1)
    fenced = VERDICT_FENCE_RE.search(cleaned)
    if fenced:
        candidates.insert(0, fenced.group(1))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "verdicts" in parsed:
            return parsed
    return None


class LlmJudge:
    """Binary probe grading over an auxiliary gateway."""

    def __init__(self, *, gateway: ModelGateway, prompt_template: str) -> None:
        if not prompt_template.strip():
            msg = "judge prompt template is empty"
            raise EvaluationError(msg)
        self._gateway = gateway
        self._template = prompt_template

    @property
    def model(self) -> str:
        return self._gateway.model

    async def agrade(self, items: Sequence[JudgeItem]) -> JudgeOutcome:
        """One grading call for the whole probe round."""
        if not items:
            msg = "the judge was asked to grade zero probes"
            raise EvaluationError(msg)
        prompt = render_judge_prompt(self._template, items)
        reply: ModelReply = await self._gateway.acomplete(
            [Message(id="judge-prompt", role=Role.USER, text=prompt)]
        )
        verdicts = parse_verdicts(
            reply.text, expected_ids=[item.probe_id for item in items]
        )
        return JudgeOutcome(
            verdicts=verdicts,
            usage=reply.usage,
            model=reply.model,
            latency_ms=reply.latency_ms,
        )

    def grade(self, items: Sequence[JudgeItem]) -> JudgeOutcome:
        """Synchronous variant for the calibration harness and the CLI."""
        import asyncio

        return asyncio.run(self.agrade(items))

    async def acalibrate(
        self, labeled: Sequence[LabeledAnswer]
    ) -> CalibrationReport:
        """Agreement with hand labels; the gate a full run must pass first."""
        if not labeled:
            msg = "calibration needs hand-labelled answers; got none"
            raise EvaluationError(msg)
        disagreements: list[dict[str, Any]] = []
        agreements = 0
        # One call per labelled answer keeps an outlier reply from poisoning the
        # grading of the others, matching how a trial's probes are graded in
        # one call each.
        for entry in labeled:
            outcome = await self.agrade([entry.item])
            verdict = outcome.verdicts[0]
            if verdict.correct == entry.human_correct:
                agreements += 1
            else:
                disagreements.append(
                    {
                        "probe_id": entry.item.probe_id,
                        "human": entry.human_correct,
                        "judge": verdict.correct,
                        "reason": verdict.reason,
                        "question": entry.item.question,
                        "gold": entry.item.gold_answer,
                        "reply": entry.item.agent_reply[:400],
                    }
                )
        return CalibrationReport(
            total=len(labeled),
            agreements=agreements,
            disagreements=tuple(disagreements),
        )


def load_judge_prompt(path: Path) -> str:
    """Read the versioned judge prompt; a missing file stops the run."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read the judge prompt {path}: {exc}"
        raise DatasetError(msg) from exc


__all__ = [
    "PAYLOAD_PLACEHOLDER",
    "CalibrationReport",
    "JudgeItem",
    "JudgeOutcome",
    "JudgeVerdict",
    "LabeledAnswer",
    "LlmJudge",
    "judge_items_for",
    "load_judge_prompt",
    "parse_verdicts",
    "render_judge_prompt",
]
