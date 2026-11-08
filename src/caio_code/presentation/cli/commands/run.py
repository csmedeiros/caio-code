"""``caio-code run``: one headless agent run with a metrics report."""

from __future__ import annotations

import asyncio
from argparse import Namespace
from pathlib import Path
from typing import Any

from caio_code.application.agent.session import RUN_STATUS_COMPLETED
from caio_code.presentation.cli.composition import build_runner, load_cli_settings
from caio_code.presentation.cli.formatting import format_metrics, write_json

EXIT_OK = 0
EXIT_RUN_FAILED = 1


def run_command(args: Namespace) -> int:
    settings = load_cli_settings(args, with_model=True, with_window=True, with_root=True)
    runner = build_runner(settings, policy_name=args.policy)
    result = asyncio.run(runner.run(args.task))

    print(result.final_text or "(the run produced no final text)")
    print()
    print(format_metrics(result))

    if args.json:
        record: dict[str, Any] = result.as_record()
        write_json(Path(args.json), record)
        print(f"record written to {args.json}")

    return EXIT_OK if result.status == RUN_STATUS_COMPLETED else EXIT_RUN_FAILED


__all__ = ["run_command"]
