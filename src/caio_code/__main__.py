"""``python -m caio_code``: delegate to the CLI entry point."""

from __future__ import annotations

import sys

from caio_code.presentation.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
