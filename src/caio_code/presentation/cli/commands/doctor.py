"""``caio-code doctor``: resolved configuration and environment health.

Reports which credentials exist **by name only** (values are never printed),
whether each provider is usable, the decision-model configuration, the eval
dataset, the token counter and the price entries of the chosen model. Exits
non-zero when the requested chat provider cannot run for lack of credentials,
or when the decision provider is ``typesafe`` without ``TYPESAFE_API_KEY``.
"""

from __future__ import annotations

import importlib
import json
import os
from argparse import Namespace
from typing import Any

from caio_code.config import Settings, load_settings
from caio_code.domain.errors import CaioCodeError
from caio_code.infrastructure.tokens.counter import build_counter

EXIT_OK = 0
EXIT_UNUSABLE_PROVIDER = 1

REPORTED_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "TYPESAFE_API_KEY",
    "TYPESAFE_BASE_URL",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "CAIO_CODE_PROVIDER",
    "CAIO_CODE_MODEL",
    "CAIO_CODE_DECISION_PROVIDER",
    "CAIO_CODE_WINDOW_TOKENS",
)
PROVIDERS: tuple[str, ...] = ("stub", "openai_compatible")
"""Chat providers. TypeSafe is not one: Jev is a decision model (ADR 0005)."""

DECISION_SDK_MODULE = "langchain_typesafe"


def _provider_usable(settings: Settings, provider: str) -> tuple[bool, str]:
    if provider == "stub":
        return True, "offline deterministic provider; no credentials needed"
    if provider == "openai_compatible":
        ok = bool(
            settings.endpoints.openai_base_url.strip() and settings.endpoints.openai_api_key.strip()
        )
        detail = "OPENAI_BASE_URL and OPENAI_API_KEY present" if ok else (
            "missing OPENAI_BASE_URL and/or OPENAI_API_KEY"
        )
        return ok, detail
    return False, f"unknown provider {provider!r}"


def _decision_sdk_importable() -> bool:
    try:
        importlib.import_module(DECISION_SDK_MODULE)
    except ImportError:
        return False
    return True


def _decision_report(settings: Settings) -> dict[str, Any]:
    """Decision-model health: names and resolved settings only, never values."""
    decision = settings.decision
    key_present = bool(settings.endpoints.typesafe_api_key.strip())
    if decision.provider == "typesafe":
        usable = key_present
        detail = "TYPESAFE_API_KEY present" if usable else "missing TYPESAFE_API_KEY"
    else:
        usable = True
        detail = "offline deterministic decision model; no credentials needed"
    return {
        "provider": decision.provider,
        "model": decision.model,
        "base_url": decision.base_url,
        "timeout_seconds": decision.timeout_seconds,
        "api_key_present": key_present,
        "sdk_importable": _decision_sdk_importable(),
        "selection_scorer": settings.selection.scorer,
        "usable": usable,
        "detail": detail,
    }


def _dataset_report(settings: Settings) -> dict[str, Any]:
    dataset_dir = settings.evaluation.dataset_dir
    report: dict[str, Any] = {"path": str(dataset_dir), "exists": dataset_dir.is_dir()}
    if not report["exists"]:
        report["cases"] = None
        return report
    try:
        from caio_code.infrastructure.datasets.loader import load_dataset

        dataset = load_dataset(dataset_dir)
        report["name"] = dataset.name
        report["cases"] = len(dataset.cases)
    except (CaioCodeError, OSError, ValueError) as exc:
        report["cases"] = None
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


def doctor_report(settings: Settings, *, requested_provider: str | None) -> dict[str, Any]:
    counter = build_counter(
        settings.tokens.counter,
        chars_per_token=settings.tokens.chars_per_token,
        encoding=settings.tokens.tiktoken_encoding,
    )
    price = _price_report(settings)
    providers = {
        name: dict(zip(("usable", "detail"), _provider_usable(settings, name), strict=True))
        for name in PROVIDERS
    }
    return {
        "provider": settings.provider.provider,
        "requested_provider": requested_provider,
        "model": settings.provider.model,
        "aux_provider": settings.provider.aux_provider,
        "aux_model": settings.provider.aux_model,
        "window_tokens": settings.window.tokens,
        "context_limit": settings.window.context_limit,
        "compaction_trigger_tokens": settings.window.compaction_trigger_tokens,
        "token_counter": counter.name,
        "sandbox_root": str(settings.sandbox.root),
        "allow_execute": settings.sandbox.allow_execute,
        "env_present": {name: name in os.environ for name in REPORTED_ENV_VARS},
        "providers": providers,
        "decision": _decision_report(settings),
        "dataset": _dataset_report(settings),
        "price": price,
    }


def _price_report(settings: Settings) -> dict[str, Any]:
    from caio_code.infrastructure.pricing.sheet import pricing_for

    sheet = pricing_for(settings)
    entry = sheet.for_model(settings.provider.model)
    return {
        "model": entry.model,
        "input_per_million_usd": str(entry.input_per_million),
        "cached_input_per_million_usd": str(entry.cached_input_per_million),
        "output_per_million_usd": str(entry.output_per_million),
        "fallback_used": entry.model != settings.provider.model
        and not settings.provider.model.startswith(entry.model),
    }


def _print_human(report: dict[str, Any]) -> None:
    print(f"provider: {report['provider']} (requested: {report['requested_provider'] or 'default'})")
    print(f"model: {report['model']}  aux: {report['aux_provider']}/{report['aux_model']}")
    print(
        f"window: {report['window_tokens']} tokens "
        f"(context limit {report['context_limit']}, compaction trigger {report['compaction_trigger_tokens']})"
    )
    print(f"token counter: {report['token_counter']}")
    print(f"sandbox root: {report['sandbox_root']} (execute: {report['allow_execute']})")
    print("environment (names only):")
    for name, present in report["env_present"].items():
        print(f"  {name}: {'set' if present else 'absent'}")
    print("providers:")
    for name, info in report["providers"].items():
        print(f"  {name}: {'usable' if info['usable'] else 'UNUSABLE'} - {info['detail']}")
    decision = report["decision"]
    print("decision model:")
    print(f"  provider: {decision['provider']}  model: {decision['model']}")
    print(f"  base URL: {decision['base_url']}  timeout: {decision['timeout_seconds']}s")
    print(f"  TYPESAFE_API_KEY: {'set' if decision['api_key_present'] else 'absent'}")
    print(
        f"  {DECISION_SDK_MODULE}: "
        f"{'importable' if decision['sdk_importable'] else 'NOT IMPORTABLE'}"
    )
    print(f"  selection scorer: {decision['selection_scorer']}")
    print(f"  {'usable' if decision['usable'] else 'UNUSABLE'} - {decision['detail']}")
    dataset = report["dataset"]
    cases = dataset["cases"]
    print(f"dataset: {dataset['path']} (exists: {dataset['exists']}, cases: {cases})")
    if "error" in dataset:
        print(f"  dataset error: {dataset['error']}")
    price = report["price"]
    print(
        f"price for {price['model']}: in ${price['input_per_million_usd']}/M, "
        f"cached ${price['cached_input_per_million_usd']}/M, "
        f"out ${price['output_per_million_usd']}/M"
    )


def doctor_command(args: Namespace) -> int:
    settings = load_settings(provider=args.provider)
    report = doctor_report(settings, requested_provider=args.provider)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    usable = report["providers"][report["provider"]]["usable"] and report["decision"]["usable"]
    return EXIT_OK if usable else EXIT_UNUSABLE_PROVIDER


__all__ = ["doctor_command", "doctor_report"]
