"""Domain layer: the model of the problem, with no dependency outside itself.

Everything here is pure data and pure functions. No SDK, no file, no clock, no
network. If a test needs a fixture to exercise something in this package, the
fixture is plain Python.
"""

from __future__ import annotations

__all__: list[str] = []
