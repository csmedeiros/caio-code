"""Typed errors. Every failure the agent can produce has a class here.

Bare ``Exception`` and ``except: pass`` are forbidden in this repository: an
experiment that swallows an error measures nothing. Each error carries the
offending value in its message so a log line is enough to diagnose it.
"""

from __future__ import annotations


class CaioCodeError(Exception):
    """Base class for every error raised by the agent."""


class ConfigurationError(CaioCodeError):
    """A setting is missing, malformed, or contradictory."""


class ContextBudgetError(CaioCodeError):
    """A budget or limit was built with a value that cannot work."""


class ContextOverflowError(CaioCodeError):
    """The transcript does not fit the declared window and the arm forbids shaping.

    This is a *result*, not a bug: the baseline arm raises it on purpose so the
    cost of managing no context is measured instead of hidden.
    """

    def __init__(self, *, required: int, limit: int, policy: str) -> None:
        self.required = required
        self.limit = limit
        self.policy = policy
        super().__init__(
            f"context overflow: {required} tokens required, {limit} allowed "
            f"(policy {policy!r} keeps everything)"
        )


class ProviderError(CaioCodeError):
    """A model call failed: network, auth, rate limit, or malformed response."""


class SummarizerError(ProviderError):
    """The compaction summarizer returned nothing usable."""


class ToolError(CaioCodeError):
    """A tool refused or failed. Returned to the model as structured text."""


class SandboxEscapeError(ToolError):
    """A tool tried to act outside its root."""


class ToolUnavailableInReplay(ToolError):
    """A probe-round tool call has no recorded interaction to replay.

    This is a *visible* miss: the replay tool server returns its message to the
    model as the tool result and counts it, so a retention number that was
    driven by misses is legible in the report instead of hidden.
    """


class GuardrailTriggered(CaioCodeError):
    """A guardrail stopped the loop (repeated call, runaway cost)."""


class EvaluationError(CaioCodeError):
    """The evaluation harness could not run a case or score an answer."""


class DatasetError(EvaluationError):
    """An eval dataset is missing, empty, or internally inconsistent."""


class StorageError(CaioCodeError):
    """A transcript or result could not be persisted."""
