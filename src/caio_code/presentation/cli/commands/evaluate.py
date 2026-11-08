"""``caio-code evaluate``: thin wrapper over the experiment runner.

The experiment package is being written in parallel; the import is lazy and a
missing module is a typed :class:`ConfigurationError`, never an ImportError
traceback at the user.
"""

from __future__ import annotations

from argparse import Namespace
from typing import Any

from caio_code.config import load_settings
from caio_code.domain.errors import ConfigurationError

EXIT_OK = 0
EXPERIMENT_ENTRY_POINTS: tuple[str, ...] = ("main", "run_experiment", "run")


def evaluate_command(args: Namespace) -> int:
    variants = getattr(args, "variants", None)
    if variants:
        return _replay_command(args, variants)
    try:
        from caio_code.application.experiment import runner as experiment
    except ImportError as exc:
        msg = (
            "the experiment runner caio_code.application.experiment.runner is not "
            f"available yet: {exc}"
        )
        raise ConfigurationError(msg) from exc

    settings = load_settings(
        provider=args.provider,
        model=getattr(args, "model", None),
        window_tokens=args.window_tokens,
    )
    options: dict[str, Any] = {
        "settings": settings,
        "arms": tuple(args.arms.split(",")) if args.arms else None,
        "cases": args.cases,
        "repetitions": args.repetitions,
        "out": args.out,
        "concurrency": args.concurrency,
        "run_id": args.run_id,
        "window_tokens": args.window_tokens,
    }
    for name in EXPERIMENT_ENTRY_POINTS:
        entry = getattr(experiment, name, None)
        if callable(entry):
            result = entry(**options)
            return EXIT_OK if result is None or result == EXIT_OK else int(result)
    msg = (
        "caio_code.application.experiment.runner exposes none of "
        f"{EXPERIMENT_ENTRY_POINTS}; cannot delegate the evaluation"
    )
    raise ConfigurationError(msg)


def _replay_command(args: Namespace, variants: str) -> int:
    """``--variants`` routes to the chat-replay evaluation (Chapter 4, v5)."""
    try:
        from caio_code.application.evaluation import replay
    except ImportError as exc:
        msg = f"the chat-replay runner is not available: {exc}"
        raise ConfigurationError(msg) from exc

    settings = load_settings(
        provider=args.provider,
        model=getattr(args, "model", None),
        window_tokens=args.window_tokens,
    )
    resolved = replay.resolve_variants(tuple(variants.split(",")))
    return replay.main(
        settings=settings,
        arms=tuple(args.arms.split(",")) if args.arms else None,
        variants=resolved,
        cases=args.cases,
        repetitions=args.repetitions,
        out=args.out,
        concurrency=args.concurrency,
        run_id=args.run_id,
    )


__all__ = ["evaluate_command"]
