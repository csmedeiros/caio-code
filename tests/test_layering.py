"""The dependency rule and the determinism rule, checked by AST.

ADR 0003 states the layering; this test is what keeps it true. It reads every
module under ``src/caio_code`` and fails on an import that crosses the rule, on
a third-party package inside the domain, and on a wall-clock or random call
outside the single module allowed to read one.

The one deliberate exception is encoded, not hidden: ``application`` may import
``infrastructure`` (the agent runner needs the mappers and the deepagents
backend), and ``presentation`` may import anything below it. Nothing else.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "caio_code"

ALLOWED_IMPORTS: dict[str, set[str]] = {
    "domain": set(),
    "application": {"domain", "infrastructure"},
    "infrastructure": {"domain"},
    "presentation": {"domain", "application", "infrastructure"},
}
LAYERS = tuple(ALLOWED_IMPORTS)

STDLIB_PREFIXES = frozenset(sys.stdlib_module_names)
"""Stdlib names of the running interpreter: the domain may import these only."""

DETERMINISM_ALLOWLIST = {
    # SystemClock is the only place that reads a wall clock, and only the
    # composition root may build one.
    Path("infrastructure/observability/clocks.py"),
}
WATCHED_LIMITS = frozenset({8_000, 20_000, 51_200, 2_000, 128_000})
"""Values Chapter 4 reports; a second copy of one of them is a bug waiting to drift."""

FORBIDDEN_CALLS = frozenset(
    {
        "time.time",
        "time.monotonic",
        "time.perf_counter",
        "datetime.now",
        "datetime.utcnow",
        "datetime.today",
        "uuid.uuid4",
        "uuid.uuid1",
        "random.random",
        "random.randint",
        "random.choice",
        "random.shuffle",
        "random.sample",
    }
)


def modules() -> Iterator[Path]:
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts or "egg-info" in path.parts:
            continue
        yield path


def layer_of(path: Path) -> str | None:
    relative = path.relative_to(PACKAGE)
    top = relative.parts[0]
    return top if top in LAYERS else None


def imported_modules(tree: ast.AST) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.lineno, node.module


def test_no_import_crosses_the_dependency_rule() -> None:
    violations: list[str] = []
    for path in modules():
        layer = layer_of(path)
        if layer is None:
            continue
        allowed = ALLOWED_IMPORTS[layer] | {layer}
        for lineno, module in imported_modules(ast.parse(path.read_text(encoding="utf-8"))):
            if not module.startswith("caio_code."):
                continue
            parts = module.split(".")
            if len(parts) < 2:
                continue
            target = parts[1]
            if target in LAYERS and target not in allowed:
                violations.append(
                    f"{path.relative_to(ROOT)}:{lineno}: {layer} must not import {module}"
                )
    assert not violations, "dependency rule broken:\n" + "\n".join(violations)


def test_domain_imports_no_third_party_package() -> None:
    offenders: list[str] = []
    for path in modules():
        if layer_of(path) != "domain":
            continue
        for lineno, module in imported_modules(ast.parse(path.read_text(encoding="utf-8"))):
            root_name = module.split(".")[0]
            if root_name in {"caio_code", "__future__"} or root_name in STDLIB_PREFIXES:
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {module}")
    assert not offenders, (
        "the domain must stay free of SDKs so a policy can be tested with plain data:\n"
        + "\n".join(offenders)
    )


def test_presentation_is_not_imported_by_anything_below_it() -> None:
    offenders: list[str] = []
    for path in modules():
        layer = layer_of(path)
        if layer in {None, "presentation"}:
            continue
        for lineno, module in imported_modules(ast.parse(path.read_text(encoding="utf-8"))):
            if module.startswith("caio_code.presentation"):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {module}")
    assert not offenders, "presentation must stay a leaf:\n" + "\n".join(offenders)


def test_no_wall_clock_or_random_outside_the_allowlist() -> None:
    offenders: list[str] = []
    for path in modules():
        if path.relative_to(PACKAGE) in DETERMINISM_ALLOWLIST:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            try:
                name = ast.unparse(node)
            except Exception:  # pragma: no cover - defensive: unparsing a valid tree works
                continue
            if name in FORBIDDEN_CALLS:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
        # `import random` / `from random import ...` is fine only through random.Random(seed)
        for lineno, module in imported_modules(tree):
            if module == "random" or module.startswith("random."):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: import {module}")
    assert not offenders, (
        "a run that cannot be replayed cannot be reported; inject a Clock or a seeded Random:\n"
        + "\n".join(offenders)
    )


def test_config_holds_the_numbers() -> None:
    """Limits inside a function body are magic numbers; named defaults are not.

    A dataclass field default (``max_lines: int = 2_000``) and a module constant
    are documented values that mirror config on purpose. The same literal inline
    in a branch is not: it drifts from the value the experiment reports.
    """
    offenders: list[str] = []
    for path in modules():
        if path.name == "config.py" or layer_of(path) is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in _functions(tree):
            for node in ast.walk(function):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, int):
                    continue
                if node.value not in WATCHED_LIMITS:
                    continue
                if _in_defaults(function, node):
                    continue
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.value}")
    assert not offenders, (
        "these limits belong to config.py or to a named default; inline they drift from the "
        "measured value:\n" + "\n".join(offenders)
    )


def _functions(tree: ast.AST) -> Iterator[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def _in_defaults(function: ast.AST, node: ast.Constant) -> bool:
    arguments = function.args  # type: ignore[attr-defined]
    defaults = [*arguments.defaults, *(item for item in arguments.kw_defaults if item)]
    return any(
        default.lineno <= node.lineno <= (default.end_lineno or node.lineno)
        for default in defaults
    )
