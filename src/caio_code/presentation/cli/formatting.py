"""Output formatting shared by the CLI commands.

Printing stays dumb: pure functions from records to strings, plus the JSON
writer. No command formats its own numbers twice in different shapes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from caio_code.application.agent.session import AgentRunResult

PERCENT_FACTOR = 100.0


def format_ratio(ratio: float) -> str:
    return f"{ratio * PERCENT_FACTOR:.1f}%"


def format_metrics(result: AgentRunResult) -> str:
    """The metrics block printed after a headless run."""
    usage = result.accounting.usage
    cache = result.accounting.cache
    cost = result.accounting.cost
    lines = [
        "metrics:",
        f"  run_id: {result.run_id}",
        f"  status: {result.status}",
        f"  model: {result.accounting.model}",
        f"  tokens_in: {usage.input_tokens}",
        f"  tokens_out: {usage.output_tokens}",
        f"  tokens_cached: {usage.cached_input_tokens}",
        f"  cache_hit: {format_ratio(cache.hit_ratio)}",
        f"  cost_usd: {cost.rounded}",
        f"  compactions: {result.compactions}",
        f"  latency_ms: {result.latency_ms}",
    ]
    context = result.context
    if context is not None:
        lines.append(
            f"  context: {context.policy} {context.tokens_before} -> {context.tokens_after}"
            f" / {context.budget_tokens} budget, overflow {context.overflow_tokens},"
            f" kept {context.kept}, dropped {context.dropped}"
        )
    if result.error is not None:
        lines.append(f"  error: {result.error}")
    return "\n".join(lines)


def format_summary_block(text: str, *, cost_usd: Any, usage: Any, well_formed: bool) -> str:
    lines = [
        "compaction summary:",
        text.strip(),
        "",
        f"well_formed: {well_formed}",
        f"tokens_in: {usage.input_tokens}",
        f"tokens_out: {usage.output_tokens}",
        f"cost_usd: {cost_usd}",
    ]
    return "\n".join(lines)


def write_json(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(record), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


__all__ = ["format_metrics", "format_ratio", "format_summary_block", "write_json"]
