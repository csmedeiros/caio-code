"""LangSmith tracing: opt-in, disabled by default, key never printed.

Tracing is enabled only when ``settings.endpoints.tracing_enabled`` (that is, a
``LANGSMITH_API_KEY`` is present). Tests run with tracing off and never need a
key; ``tracing_disabled()`` forces it off for a block even in a traced process.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from caio_code.config import Settings

TRACING_ENV_VAR = "LANGSMITH_TRACING"
API_KEY_ENV_VAR = "LANGSMITH_API_KEY"
PROJECT_ENV_VAR = "LANGSMITH_PROJECT"


def configure_tracing(settings: Settings) -> bool:
    """Enable LangSmith tracing from settings; return whether it was enabled.

    Sets only environment variables the LangSmith SDK reads. The API key is
    passed through the environment, never logged, and never appears in an
    error message.
    """
    if not settings.endpoints.tracing_enabled:
        os.environ[TRACING_ENV_VAR] = "false"
        return False
    os.environ[TRACING_ENV_VAR] = "true"
    os.environ[API_KEY_ENV_VAR] = settings.endpoints.langsmith_api_key
    os.environ[PROJECT_ENV_VAR] = settings.endpoints.langsmith_project
    return True


@contextmanager
def tracing_disabled() -> Iterator[None]:
    """Force tracing off inside the block, restoring the previous state after.

    Used by tests and by offline runs so no code path can phone home by
    accident. Does not depend on the LangSmith SDK being importable.
    """
    from langsmith.run_helpers import tracing_context

    with tracing_context(enabled=False):
        yield
