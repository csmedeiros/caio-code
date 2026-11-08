"""The agent use case: one deepagents graph, streamed, instrumented, guarded.

``AgentRunner`` owns the loop. It builds the graph once (``build_agent``) from
explicit ``AgentDependencies`` -- nothing is created implicitly, so every test
injects stubs -- and each ``run`` publishes the domain event stream the TUI,
the ledger and the eval harness consume:

``RunStarted`` -> ``MessageAppended`` (deltas share one ``message_id``) ->
``ToolCallIssued``/``ToolCallCompleted`` (guard advisory injected as the tool
message when it fires) -> ``UsageRecorded`` -> ``RunFinished``.

Time and identifiers come only from the injected ``Clock``/``IdentifierFactory``.
``interrupt()`` cancels the streaming task and the run returns with status
``"interrupted"``; errors are caught, recorded on the result and published on
``RunFinished`` -- never swallowed silently.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from deepagents import create_deep_agent
from deepagents.backends import BackendProtocol
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from caio_code.application.agent.bridges import (
    GuardPort,
    RunLedgerPort,
    TodoTrackerPort,
    load_compaction_service_class,
    load_context_policy_middleware_factory,
)
from caio_code.application.agent.session import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_ERROR,
    RUN_STATUS_INTERRUPTED,
    AgentRunResult,
    ContextSnapshot,
)
from caio_code.application.agent.stub_model import (
    STUB_MODEL_NAME,
    StubChatModel,
    build_stub_chat_model,
)
from caio_code.config import Settings
from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Transcript
from caio_code.domain.errors import CaioCodeError, ConfigurationError
from caio_code.domain.events import (
    CompactionEnded,
    ContextShaped,
    DomainEvent,
    EventBus,
    MessageAppended,
    RunFinished,
    RunStarted,
    TodoBoardUpdated,
    ToolCallCompleted,
    ToolCallIssued,
    UsageRecorded,
)
from caio_code.domain.policy.base import PolicyPipeline
from caio_code.domain.ports.gateway import ModelGateway
from caio_code.domain.ports.scorer import RelevanceScorer
from caio_code.domain.ports.summarizer import Summarizer
from caio_code.domain.ports.time import Clock, IdentifierFactory
from caio_code.domain.ports.tokenizer import TokenCounter
from caio_code.domain.usage.accounting import PriceSheet, TokenUsage
from caio_code.infrastructure.mappers.langchain import to_domain
from caio_code.infrastructure.persistence.codec import message_to_dict
from caio_code.infrastructure.tools.deepagents_backend import build_backend

WRITE_TODOS_TOOL_NAME = "write_todos"
DEEPAGENTS_BUILTIN_TOOL_NAMES: frozenset[str] = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute", "task", WRITE_TODOS_TOOL_NAME}
)
"""Built-in deepagents tool names; toolset tools with these names are dropped
so the graph never sees two tools with the same name."""

ASTREAM_EVENTS_VERSION = "v2"
RUN_ID_UNSET = ""


class AgentNotBuiltError(CaioCodeError):
    """``run`` was called before ``build_agent`` produced a graph."""


@runtime_checkable
class LangChainToolset(Protocol):
    """A toolset adapter exposing LangChain tools."""

    def as_langchain_tools(self) -> list[Any]: ...


@dataclass(frozen=True, slots=True)
class AgentDependencies:
    """Everything the runner needs, injected explicitly by the composition root."""

    settings: Settings
    bus: EventBus
    clock: Clock
    identifiers: IdentifierFactory
    counter: TokenCounter
    gateway: ModelGateway
    summarizer: Summarizer
    scorer: RelevanceScorer
    todos: TodoTrackerPort
    guard: GuardPort
    ledger: RunLedgerPort
    toolsets: Sequence[LangChainToolset]
    backend: BackendProtocol | None = None
    pricing: PriceSheet = field(default_factory=PriceSheet)
    chat_model: Any | None = None
    checkpointer: Any | None = None


@dataclass(slots=True)
class _AgentBundle:
    """The built graph plus the parts ``run`` needs to instrument it."""

    graph: Any
    pipeline: PolicyPipeline
    model_name: str
    context_middleware: AgentMiddleware[Any, Any, Any]
    tool_middleware: AgentMiddleware[Any, Any, Any]


@dataclass(slots=True)
class _StreamOutcome:
    final_text: str
    transcript: tuple[dict[str, Any], ...]


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content) if content else ""


def _tool_result_messages(result: Any) -> list[ToolMessage]:
    """ToolMessages produced by one tool call, unwrapping ``Command`` updates."""
    if isinstance(result, ToolMessage):
        return [result]
    update = getattr(result, "update", None)
    if isinstance(update, dict):
        messages = update.get("messages")
        if isinstance(messages, list):
            return [message for message in messages if isinstance(message, ToolMessage)]
    if isinstance(result, list):
        return [message for message in result if isinstance(message, ToolMessage)]
    return []


def _token_usage_from_message(message: Any) -> TokenUsage | None:
    """Map LangChain usage metadata (or OpenAI token_usage) onto the domain."""
    usage: Any = getattr(message, "usage_metadata", None)
    input_tokens = 0
    output_tokens = 0
    cached = 0
    if isinstance(usage, dict) and usage:
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        details = usage.get("input_token_details") or {}
        if isinstance(details, dict):
            cached = int(details.get("cache_read", 0) or 0)
    else:
        metadata = getattr(message, "response_metadata", None) or {}
        token_usage = metadata.get("token_usage") if isinstance(metadata, dict) else None
        if not isinstance(token_usage, dict):
            return None
        input_tokens = int(token_usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(token_usage.get("completion_tokens", 0) or 0)
        details = token_usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            cached = int(details.get("cached_tokens", 0) or 0)
    if input_tokens <= 0 and output_tokens <= 0:
        return None
    cached = max(0, min(cached, input_tokens))
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached,
    )


class _ToolEventMiddleware(AgentMiddleware[Any, Any, Any]):
    """Publishes tool events, runs the guard, and bridges ``write_todos``.

    Lives between the runner and the graph: ``wrap_tool_call`` sees every tool
    invocation, so this is where ``ToolCallIssued``/``ToolCallCompleted`` are
    published, where the repeated-call guard runs *before* execution (its
    advisory replaces the tool result when it fires), and where a
    ``write_todos`` call updates the :class:`TodoTrackerPort`.
    """

    def __init__(self, runner: AgentRunner) -> None:
        super().__init__()
        self._runner = runner
        self.run_id = RUN_ID_UNSET

    def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        return self._runner._handle_tool_call(request, handler, is_async=False)

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        return await self._runner._handle_tool_call(request, handler, is_async=True)


class AgentRunner:
    """One deepagents graph, streamed and instrumented, per use case."""

    def __init__(self, deps: AgentDependencies) -> None:
        self._deps = deps
        self._bundle: _AgentBundle | None = None
        self._run_id = RUN_ID_UNSET
        self._snapshot: ContextSnapshot | None = None
        self._compactions = 0
        self._interrupt_event = asyncio.Event()
        self._stream_task: asyncio.Task[_StreamOutcome] | None = None
        self._last_result: AgentRunResult | None = None
        deps.bus.subscribe(self._on_event)

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------

    @property
    def deps(self) -> AgentDependencies:
        return self._deps

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def board(self) -> Any:
        return self._deps.todos.board

    @property
    def accounting(self) -> Any:
        return self._deps.ledger.accounting()

    @property
    def context(self) -> ContextSnapshot | None:
        return self._snapshot

    @property
    def compactions(self) -> int:
        return self._compactions

    @property
    def last_result(self) -> AgentRunResult | None:
        return self._last_result

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_agent(
        self,
        *,
        policy: PolicyPipeline,
        budget: TokenBudget,
        system_prompt: str,
    ) -> Any:
        """Create the deepagents graph; call once before the first ``run``."""
        deps = self._deps
        chat_model = deps.chat_model if deps.chat_model is not None else self._build_chat_model()
        model_name = _model_name_of(chat_model, deps.settings)
        tools = self._collect_tools()

        compaction = self._build_compaction_service()
        middleware_factory = load_context_policy_middleware_factory()
        context_middleware = middleware_factory(
            policy,
            counter=deps.counter,
            bus=deps.bus,
            clock=deps.clock,
            compaction=compaction,
            budget=budget,
            run_id=RUN_ID_UNSET,
        )
        tool_middleware = _ToolEventMiddleware(self)
        backend = deps.backend if deps.backend is not None else build_backend(deps.settings)

        graph = create_deep_agent(
            model=chat_model,
            tools=tools,
            system_prompt=system_prompt,
            middleware=[TodoListMiddleware(), tool_middleware, context_middleware],
            backend=backend,
            checkpointer=deps.checkpointer,
            name=deps.settings.agent_name,
        )
        self._bundle = _AgentBundle(
            graph=graph,
            pipeline=policy,
            model_name=model_name,
            context_middleware=context_middleware,
            tool_middleware=tool_middleware,
        )
        return graph

    def _build_compaction_service(self) -> Any | None:
        service_class = load_compaction_service_class()
        if service_class is None:
            return None
        deps = self._deps
        return service_class(
            deps.summarizer,
            deps.counter,
            deps.clock,
            deps.bus,
            pricing=deps.pricing,
        )

    def _build_chat_model(self) -> Any:
        settings = self._deps.settings
        provider = settings.provider.provider
        if provider == "stub":
            return build_stub_chat_model(clock=self._deps.clock, counter=self._deps.counter)
        # No 'typesafe' branch: Jev is a decision model, reached through the
        # decision port (domain/ports/decision.py, infrastructure/decision/).
        if provider == "openai_compatible":
            base_url = settings.endpoints.openai_base_url.strip()
            api_key = settings.endpoints.openai_api_key.strip()
            if not base_url or not api_key:
                msg = (
                    "provider 'openai_compatible' requires credentials: "
                    "set OPENAI_BASE_URL and OPENAI_API_KEY"
                )
                raise ConfigurationError(msg)
        else:
            msg = f"unknown provider {provider!r}"
            raise ConfigurationError(msg)
        from langchain_openai import ChatOpenAI  # lazy: only real providers need it

        return ChatOpenAI(
            base_url=base_url,
            api_key=api_key,
            model=settings.provider.model,
            temperature=settings.provider.temperature,
            max_tokens=settings.provider.max_output_tokens,
            timeout=settings.provider.timeout_seconds,
            max_retries=settings.provider.max_retries,
        )

    def _collect_tools(self) -> list[Any]:
        tools: list[Any] = []
        seen: set[str] = set(DEEPAGENTS_BUILTIN_TOOL_NAMES)
        for toolset in self._deps.toolsets:
            for tool in toolset.as_langchain_tools():
                name = getattr(tool, "name", "")
                if name in seen:
                    continue
                seen.add(name)
                tools.append(tool)
        return tools

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self, task: str, *, run_id: str | None = None) -> AgentRunResult:
        """Stream one agent turn and report it as events plus a result."""
        bundle = self._bundle
        if bundle is None:
            msg = "run() called before build_agent(); build the graph first"
            raise AgentNotBuiltError(msg)
        if not task.strip():
            msg = f"task must not be empty, got {task!r}"
            raise ConfigurationError(msg)

        resolved_run_id = run_id if run_id is not None else self._deps.identifiers.run_id()
        self._run_id = resolved_run_id
        self._snapshot = None
        self._compactions = 0
        self._interrupt_event.clear()
        self._deps.ledger.reset()
        _set_run_id(bundle.context_middleware, resolved_run_id)
        bundle.tool_middleware.run_id = resolved_run_id  # type: ignore[attr-defined]

        clock = self._deps.clock
        started_at = clock.now()
        start_ms = clock.monotonic_ms()
        self._publish(
            RunStarted(
                at=clock.now(),
                run_id=resolved_run_id,
                task=task,
                model=bundle.model_name,
                policy=bundle.pipeline.name,
            )
        )
        user_message_id = self._deps.identifiers.message_id()
        self._publish(
            MessageAppended(
                at=clock.now(),
                run_id=resolved_run_id,
                message_id=user_message_id,
                role="user",
                chars=len(task),
                preview=task,
            )
        )

        status = RUN_STATUS_COMPLETED
        error: str | None = None
        outcome = _StreamOutcome(final_text="", transcript=())
        try:
            outcome = await self._stream(task, user_message_id)
        except asyncio.CancelledError:
            status = RUN_STATUS_INTERRUPTED
        except CaioCodeError as exc:
            status = RUN_STATUS_ERROR
            error = f"{type(exc).__name__}: {exc}"
        except (OSError, ValueError, RuntimeError) as exc:
            status = RUN_STATUS_ERROR
            error = f"{type(exc).__name__}: {exc}"
        if self._interrupt_event.is_set() and status == RUN_STATUS_COMPLETED:
            status = RUN_STATUS_INTERRUPTED

        accounting = self._deps.ledger.accounting()
        latency_ms = clock.monotonic_ms() - start_ms
        self._publish(
            RunFinished(
                at=clock.now(),
                run_id=resolved_run_id,
                status=status,
                usage=accounting.usage,
                cost=accounting.cost,
                compactions=self._compactions,
                error=error,
            )
        )
        result = AgentRunResult(
            run_id=resolved_run_id,
            status=status,
            final_text=outcome.final_text,
            accounting=accounting,
            board=self._deps.todos.board,
            compactions=self._compactions,
            latency_ms=latency_ms,
            started_at=started_at,
            finished_at=clock.now(),
            transcript=outcome.transcript,
            context=self._snapshot,
            error=error,
        )
        self._last_result = result
        return result

    async def _stream(self, task: str, user_message_id: str) -> _StreamOutcome:
        bundle = self._bundle
        assert bundle is not None  # guaranteed by run()
        self._stream_task = asyncio.create_task(
            self._consume(bundle.graph, task, user_message_id)
        )
        interrupt_waiter = asyncio.create_task(self._interrupt_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {self._stream_task, interrupt_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self._stream_task in done:
                return self._stream_task.result()
            # interrupt() landed first: cancel the stream and report interrupted.
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
            raise asyncio.CancelledError("agent run interrupted")
        finally:
            interrupt_waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await interrupt_waiter
            self._stream_task = None

    async def _consume(self, graph: Any, task: str, user_message_id: str) -> _StreamOutcome:
        run_id = self._run_id
        clock = self._deps.clock
        accumulated: dict[str, str] = {}
        final_text = ""
        final_messages: list[AnyMessage] = []
        inputs = {"messages": [HumanMessage(content=task, id=user_message_id)]}
        async for event in graph.astream_events(inputs, version=ASTREAM_EVENTS_VERSION):
            kind = event.get("event")
            data = event.get("data") or {}
            if kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if isinstance(chunk, AIMessage):
                    text = _message_text(chunk)
                    message_id = chunk.id or ""
                    if message_id and text:
                        accumulated[message_id] = accumulated.get(message_id, "") + text
                        self._publish(
                            MessageAppended(
                                at=clock.now(),
                                run_id=run_id,
                                message_id=message_id,
                                role="assistant",
                                chars=len(accumulated[message_id]),
                                preview=accumulated[message_id],
                            )
                        )
            elif kind == "on_chat_model_end":
                output = data.get("output")
                message = getattr(output, "message", output)
                if not isinstance(message, AIMessage):
                    continue
                text = _message_text(message)
                message_id = message.id or ""
                if text and message_id:
                    accumulated[message_id] = text
                    self._publish(
                        MessageAppended(
                            at=clock.now(),
                            run_id=run_id,
                            message_id=message_id,
                            role="assistant",
                            chars=len(text),
                            preview=text,
                        )
                    )
                    final_text = text
                usage = _token_usage_from_message(message)
                if usage is not None:
                    metadata = getattr(message, "response_metadata", None) or {}
                    model = (
                        metadata.get("model_name")
                        if isinstance(metadata, dict)
                        else None
                    ) or (self._bundle.model_name if self._bundle else STUB_MODEL_NAME)
                    self._publish(
                        UsageRecorded(
                            at=clock.now(),
                            run_id=run_id,
                            usage=usage,
                            cost=self._deps.pricing.cost_of(usage, model),
                            model=model,
                        )
                    )
            elif kind == "on_chain_end":
                output = data.get("output")
                if isinstance(output, dict) and isinstance(output.get("messages"), list):
                    final_messages = list(output["messages"])
        transcript = Transcript.of(
            to_domain(message) for message in final_messages if isinstance(message, BaseMessage)
        )
        records = tuple(message_to_dict(message) for message in transcript)
        return _StreamOutcome(final_text=final_text, transcript=records)

    def interrupt(self) -> None:
        """Cancel the running turn; ``run`` then returns ``"interrupted"``."""
        self._interrupt_event.set()
        task = self._stream_task
        if task is not None and not task.done():
            task.cancel()

    # ------------------------------------------------------------------
    # Tool-call instrumentation (called by _ToolEventMiddleware)
    # ------------------------------------------------------------------

    async def _handle_tool_call(
        self, request: ToolCallRequest, handler: Any, *, is_async: bool
    ) -> Any:
        deps = self._deps
        run_id = self._run_id
        tool_call = request.tool_call
        tool_name = str(tool_call.get("name", ""))
        call_id = str(tool_call.get("id", ""))
        arguments = json.dumps(
            tool_call.get("args") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        self._publish(
            ToolCallIssued(
                at=deps.clock.now(), run_id=run_id, tool=tool_name, arguments=arguments,
                call_id=call_id,
            )
        )

        verdict = deps.guard.inspect(tool_name, arguments, run_id=run_id)
        if getattr(verdict, "fired", False):
            advisory = str(getattr(verdict, "message", "guardrail fired"))
            result: Any = ToolMessage(content=advisory, tool_call_id=call_id, name=tool_name)
            self._finish_tool_call(tool_name, call_id, result, error=None)
            return result

        result = await handler(request) if is_async else handler(request)
        if tool_name == WRITE_TODOS_TOOL_NAME:
            self._update_todos(arguments, run_id=run_id)
        error: str | None = None
        messages = _tool_result_messages(result)
        if messages and getattr(messages[0], "status", None) == "error":
            error = _message_text(messages[0])
        self._finish_tool_call(tool_name, call_id, result, error=error)
        return result

    def _finish_tool_call(
        self, tool_name: str, call_id: str, result: Any, *, error: str | None
    ) -> None:
        deps = self._deps
        text = ""
        for message in _tool_result_messages(result):
            text += _message_text(message)
        truncated = bool(text) and deps.settings.tool_output.placeholder in text
        if text:
            self._publish(
                MessageAppended(
                    at=deps.clock.now(),
                    run_id=self._run_id,
                    message_id=call_id,
                    role="tool",
                    chars=len(text),
                    preview=text,
                )
            )
        self._publish(
            ToolCallCompleted(
                at=deps.clock.now(),
                run_id=self._run_id,
                tool=tool_name,
                call_id=call_id,
                chars=len(text),
                truncated=truncated,
                error=error,
            )
        )

    def _update_todos(self, arguments: str, *, run_id: str) -> None:
        board = self._deps.todos.replace_from_tool_arguments(arguments, run_id=run_id)
        self._publish(
            TodoBoardUpdated(at=self._deps.clock.now(), run_id=run_id, board=board)
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _publish(self, event: DomainEvent) -> None:
        self._deps.bus.publish(event)

    def _on_event(self, event: DomainEvent) -> None:
        if getattr(event, "run_id", None) != self._run_id:
            return
        match event:
            case ContextShaped():
                self._snapshot = ContextSnapshot.from_decision(event.decision)
            case CompactionEnded():
                self._compactions += 1
            case _:
                pass


def _model_name_of(chat_model: Any, settings: Settings) -> str:
    if isinstance(chat_model, StubChatModel):
        return chat_model.stub_name
    if settings.provider.provider == "stub":
        return STUB_MODEL_NAME
    return getattr(chat_model, "model_name", None) or settings.provider.model


def _set_run_id(middleware: Any, run_id: str) -> None:
    """Best-effort: the documented middleware takes ``run_id`` at construction.

    Instances that expose it as a mutable attribute (the fallback does) get the
    current run id so ``ContextShaped`` events carry it; a frozen real
    implementation simply keeps the construction-time value.
    """
    with contextlib.suppress(AttributeError):
        middleware.run_id = run_id


__all__ = [
    "AgentDependencies",
    "AgentNotBuiltError",
    "AgentRunner",
    "LangChainToolset",
]
