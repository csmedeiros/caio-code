"""Deterministic offline doubles for the model ports.

The stub is the only provider tests and CI are allowed to use. It never reads
a clock of its own, never touches the network, and produces the same output for
the same input, which is what makes an experiment replayable.

``StubGateway``
    Round-robin replies with optional keyword routing; usage derived from the
    char proxy; latency measured with the injected :class:`Clock`.

``StubSummarizer``
    Builds a well-formed anchored summary by extracting from the prompt, so
    ``parse_summary(result.text).is_well_formed`` is always true.

``StubScorer``
    Lowercased word overlap divided by ``sqrt(len(words))``, ties broken by
    recency (newer messages first).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence

from caio_code.config import CHARS_PER_TOKEN
from caio_code.domain.conversation.messages import Message, Role, ToolCall
from caio_code.domain.conversation.summary import (
    EMPTY_MARKER,
    SECTION_HEADINGS,
    WORK_STATE_SUBSECTIONS,
    parse_summary,
)
from caio_code.domain.errors import ConfigurationError
from caio_code.domain.ports.gateway import ModelGateway, ModelReply, ToolSchema
from caio_code.domain.ports.scorer import RelevanceScorer, ScoredMessage
from caio_code.domain.ports.summarizer import Summarizer, SummaryResult
from caio_code.domain.ports.time import Clock
from caio_code.domain.usage.accounting import TokenUsage
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

USER_LINE_PREFIX = "[User]:"
STUB_SCORER_NAME = "stub"
SUMMARY_PROMPT_MESSAGE_ID = "stub-summary-prompt"

_DETAIL_LINE_RE = re.compile(r"[\d=/'\"]")
_PATH_TOKEN_RE = re.compile(
    r"(?:[\w.-]+/)+[\w.-]+|\b[\w-]+\.(?:py|md|json|toml|ya?ml|txt|tex|cfg|sh|js|ts)\b"
)
_WORD_RE = re.compile(r"[a-z0-9_]+")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _conversation_lines(prompt: str) -> list[str]:
    """Lines of the <conversation> block, or of the whole prompt when absent."""
    lines = prompt.splitlines()
    start = end = None
    for position, line in enumerate(lines):
        if line.strip() == "<conversation>" and start is None:
            start = position
        elif line.strip() == "</conversation>" and start is not None:
            end = position
            break
    if start is None or end is None:
        return _nonempty_lines(prompt)
    return [line.strip() for line in lines[start + 1 : end] if line.strip()]


def _bullets(items: Sequence[str]) -> str:
    if not items:
        return f"- {EMPTY_MARKER}"
    return "\n".join(f"- {item}" for item in items)


class StubGateway(ModelGateway):
    """Deterministic gateway: canned replies, char-proxy usage, clock latency."""

    def __init__(
        self,
        *,
        clock: Clock,
        replies: Sequence[str] = (),
        keyword_replies: Mapping[str, str] | None = None,
        keyword_tool_calls: Mapping[str, Sequence[ToolCall]] | None = None,
        cached_input_fraction: float = 0.0,
        model: str = "stub",
    ) -> None:
        if not 0.0 <= cached_input_fraction <= 1.0:
            msg = f"cached_input_fraction must be in [0, 1], got {cached_input_fraction}"
            raise ConfigurationError(msg)
        self._clock = clock
        self._replies = tuple(replies)
        self._keyword_replies = dict(keyword_replies or {})
        self._keyword_tool_calls = {
            keyword: tuple(calls) for keyword, calls in (keyword_tool_calls or {}).items()
        }
        self._cached_input_fraction = cached_input_fraction
        self._model = model
        self._counter = CharProxyTokenCounter(chars_per_token=CHARS_PER_TOKEN)
        self._next_reply = 0
        self._served_tool_keywords: set[str] = set()

    @property
    def model(self) -> str:
        return self._model

    def _pick_reply(self, messages: Sequence[Message]) -> str:
        last_user = self._last_user_text(messages)
        for keyword in sorted(self._keyword_replies):
            if keyword in last_user:
                return self._keyword_replies[keyword]
        if not self._replies:
            return ""
        reply = self._replies[self._next_reply % len(self._replies)]
        self._next_reply += 1
        return reply

    def _pick_tool_calls(
        self, messages: Sequence[Message], tools: Sequence[ToolSchema] | None
    ) -> tuple[ToolCall, ...]:
        """Scripted tool calls, keyed on the last user message.

        Only offered when the caller actually passed tool schemas: a scripted
        call to a tool that is not on the round's surface would be a call the
        real provider could never make. A keyword hit fires once; after the tool
        result is appended the last user text is unchanged, so the routing
        remembers which keywords were already served.
        """
        if not tools or not self._keyword_tool_calls:
            return ()
        available = {tool.name for tool in tools}
        last_user = self._last_user_text(messages)
        for keyword in sorted(self._keyword_tool_calls):
            if keyword in last_user and keyword not in self._served_tool_keywords:
                calls = tuple(
                    call for call in self._keyword_tool_calls[keyword] if call.name in available
                )
                if calls:
                    self._served_tool_keywords.add(keyword)
                    return calls
        return ()

    @staticmethod
    def _last_user_text(messages: Sequence[Message]) -> str:
        return next(
            (message.text for message in reversed(messages) if message.role is Role.USER),
            "",
        )

    def _reply(
        self,
        messages: Sequence[Message],
        *,
        system: str | None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> ModelReply:
        started_at = self._clock.monotonic_ms()
        tool_calls = self._pick_tool_calls(messages, tools)
        text = "" if tool_calls else self._pick_reply(messages)
        input_tokens = self._counter.count_messages(messages) + self._counter.count_text(
            system or ""
        )
        cached = min(input_tokens, math.floor(input_tokens * self._cached_input_fraction))
        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=self._counter.count_text(text),
            cached_input_tokens=cached,
        )
        latency_ms = self._clock.monotonic_ms() - started_at
        return ModelReply(
            text=text,
            usage=usage,
            model=self._model,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
            raw={"stub": True},
        )

    async def acomplete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> ModelReply:
        return self._reply(messages, system=system, tools=tools)

    def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> ModelReply:
        return self._reply(messages, system=system, tools=tools)


class StubJudgeGateway(ModelGateway):
    """Offline stand-in for the judge model: substring match on gold/aliases.

    Parses the JSON payload embedded in the judge prompt and returns
    ``correct: true`` for every item whose reply mentions the gold answer or an
    alias (case-insensitive). Deterministic by construction; it exercises the
    harness plumbing, not judge quality -- a live run still requires the
    calibration gate against hand-labelled answers.
    """

    def __init__(self, *, clock: Clock, model: str = "stub-judge") -> None:
        self._clock = clock
        self._model = model
        self._counter = CharProxyTokenCounter(chars_per_token=CHARS_PER_TOKEN)

    @property
    def model(self) -> str:
        return self._model

    def _reply(self, messages: Sequence[Message], *, system: str | None) -> ModelReply:
        started_at = self._clock.monotonic_ms()
        prompt = next(
            (message.text for message in reversed(messages) if message.role is Role.USER),
            "",
        )
        text = _stub_judge_verdicts(prompt)
        input_tokens = self._counter.count_messages(messages) + self._counter.count_text(
            system or ""
        )
        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=self._counter.count_text(text),
        )
        return ModelReply(
            text=text,
            usage=usage,
            model=self._model,
            latency_ms=self._clock.monotonic_ms() - started_at,
            raw={"stub_judge": True},
        )

    async def acomplete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> ModelReply:
        return self._reply(messages, system=system)

    def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> ModelReply:
        return self._reply(messages, system=system)


def _stub_judge_verdicts(prompt: str) -> str:
    """Grade the embedded payload by case-insensitive substring match."""
    items = _extract_payload_items(prompt)
    verdicts = []
    for item in items:
        reply = str(item.get("agent_reply", "")).lower()
        accepted = [str(item.get("gold_answer", "")), *item.get("aliases", [])]
        correct = any(answer.strip() and answer.strip().lower() in reply for answer in accepted)
        verdicts.append(
            {
                "probe_id": str(item.get("probe_id", "")),
                "correct": correct,
                "reason": "stub substring match on gold/aliases",
            }
        )
    return json.dumps({"verdicts": verdicts}, sort_keys=True)


def _extract_payload_items(prompt: str) -> list[dict]:
    decoder = json.JSONDecoder()
    start = prompt.find("[")
    while start != -1:
        try:
            parsed, _ = decoder.raw_decode(prompt, start)
        except json.JSONDecodeError:
            start = prompt.find("[", start + 1)
            continue
        if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
            return parsed
        start = prompt.find("[", start + 1)
    return []


def build_stub_summary(prompt: str) -> str:
    """Extract a well-formed anchored summary from a compaction prompt.

    Deterministic by construction: the Objective comes from the first
    ``[User]:`` line, Important Details from lines carrying digits, paths,
    ``=`` or quotes, Relevant Files from path-looking tokens, and Next Move
    from the last non-empty line. Everything else is ``(none)``.
    """
    lines = _conversation_lines(prompt)

    objective = EMPTY_MARKER
    for line in lines:
        if line.startswith(USER_LINE_PREFIX):
            objective = line[len(USER_LINE_PREFIX) :].strip() or EMPTY_MARKER
            break

    details: list[str] = []
    seen_details: set[str] = set()
    for line in lines:
        if line.startswith(("#", "<")):
            continue
        if _DETAIL_LINE_RE.search(line) and line not in seen_details:
            seen_details.add(line)
            details.append(line)

    files: list[str] = []
    seen_files: set[str] = set()
    for line in lines:
        for token in _PATH_TOKEN_RE.findall(line):
            if token not in seen_files:
                seen_files.add(token)
                files.append(f"{token}: referenced in the conversation")

    next_move = lines[-1] if lines else EMPTY_MARKER

    sections: list[str] = []
    for heading in SECTION_HEADINGS:
        sections.append(f"## {heading}")
        if heading == "Objective":
            sections.append(_bullets([objective]))
        elif heading == "Important Details":
            sections.append(_bullets(details))
        elif heading == "Work State":
            for sub in WORK_STATE_SUBSECTIONS:
                sections.append(f"### {sub}")
                sections.append(f"- {EMPTY_MARKER}")
        elif heading == "Next Move":
            sections.append(f"1. {next_move}")
        elif heading == "Relevant Files":
            sections.append(_bullets(files))
    return "\n".join(sections)


class StubSummarizer(Summarizer):
    """Deterministic summarizer that always returns a well-formed summary."""

    def __init__(self, *, model: str = "stub", clock: Clock | None = None) -> None:
        self._model = model
        self._clock = clock
        self._counter = CharProxyTokenCounter(chars_per_token=CHARS_PER_TOKEN)

    def _summarize(self, prompt: str, *, max_tokens: int) -> SummaryResult:
        started_at = self._clock.monotonic_ms() if self._clock is not None else 0
        # max_tokens is accepted for port compatibility but never truncates the
        # stub output: a truncated summary would break the well-formedness
        # invariant every caller relies on.
        text = build_stub_summary(prompt)
        usage = TokenUsage(
            input_tokens=self._counter.count_text(prompt),
            output_tokens=self._counter.count_text(text),
        )
        latency_ms = 0
        if self._clock is not None:
            latency_ms = self._clock.monotonic_ms() - started_at
        return SummaryResult(
            text=text,
            model=self._model,
            usage=usage,
            latency_ms=latency_ms,
        )

    async def asummarize(self, prompt: str, *, max_tokens: int) -> SummaryResult:
        return self._summarize(prompt, max_tokens=max_tokens)

    def summarize(self, prompt: str, *, max_tokens: int) -> SummaryResult:
        return self._summarize(prompt, max_tokens=max_tokens)


class StubScorer(RelevanceScorer):
    """Lexical overlap scorer: deterministic, offline, one entry per message."""

    def __init__(self, *, name: str = STUB_SCORER_NAME) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def _score(self, *, task: str, messages: Sequence[Message]) -> list[ScoredMessage]:
        task_words = set(_words(task))
        scored = [
            ScoredMessage(index=index, score=self._score_one(task_words, message), message=message)
            for index, message in enumerate(messages)
        ]
        # Ties break by recency: equal scores put the newer message first.
        return sorted(scored, key=lambda item: (-item.score, -item.index))

    @staticmethod
    def _score_one(task_words: set[str], message: Message) -> float:
        words = _words(message.text)
        if not words:
            return 0.0
        overlap = len(task_words.intersection(words))
        return overlap / math.sqrt(len(words))

    async def ascore(
        self,
        *,
        task: str,
        messages: Sequence[Message],
    ) -> Sequence[ScoredMessage]:
        return self._score(task=task, messages=messages)

    def score(
        self,
        *,
        task: str,
        messages: Sequence[Message],
    ) -> Sequence[ScoredMessage]:
        return self._score(task=task, messages=messages)


def summary_is_well_formed(result: SummaryResult) -> bool:
    """Convenience check used by tests and by the compaction use case."""
    return parse_summary(result.text).is_well_formed
