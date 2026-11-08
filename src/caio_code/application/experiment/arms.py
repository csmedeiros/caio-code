"""Experiment arms: one policy configuration per arm.

An arm is the unit of comparison in Chapter 4. It names a policy pipeline, the
window it has to fit, and whether an overflow aborts the trial. Every arm shares
the same cases, the same model and the same probes, so the only difference
between two arms is the context policy - which is the whole point of the
experiment.

The truncation arms exist in isolation and combined with a retention policy,
because tool-output truncation shrinks message *content* while the others choose
*which messages* survive: they are complementary, and the combination is what a
real harness ships.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from caio_code.config import Settings
from caio_code.domain.policy.base import ContextPolicy, PolicyPipeline
from caio_code.domain.policy.compaction import CompactionPlanner
from caio_code.domain.policy.full_history import FullHistoryPolicy
from caio_code.domain.policy.message_selection import MessageSelectionPolicy
from caio_code.domain.policy.sliding_window import SlidingWindowPolicy
from caio_code.domain.policy.structure_repair import StructureRepairPolicy
from caio_code.domain.policy.tool_output import ToolOutputTruncationPolicy

PipelineFactory = Callable[[Settings], PolicyPipeline]


@dataclass(frozen=True, slots=True)
class ArmSpec:
    """One configuration of the experiment."""

    name: str
    description: str
    factory: PipelineFactory
    window_tokens: int
    enforce_window: bool = False
    needs_compaction: bool = False
    needs_scores: bool = False
    scorer_kind: Literal["lexical", "decision"] = "lexical"
    """Who scores relevance: the deterministic lexical scorer or the decision model.

    The two arms that differ only in this field isolate the value of a calibrated
    judgement over lexical overlap, and the decision model's own token bill is
    charged to the arm that used it.
    """

    def pipeline(self, settings: Settings) -> PolicyPipeline:
        return self.factory(settings)


def _truncation(settings: Settings) -> ToolOutputTruncationPolicy:
    return ToolOutputTruncationPolicy(
        limits=None,
        max_lines=settings.tool_output.max_lines,
        max_bytes=settings.tool_output.max_bytes,
    )


def _window(settings: Settings) -> SlidingWindowPolicy:
    return SlidingWindowPolicy(keep_recent_messages=settings.selection.keep_recent_messages // 2)


def _selection(settings: Settings) -> MessageSelectionPolicy:
    return MessageSelectionPolicy(
        keep_recent_messages=settings.selection.keep_recent_messages,
        top_k_floor=settings.selection.top_k_floor,
    )


def _compaction(settings: Settings) -> CompactionPlanner:
    """Anchored compaction whose verbatim tail is sized against the window.

    The tail ceiling is the window itself and the summary allowance is reserved
    out of it, so the shaped context is summary + tail + fixed cost <= window by
    construction. Sizing the tail to a constant instead -- the earlier
    configuration set it to the whole window and then stacked the summary on top
    -- makes the arm overflow no matter how well the summarizer behaves, which
    measures the misconfiguration rather than the policy.
    """
    return CompactionPlanner(
        keep_tokens=settings.window.tokens,
        summary_allowance_tokens=settings.compaction.summary_max_tokens,
        tool_result_char_cap=settings.compaction.tool_result_char_cap,
        head_char_cap=settings.compaction.head_char_cap,
    )


def _single(name: str, policy: ContextPolicy) -> PolicyPipeline:
    """One retention policy, always closed by the structure repair.

    The repair is last because it can only re-pair tool calls and results once
    the retention policy decided what survives; without it a window that cuts
    the head sends an orphan tool result and the provider answers with a 400.
    """
    return PolicyPipeline(name, [policy, StructureRepairPolicy()])


def _combined(name: str, settings: Settings, main: ContextPolicy) -> PolicyPipeline:
    return PolicyPipeline(name, [_truncation(settings), main, StructureRepairPolicy()])


def default_arms(settings: Settings) -> tuple[ArmSpec, ...]:
    """The arms the thesis reports, in the order they appear in the table."""
    window = settings.window.tokens

    return (
        ArmSpec(
            name="baseline_full_history",
            description=(
                "No management. The whole history is sent; the overflow against the declared "
                "window is measured but the call still happens, so its real cost is visible."
            ),
            factory=lambda cfg: _single("baseline_full_history", FullHistoryPolicy()),
            window_tokens=window,
        ),
        ArmSpec(
            name="baseline_capped",
            description=(
                "No management, window enforced. A trial that does not fit is refused and "
                "recorded as a context overflow instead of being sent."
            ),
            factory=lambda cfg: _single("baseline_capped", FullHistoryPolicy()),
            window_tokens=window,
            enforce_window=True,
        ),
        ArmSpec(
            name="sliding_window",
            description="Keep the newest contiguous tail that fits the window; drop the rest.",
            factory=lambda cfg: _single("sliding_window", _window(cfg)),
            window_tokens=window,
        ),
        ArmSpec(
            name="message_selection",
            description=(
                "Keep a relevance-scored, non-contiguous subset; the scorer sees the task and "
                "every message."
            ),
            factory=lambda cfg: _single("message_selection", _selection(cfg)),
            window_tokens=window,
            needs_scores=True,
        ),
        ArmSpec(
            name="message_selection_decision",
            description=(
                "Selection scored by the TypeSafe decision model: one yes/no question per "
                "message, and the probability of yes is the relevance score."
            ),
            factory=lambda cfg: _single("message_selection_decision", _selection(cfg)),
            window_tokens=window,
            needs_scores=True,
            scorer_kind="decision",
        ),
        ArmSpec(
            name="message_selection_decision_plus_truncation",
            description=(
                "Decision-model scoring with tool outputs truncated first: the two mechanisms "
                "that decide, respectively, which messages survive and how much each costs."
            ),
            factory=lambda cfg: _combined(
                "message_selection_decision_plus_truncation", cfg, _selection(cfg)
            ),
            window_tokens=window,
            needs_scores=True,
            scorer_kind="decision",
        ),
        ArmSpec(
            name="anchored_compaction",
            description=(
                "Fold everything older than the verbatim tail into an anchored summary with the "
                "five fixed sections; the tail survives word for word."
            ),
            factory=lambda cfg: _single("anchored_compaction", _compaction(cfg)),
            window_tokens=window,
            needs_compaction=True,
        ),
        ArmSpec(
            name="tool_truncation_only",
            description=(
                "Cap tool results only (lines and bytes, head plus tail). No message is dropped, "
                "so this arm isolates the contribution of shrinking tool output."
            ),
            factory=lambda cfg: _single("tool_truncation_only", _truncation(cfg)),
            window_tokens=window,
        ),
        ArmSpec(
            name="sliding_window_plus_truncation",
            description="Truncate tool outputs first, then keep the newest tail that fits.",
            factory=lambda cfg: _combined("sliding_window_plus_truncation", cfg, _window(cfg)),
            window_tokens=window,
        ),
        ArmSpec(
            name="message_selection_plus_truncation",
            description="Truncate tool outputs first, then keep the highest-scoring subset.",
            factory=lambda cfg: _combined(
                "message_selection_plus_truncation", cfg, _selection(cfg)
            ),
            window_tokens=window,
            needs_scores=True,
        ),
        ArmSpec(
            name="anchored_compaction_plus_truncation",
            description=(
                "Truncate tool outputs first, then compact the head into an anchored summary. "
                "This is the configuration the prototype ships."
            ),
            factory=lambda cfg: _combined(
                "anchored_compaction_plus_truncation", cfg, _compaction(cfg)
            ),
            window_tokens=window,
            needs_compaction=True,
        ),
    )


def select_arms(settings: Settings, names: Sequence[str] | None = None) -> tuple[ArmSpec, ...]:
    """All default arms, or the subset whose names were requested."""
    arms = default_arms(settings)
    if not names:
        return arms
    wanted = {name.strip() for name in names if name.strip()}
    unknown = sorted(wanted - {arm.name for arm in arms})
    if unknown:
        msg = f"unknown arms: {', '.join(unknown)}; available: {', '.join(a.name for a in arms)}"
        raise ValueError(msg)
    return tuple(arm for arm in arms if arm.name in wanted)
