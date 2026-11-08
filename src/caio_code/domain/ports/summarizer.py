"""Summarizer port: the only way the domain asks a model to write a summary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from caio_code.domain.usage.accounting import TokenUsage


@dataclass(frozen=True, slots=True)
class SummaryResult:
    """Raw summary text plus what producing it cost."""

    text: str
    model: str
    usage: TokenUsage
    latency_ms: int = 0

    @property
    def is_usable(self) -> bool:
        return bool(self.text.strip())


@runtime_checkable
class Summarizer(Protocol):
    """Turns a compaction prompt into an anchored summary."""

    async def asummarize(self, prompt: str, *, max_tokens: int) -> SummaryResult:
        """Summarize asynchronously. Implementations must not raise on empty output."""

    def summarize(self, prompt: str, *, max_tokens: int) -> SummaryResult:
        """Synchronous variant, used by the CLI and by tests."""
