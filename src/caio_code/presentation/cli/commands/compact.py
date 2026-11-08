"""``caio-code compact``: one compaction of a stored transcript."""

from __future__ import annotations

import asyncio
from argparse import Namespace
from pathlib import Path
from typing import Any

from caio_code.config import load_settings
from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.summary import parse_summary
from caio_code.domain.errors import ConfigurationError
from caio_code.domain.events import InMemoryEventBus
from caio_code.domain.policy.base import PolicyRequest
from caio_code.domain.policy.compaction import CompactionPlanner
from caio_code.infrastructure.llm.factory import build_summarizer
from caio_code.infrastructure.observability.clocks import (
    SequentialIdentifiers,
    SystemClock,
)
from caio_code.infrastructure.persistence.codec import transcript_from_json
from caio_code.infrastructure.pricing.sheet import pricing_for
from caio_code.infrastructure.tokens.counter import build_counter
from caio_code.presentation.cli.formatting import format_summary_block

EXIT_OK = 0


def compact_command(args: Namespace) -> int:
    settings = load_settings(provider=args.provider)
    path = Path(args.transcript)
    if not path.is_file():
        msg = f"transcript file not found: {str(path)!r}"
        raise ConfigurationError(msg)
    transcript = transcript_from_json(path.read_text(encoding="utf-8"), source=str(path))

    clock = SystemClock()
    bus = InMemoryEventBus()
    identifiers = SequentialIdentifiers()
    run_id = identifiers.run_id()
    counter = build_counter(
        settings.tokens.counter,
        chars_per_token=settings.tokens.chars_per_token,
        encoding=settings.tokens.tiktoken_encoding,
    )
    keep_tokens = (
        args.keep_tokens if args.keep_tokens is not None else settings.compaction.keep_tokens
    )
    planner = CompactionPlanner(
        keep_tokens=keep_tokens,
        tool_result_char_cap=settings.compaction.tool_result_char_cap,
    )
    request = PolicyRequest(
        transcript=transcript,
        budget=TokenBudget(settings.window.tokens),
        counter=counter,
        tool_result_char_cap=settings.compaction.tool_result_char_cap,
    )
    decision = planner.plan(request)
    if not decision.detail.get("compacted"):
        print("nothing to compact: the transcript fits the verbatim tail")
        return EXIT_OK

    summarizer = build_summarizer(settings, clock=clock)
    pricing = pricing_for(settings)
    summary_text, usage, cost, well_formed = _summarize(
        args,
        settings=settings,
        bus=bus,
        clock=clock,
        counter=counter,
        summarizer=summarizer,
        pricing=pricing,
        request=request,
        decision=decision,
        run_id=run_id,
    )

    block = format_summary_block(
        summary_text, cost_usd=cost.rounded, usage=usage, well_formed=well_formed
    )
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(block + "\n", encoding="utf-8")
        print(f"summary written to {args.out}")
    else:
        print(block)
    return EXIT_OK


def _summarize(
    args: Namespace,
    *,
    settings: Any,
    bus: Any,
    clock: Any,
    counter: Any,
    summarizer: Any,
    pricing: Any,
    request: PolicyRequest,
    decision: Any,
    run_id: str,
) -> tuple[str, Any, Any, bool]:
    """Prefer the real CompactionService; fall back to the summarizer port."""
    try:
        from caio_code.application.compaction.service import CompactionService
    except ImportError:
        CompactionService = None  # type: ignore[assignment]

    if CompactionService is not None:
        service = CompactionService(summarizer, counter, clock, bus, pricing=pricing)
        outcome = asyncio.run(
            service.compact(
                transcript=request.transcript,
                request=request,
                decision=decision,
                run_id=run_id,
                reason="manual",
            )
        )
        return (
            outcome.summary.render(),
            outcome.usage,
            outcome.cost,
            bool(outcome.well_formed),
        )

    prompt = str(decision.injected[0].metadata.get("compaction_prompt", ""))
    if not prompt:
        msg = "compaction decision carries no summarizer prompt"
        raise ConfigurationError(msg)
    result = summarizer.summarize(prompt, max_tokens=settings.compaction.summary_max_tokens)
    summary = parse_summary(result.text)
    return (
        summary.render(),
        result.usage,
        pricing.cost_of(result.usage, result.model),
        summary.is_well_formed,
    )


__all__ = ["compact_command"]
