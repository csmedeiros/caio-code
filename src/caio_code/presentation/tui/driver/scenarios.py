"""The built-in scenarios: offline, deterministic, driven by ScriptedFacade.

Every entry of :data:`SCENARIOS` is a factory that builds a fresh app (facade
plus bus plus FixedClock) and returns it together with the driver steps. The
CLI and the tests call the factories, so no state leaks between runs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from textual.app import App

from caio_code.config import DEFAULT_AGENT_MODEL
from caio_code.domain.events import InMemoryEventBus
from caio_code.domain.usage.accounting import TokenUsage
from caio_code.infrastructure.observability.clocks import FixedClock, SequentialIdentifiers
from caio_code.presentation.tui.app import CaioCodeApp
from caio_code.presentation.tui.driver.errors import ScenarioError
from caio_code.presentation.tui.driver.steps import (
    ALL_SCENARIOS,
    AssertFooter,
    AssertText,
    AssertTodo,
    AssertWidget,
    Key,
    Scenario,
    Send,
    Snapshot,
    Wait,
)
from caio_code.presentation.tui.scripted import (
    AssistantStep,
    AwaitInterruptStep,
    CompactionStep,
    ContextStep,
    FinishStep,
    Script,
    ScriptedFacade,
    TodoStep,
    UsageStep,
    demo_script,
    fixed_now,
)

SCENARIO_SETTLE_MS = 50
INTERRUPT_SETTLE_MS = 100
DEMO_MODEL = DEFAULT_AGENT_MODEL
DEMO_POLICY = "sliding_window"

SMOKE_SCRIPT: Script = (
    AssistantStep("Hello! How can I help you today?", deltas=2),
    FinishStep(),
)
SMOKE_STEPS: Scenario = (
    Send("hello"),
    Wait(SCENARIO_SETTLE_MS),
    AssertText("Hello! How can I help you today?"),
    Snapshot("assistant-reply"),
    Key("ctrl+q"),
)

TODO_ITEMS_INITIAL: tuple[tuple[str, str], ...] = (
    ("Read the failing module", "in_progress"),
    ("Reproduce the bug", "pending"),
    ("Patch the window policy", "pending"),
    ("Add a regression test", "pending"),
    ("Run the suite", "pending"),
)
TODO_ITEMS_PROGRESS: tuple[tuple[str, str], ...] = (
    ("Read the failing module", "completed"),
    ("Reproduce the bug", "completed"),
    ("Patch the window policy", "in_progress"),
    ("Add a regression test", "pending"),
    ("Run the suite", "pending"),
)
TODO_SCRIPT: Script = (
    TodoStep(TODO_ITEMS_INITIAL),
    AssistantStep("Planning the refactor in five steps.", deltas=2),
    TodoStep(TODO_ITEMS_PROGRESS),
    FinishStep(),
)
TODO_STEPS: Scenario = (
    Send("plan the refactor"),
    Wait(SCENARIO_SETTLE_MS),
    AssertTodo(count=5, in_progress=1, completed=2),
    AssertText("2/5 · 40%", within="#todo-header"),
    AssertText("Patch the window policy", within="#sidebar"),
    Snapshot("todo-progress"),
    Key("ctrl+q"),
)

OVER_BUDGET_TOKENS = 12_400
COMPACTED_TOKENS = 4_100
COMPACT_BUDGET_TOKENS = 8_000
COMPACTION_SUMMARY = (
    "## Objective\n- finish the migration\n"
    "## Work State\n### Completed\n- window policy patched\n"
    "## Next Move\n1. run the suite"
)
COMPACTION_SCRIPT: Script = (
    AssistantStep("The context is filling up; I will keep going.", deltas=2),
    ContextStep(
        policy="baseline",
        tokens_before=OVER_BUDGET_TOKENS,
        tokens_after=OVER_BUDGET_TOKENS,
        budget_tokens=COMPACT_BUDGET_TOKENS,
        kept=20,
        dropped=0,
    ),
    UsageStep(usage=TokenUsage(input_tokens=OVER_BUDGET_TOKENS, output_tokens=300)),
    CompactionStep(summary_text=COMPACTION_SUMMARY, head_chars=OVER_BUDGET_TOKENS),
    ContextStep(
        policy="compaction",
        tokens_before=OVER_BUDGET_TOKENS,
        tokens_after=COMPACTED_TOKENS,
        budget_tokens=COMPACT_BUDGET_TOKENS,
        kept=8,
        dropped=12,
    ),
    AssistantStep("Compacted; continuing the migration.", deltas=1),
    FinishStep(),
)
COMPACTION_STEPS: Scenario = (
    Send("keep going until the context overflows"),
    Wait(SCENARIO_SETTLE_MS),
    AssertText("## Objective", within="#transcript"),
    AssertWidget(".message-summary"),
    AssertFooter(contains=("4.1k", "8.0k", "51%")),
    Snapshot("after-compaction"),
    Key("ctrl+u"),
    Wait(SCENARIO_SETTLE_MS),
    AssertWidget("#context-inspector"),
    Snapshot("context-inspector"),
    Key("escape"),
    Key("ctrl+q"),
)

INTERRUPT_SCRIPT: Script = (
    AssistantStep("Starting the long refactor; this will take a while.", deltas=4),
    AwaitInterruptStep(),
    AssistantStep("This text must never be rendered.", deltas=1),
    FinishStep(),
)
INTERRUPT_STEPS: Scenario = (
    Send("start the long run"),
    Wait(SCENARIO_SETTLE_MS),
    AssertFooter(contains=("running",)),
    Key("escape"),
    Wait(INTERRUPT_SETTLE_MS),
    AssertFooter(contains=("interrupted",)),
    Snapshot("interrupted"),
    Key("ctrl+q"),
)

DEMO_STEPS: Scenario = (
    Send("demo run"),
    Wait(SCENARIO_SETTLE_MS),
    AssertText("Patched the policy; tests are green.", within="#transcript"),
    AssertTodo(count=3, in_progress=1, completed=1),
    AssertWidget("#tool-panel-msg-msg-0003"),
    Snapshot("demo-final"),
    Key("ctrl+q"),
)


def build_app(script: Script, steps: Scenario) -> tuple[App[object], Scenario]:
    """Wire a ScriptedFacade app around ``script``; returns app and steps."""
    bus = InMemoryEventBus()
    clock = FixedClock(fixed_now())
    facade = ScriptedFacade(
        bus,
        clock,
        SequentialIdentifiers(),
        script=script,
        model=DEMO_MODEL,
        policy=DEMO_POLICY,
    )
    app: App[object] = CaioCodeApp(facade, bus, clock=clock)
    return app, steps


def build_smoke() -> tuple[App[object], Scenario]:
    return build_app(SMOKE_SCRIPT, SMOKE_STEPS)


def build_todo_sidebar() -> tuple[App[object], Scenario]:
    return build_app(TODO_SCRIPT, TODO_STEPS)


def build_compaction() -> tuple[App[object], Scenario]:
    return build_app(COMPACTION_SCRIPT, COMPACTION_STEPS)


def build_interrupt() -> tuple[App[object], Scenario]:
    return build_app(INTERRUPT_SCRIPT, INTERRUPT_STEPS)


def build_demo() -> tuple[App[object], Scenario]:
    return build_app(demo_script(), DEMO_STEPS)


ScenarioFactory = Callable[[], tuple[App[object], Scenario]]

SCENARIOS: Mapping[str, ScenarioFactory] = {
    "smoke": build_smoke,
    "todo_sidebar": build_todo_sidebar,
    "compaction": build_compaction,
    "interrupt": build_interrupt,
    "demo": build_demo,
}


def resolve_scenario_names(requested: Sequence[str]) -> list[str]:
    """Expand ``all`` and validate names; unknown names raise ScenarioError."""
    if not requested:
        msg = "no scenario requested"
        raise ScenarioError(msg)
    names: list[str] = []
    for name in requested:
        if name == ALL_SCENARIOS:
            names.extend(SCENARIOS)
        elif name in SCENARIOS:
            names.append(name)
        else:
            known = ", ".join(sorted({*SCENARIOS, ALL_SCENARIOS}))
            msg = f"unknown scenario {name!r}; known: {known}"
            raise ScenarioError(msg)
    deduplicated = list(dict.fromkeys(names))
    return deduplicated


def build_scenario(name: str) -> tuple[App[object], Scenario]:
    try:
        factory = SCENARIOS[name]
    except KeyError as exc:
        msg = f"unknown scenario {name!r}"
        raise ScenarioError(msg) from exc
    return factory()
