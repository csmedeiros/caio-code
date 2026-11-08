"""Composition root of the CLI.

This is the only place in the presentation layer allowed to import
infrastructure: it turns :class:`Settings` into fully-injected
:class:`AgentDependencies`, builds the policy pipeline named on the command
line, and assembles the system prompt. Tests reuse these builders with a
``FixedClock``/``SequentialIdentifiers`` and the stub provider.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from caio_code.application.agent.bridges import (
    load_guard_factory,
    load_run_ledger_factory,
    load_todo_tracker_factory,
)
from caio_code.application.agent.prompt import build_system_prompt
from caio_code.application.agent.runner import AgentDependencies, AgentRunner
from caio_code.config import Settings, load_settings
from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.errors import ConfigurationError
from caio_code.domain.events import EventBus, InMemoryEventBus
from caio_code.domain.policy.base import ContextPolicy, PolicyPipeline
from caio_code.domain.policy.compaction import CompactionPlanner
from caio_code.domain.policy.full_history import FullHistoryPolicy
from caio_code.domain.policy.message_selection import MessageSelectionPolicy
from caio_code.domain.policy.sliding_window import SlidingWindowPolicy
from caio_code.domain.policy.tool_output import ToolOutputTruncationPolicy
from caio_code.domain.ports.time import Clock, IdentifierFactory
from caio_code.infrastructure.llm.factory import build_gateway, build_scorer, build_summarizer
from caio_code.infrastructure.llm.stub import StubScorer
from caio_code.infrastructure.observability.clocks import (
    SequentialIdentifiers,
    SystemClock,
)
from caio_code.infrastructure.pricing.sheet import pricing_for
from caio_code.infrastructure.tokens.counter import build_counter
from caio_code.infrastructure.tools.deepagents_backend import build_backend
from caio_code.infrastructure.tools.filesystem import FilesystemToolset
from caio_code.infrastructure.tools.sandbox import Sandbox
from caio_code.infrastructure.tools.search import SearchToolset
from caio_code.infrastructure.tools.shell import ShellToolset

SEARCH_MAX_RESULTS = 100
"""Ceiling for grep/find results; no config slot exists for it yet, so it is a
named module constant (report to add ``SearchConfig.max_results`` to config)."""

BASELINE_ALIASES: frozenset[str] = frozenset({"baseline", "full_history", "baseline_full_history"})
POLICY_NAMES: tuple[str, ...] = (
    "sliding_window",
    "message_selection",
    "compaction",
    "tool_output",
    "baseline",
)


def tool_output_policy(settings: Settings) -> ToolOutputTruncationPolicy:
    return ToolOutputTruncationPolicy(
        max_lines=settings.tool_output.max_lines,
        max_bytes=settings.tool_output.max_bytes,
    )


def build_policy_policies(settings: Settings, name: str) -> tuple[ContextPolicy, ...]:
    """The policy steps of a named arm; truncation always runs first."""
    if name in BASELINE_ALIASES:
        return (FullHistoryPolicy(),)
    if name == "sliding_window":
        return (
            tool_output_policy(settings),
            SlidingWindowPolicy(keep_recent_messages=settings.sliding_window.keep_recent_messages),
        )
    if name == "message_selection":
        return (
            tool_output_policy(settings),
            MessageSelectionPolicy(
                keep_recent_messages=settings.selection.keep_recent_messages,
                top_k_floor=settings.selection.top_k_floor,
            ),
        )
    if name == "compaction":
        return (
            tool_output_policy(settings),
            CompactionPlanner(
                keep_tokens=settings.compaction.keep_tokens,
                summary_allowance_tokens=settings.compaction.summary_max_tokens,
                tool_result_char_cap=settings.compaction.tool_result_char_cap,
            ),
        )
    if name == "tool_output":
        return (tool_output_policy(settings),)
    msg = f"unknown policy {name!r}; expected one of {sorted(POLICY_NAMES)}"
    raise ConfigurationError(msg)


def build_policy_pipeline(settings: Settings, name: str) -> PolicyPipeline:
    """Named pipeline; the baseline arm keeps its honest no-management name."""
    resolved = "baseline_full_history" if name in BASELINE_ALIASES else name
    return PolicyPipeline(resolved, build_policy_policies(settings, name))


def resolve_system_prompt(settings: Settings, *, policy_name: str, extra: str = "") -> str:
    """The configured prompt file when present, else the built prompt."""
    if settings.system_prompt_file is not None:
        path = Path(settings.system_prompt_file)
        if not path.is_file():
            msg = f"system_prompt_file does not exist: {str(path)!r}"
            raise ConfigurationError(msg)
        return path.read_text(encoding="utf-8")
    return build_system_prompt(
        workspace_root=str(settings.sandbox.root),
        policy_name=policy_name,
        window_tokens=settings.window.tokens,
        extra=extra,
    )


def build_dependencies(
    settings: Settings,
    *,
    bus: EventBus | None = None,
    clock: Clock | None = None,
    identifiers: IdentifierFactory | None = None,
    chat_model: Any | None = None,
    checkpointer: Any | None = None,
) -> AgentDependencies:
    """Every collaborator, injected; nothing here reads a clock of its own."""
    resolved_bus: EventBus = bus if bus is not None else InMemoryEventBus()
    resolved_clock: Clock = clock if clock is not None else SystemClock()
    resolved_identifiers: IdentifierFactory = (
        identifiers if identifiers is not None else SequentialIdentifiers()
    )
    counter = build_counter(
        settings.tokens.counter,
        chars_per_token=settings.tokens.chars_per_token,
        encoding=settings.tokens.tiktoken_encoding,
    )
    pricing = pricing_for(settings)
    ledger_factory = load_run_ledger_factory()
    todo_factory = load_todo_tracker_factory()
    guard_factory = load_guard_factory()
    sandbox = Sandbox(settings.sandbox)
    toolsets: Sequence[Any] = (
        FilesystemToolset(sandbox, settings.tool_output),
        ShellToolset(sandbox, settings.sandbox, settings.tool_output),
        SearchToolset(sandbox, settings.tool_output, max_results=SEARCH_MAX_RESULTS),
    )
    return AgentDependencies(
        settings=settings,
        bus=resolved_bus,
        clock=resolved_clock,
        identifiers=resolved_identifiers,
        counter=counter,
        gateway=build_gateway(settings, clock=resolved_clock),
        summarizer=build_summarizer(settings, clock=resolved_clock),
        scorer=build_scorer(settings, StubScorer(), clock=resolved_clock),
        todos=todo_factory(resolved_bus, resolved_clock, resolved_identifiers),
        guard=guard_factory(settings.guardrails, resolved_bus),
        ledger=ledger_factory(resolved_bus, pricing, settings.provider.model),
        toolsets=toolsets,
        backend=build_backend(settings),
        pricing=pricing,
        chat_model=chat_model,
        checkpointer=checkpointer,
    )


def build_runner(
    settings: Settings,
    *,
    policy_name: str,
    bus: EventBus | None = None,
    clock: Clock | None = None,
    identifiers: IdentifierFactory | None = None,
    chat_model: Any | None = None,
    checkpointer: Any | None = None,
    system_prompt_extra: str = "",
) -> AgentRunner:
    """Settings in, a runner with a built graph out (the composition recipe)."""
    deps = build_dependencies(
        settings,
        bus=bus,
        clock=clock,
        identifiers=identifiers,
        chat_model=chat_model,
        checkpointer=checkpointer,
    )
    runner = AgentRunner(deps)
    pipeline = build_policy_pipeline(settings, policy_name)
    prompt = resolve_system_prompt(settings, policy_name=pipeline.name, extra=system_prompt_extra)
    runner.build_agent(
        policy=pipeline,
        budget=TokenBudget(settings.window.tokens),
        system_prompt=prompt,
    )
    return runner


def load_cli_settings(
    args: Any,
    *,
    with_model: bool = False,
    with_window: bool = False,
    with_root: bool = False,
) -> Settings:
    """``load_settings`` from argparse attributes, tolerating absent options."""
    provider = getattr(args, "provider", None)
    model = getattr(args, "model", None) if with_model else None
    window = getattr(args, "window_tokens", None) if with_window else None
    root: Path | None = None
    if with_root:
        raw_root = getattr(args, "root", None)
        root = Path(raw_root).expanduser() if raw_root else None
    return load_settings(provider=provider, model=model, window_tokens=window, root=root)


__all__ = [
    "POLICY_NAMES",
    "SEARCH_MAX_RESULTS",
    "build_dependencies",
    "build_policy_pipeline",
    "build_runner",
    "load_cli_settings",
    "resolve_system_prompt",
]
