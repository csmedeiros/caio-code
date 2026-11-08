"""Command-line entry point: ``python -m caio_code`` / ``caio-code``.

The only module in the package that reads ``sys.argv``, prints to stdout and
produces the process exit code. Subcommands delegate to
:mod:`caio_code.presentation.cli.commands`; typed errors become a one-line
stderr message and a non-zero exit instead of a traceback.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from caio_code.config import DEFAULT_AGENT_MODEL
from caio_code.domain.errors import CaioCodeError
from caio_code.presentation.cli.commands import (
    classify_command,
    compact_command,
    doctor_command,
    evaluate_command,
    run_command,
    tui_command,
)
from caio_code.presentation.cli.commands.classify import DECISION_PROVIDER_CHOICES
from caio_code.presentation.cli.composition import POLICY_NAMES

EXIT_OK = 0
EXIT_FAILURE = 1

PROVIDER_CHOICES: tuple[str, ...] = ("stub", "openai_compatible")
DEFAULT_POLICY = "sliding_window"
DEFAULT_CASES = 5
DEFAULT_REPETITIONS = 1

CommandHandler = Callable[[argparse.Namespace], int]


def _add_provider_options(parser: argparse.ArgumentParser, *, with_model: bool = False) -> None:
    parser.add_argument(
        "--provider",
        choices=PROVIDER_CHOICES,
        default=None,
        help="LLM provider (default: stub, or CAIO_CODE_PROVIDER)",
    )
    if with_model:
        parser.add_argument(
            "--model", default=None, help=f"model name (default: {DEFAULT_AGENT_MODEL})"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caio-code",
        description="caio-code: a context-engineered coding agent (TCC prototype).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="one headless agent run")
    run.add_argument("--task", required=True, help="the task the agent must complete")
    run.add_argument("--root", default=None, help="workspace root (default: cwd)")
    _add_provider_options(run, with_model=True)
    run.add_argument("--policy", choices=POLICY_NAMES, default=DEFAULT_POLICY)
    run.add_argument("--window-tokens", type=int, default=None, help="declared window in tokens")
    run.add_argument("--json", default=None, metavar="OUT", help="write the run record as JSON")
    run.set_defaults(handler=run_command)

    tui = subparsers.add_parser("tui", help="launch the terminal interface")
    tui.add_argument("--root", default=None, help="workspace root (default: cwd)")
    _add_provider_options(tui)
    tui.add_argument("--policy", choices=POLICY_NAMES, default=DEFAULT_POLICY)
    tui.add_argument(
        "--demo", action="store_true", help="replay the scripted demo instead of a live agent"
    )
    tui.set_defaults(handler=tui_command)

    compact = subparsers.add_parser("compact", help="compact a stored transcript once")
    compact.add_argument("--transcript", required=True, help="JSON transcript envelope file")
    compact.add_argument(
        "--keep-tokens", type=int, default=None, help="verbatim tail kept by the compaction"
    )
    _add_provider_options(compact)
    compact.add_argument("--out", default=None, metavar="FILE", help="write the summary to FILE")
    compact.set_defaults(handler=compact_command)

    evaluate = subparsers.add_parser("evaluate", help="run the experiment arms")
    evaluate.add_argument("--arms", default=None, help="comma-separated policy arms")
    evaluate.add_argument("--cases", type=int, default=DEFAULT_CASES)
    evaluate.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    _add_provider_options(evaluate, with_model=True)
    evaluate.add_argument("--out", default=None, metavar="DIR", help="reports directory")
    evaluate.add_argument("--run-id", default=None, help="name of the run directory under --out")
    evaluate.add_argument(
        "--concurrency", type=int, default=1, help="trials in flight (default: 1)"
    )
    evaluate.add_argument(
        "--window-tokens", type=int, default=None, help="declared window in tokens"
    )
    evaluate.add_argument(
        "--variants",
        default=None,
        help=(
            "comma-separated case variants (full,spill); runs the chat-replay "
            "evaluation instead of the frozen-history experiment"
        ),
    )
    evaluate.set_defaults(handler=evaluate_command)

    classify = subparsers.add_parser(
        "classify", help="send one state to the decision model (Jev) and print the answers"
    )
    classify.add_argument("--state", required=True, help="the state string to classify")
    classify.add_argument(
        "--provider",
        choices=DECISION_PROVIDER_CHOICES,
        default=None,
        help="decision provider (default: CAIO_CODE_DECISION_PROVIDER, else stub)",
    )
    classify.add_argument(
        "--noul",
        action="append",
        default=[],
        metavar="ID=QUESTION",
        help="yes/no question, answered with the probability of yes (repeatable)",
    )
    classify.add_argument(
        "--choice",
        action="append",
        default=[],
        metavar="ID=QUESTION|label=desc|label=desc",
        help="categorical question with at least two labels (repeatable)",
    )
    classify.add_argument(
        "--score",
        action="append",
        default=[],
        metavar="ID=QUESTION|level0|level1",
        help="ordinal question with at least two ordered levels (repeatable)",
    )
    classify.set_defaults(handler=classify_command)

    doctor = subparsers.add_parser("doctor", help="report resolved settings and health")
    doctor.add_argument("--json", action="store_true", help="machine-readable report")
    _add_provider_options(doctor)
    doctor.set_defaults(handler=doctor_command)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` (default ``sys.argv[1:]``), dispatch, return the exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: CommandHandler = args.handler
    try:
        return handler(args)
    except CaioCodeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    except (OSError, ValueError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILURE


__all__ = ["build_parser", "main"]
