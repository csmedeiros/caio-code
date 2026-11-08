#!/usr/bin/env python3
"""Roda o NeMo Data Designer para cada (caso, conjunto de colunas) do build config.

O build config (`configs/long_histories_128k.json`) é a única fonte de verdade:
casos, contagens de blocos, prompts e aliases de modelo. Este script materializa
um config do Data Designer por (caso, conjunto), substituindo `__DOMAIN__` e
injetando o `model_alias`, e chama `data-designer create`.

Custa dinheiro: cada registro é uma chamada de modelo. Use `--dry-run` primeiro.
Segredos nunca são impressos — só se verifica se as variáveis existem.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

DATAGEN_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = DATAGEN_ROOT.parent
DEFAULT_CONFIG = DATAGEN_ROOT / "configs" / "long_histories_128k.json"
PROVIDERS_SPEC = DATAGEN_ROOT / "configs" / "providers.yaml"
OUTPUT_ROOT = DATAGEN_ROOT / "output"
DD_BIN = DATAGEN_ROOT / ".venv" / "bin" / "data-designer"

# O venv do datagen é isolado; os módulos puros do agente entram por sys.path
# para reutilizar CHAR_PER_TOKEN e PRICE_SHEET em vez de duplicar números.
sys.path.insert(0, str(REPO_ROOT / "src"))
from caio_code.config import CHARS_PER_TOKEN, PRICE_SHEET  # noqa: E402

REQUIRED_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL")


class GenerateError(RuntimeError):
    """Config inválido, ambiente incompleto ou falha do Data Designer."""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        msg = f"arquivo não encontrado: {path}"
        raise GenerateError(msg)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"JSON inválido em {path}: {exc}"
        raise GenerateError(msg) from exc


def _alias_to_model() -> dict[str, str]:
    """alias -> nome do modelo, lido do spec de providers (fonte única)."""
    if not PROVIDERS_SPEC.is_file():
        msg = f"spec de providers não encontrado: {PROVIDERS_SPEC}"
        raise GenerateError(msg)
    raw = yaml.safe_load(PROVIDERS_SPEC.read_text(encoding="utf-8")) or {}
    mapping: dict[str, str] = {}
    for entry in raw.get("model_configs") or []:
        if isinstance(entry, dict) and entry.get("alias") and entry.get("model"):
            mapping[str(entry["alias"])] = str(entry["model"])
    return mapping


def _price_for(model: str) -> tuple[Decimal, Decimal]:
    for entry in PRICE_SHEET:
        if entry.model == model:
            return entry.input_per_million, entry.output_per_million
    msg = f"o modelo {model!r} não está na PRICE_SHEET; não é possível estimar custo"
    raise GenerateError(msg)


def _check_env() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        msg = (
            f"variáveis ausentes ou vazias: {', '.join(missing)}. "
            "Exporte-as antes de gerar (set -a && . ../../.env && set +a)."
        )
        raise GenerateError(msg)


def _materialize(columns: list[dict[str, Any]], domain: str, model_alias: str) -> dict[str, Any]:
    """Copia as colunas, substitui __DOMAIN__ e injeta o model_alias nas colunas de LLM."""
    materialized: list[dict[str, Any]] = []
    for column in columns:
        clone = json.loads(json.dumps(column))
        params = clone.get("params")
        if isinstance(params, dict) and params.get("values") == ["__DOMAIN__"]:
            params["values"] = [domain]
        if clone.get("column_type", "").startswith("llm-"):
            clone["model_alias"] = model_alias
        materialized.append(clone)
    return {"columns": materialized}


def _resolve_alias(models: dict[str, str], set_name: str) -> str:
    alias = models.get("facts" if set_name == "facts" else "blocks")
    if not isinstance(alias, str) or not alias:
        msg = f"nenhum alias de modelo configurado para o conjunto {set_name!r}"
        raise GenerateError(msg)
    return alias


def _records_for(spec: dict[str, Any], set_name: str, scale: float) -> int:
    raw = spec.get("facts") if set_name == "facts" else (spec.get("blocks") or {}).get(set_name)
    if not isinstance(raw, int) or raw <= 0:
        msg = f"contagem inválida para {set_name!r}: {raw!r}"
        raise GenerateError(msg)
    return max(1, math.ceil(raw * scale))


def _estimate_cost(
    plan: list[dict[str, Any]],
    build: dict[str, Any],
    alias_model: dict[str, str],
) -> Decimal:
    cost_model = build.get("cost_model") or {}
    prompt_tokens = int(cost_model.get("prompt_tokens_per_call", 0))
    output_chars = cost_model.get("output_chars") or {}
    total = Decimal("0")
    for item in plan:
        model = alias_model.get(item["alias"])
        if model is None:
            msg = f"alias {item['alias']!r} não existe em {PROVIDERS_SPEC.name}"
            raise GenerateError(msg)
        input_price, output_price = _price_for(model)
        chars = int(output_chars.get(item["set"], 0))
        out_tokens = max(1, math.ceil(chars / CHARS_PER_TOKEN))
        calls = Decimal(item["records"])
        total += (calls * Decimal(prompt_tokens) * input_price + calls * Decimal(out_tokens) * output_price) / Decimal(
            1_000_000
        )
    return total


def _run_dd(config_path: Path, records: int, dataset_name: str, artifact_path: Path, timeout: float) -> None:
    if not DD_BIN.is_file():
        msg = f"binário do Data Designer ausente: {DD_BIN} (crie o venv e instale data-designer)"
        raise GenerateError(msg)
    artifact_path.mkdir(parents=True, exist_ok=True)
    command = [
        str(DD_BIN),
        "create",
        str(config_path),
        "--num-records",
        str(records),
        "--dataset-name",
        dataset_name,
        "--artifact-path",
        str(artifact_path),
        "--output-format",
        "jsonl",
        "--no-tui",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        msg = (
            f"data-designer create estourou {timeout:.0f}s para {dataset_name} "
            f"(n={records}). O provedor travou ou o conjunto é grande demais; "
            f"reduza --scale ou aumente `run_timeout_seconds` no build config."
        )
        raise GenerateError(msg) from exc
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout or "").strip().splitlines()[-25:])
        msg = f"data-designer create falhou (exit {result.returncode}) para {dataset_name}:\n{tail}"
        raise GenerateError(msg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="build config JSON")
    parser.add_argument("--case", action="append", default=None, help="gera só este case id (repetível)")
    parser.add_argument("--set", dest="sets", action="append", default=None, help="gera só este conjunto (repetível)")
    parser.add_argument("--scale", type=float, default=1.0, help="fator sobre as contagens (piloto: 0.02)")
    parser.add_argument("--dry-run", action="store_true", help="mostra o plano e o custo estimado, sem gastar")
    args = parser.parse_args(argv)

    try:
        build = _load_json(args.config)
        cases = build.get("cases") or []
        column_sets = build.get("column_sets") or {}
        models = build.get("models") or {}
        if not cases or not column_sets or not models:
            msg = "o build config precisa de `cases`, `column_sets` e `models`"
            raise GenerateError(msg)
        if not 0 < args.scale <= 1.0:
            msg = f"--scale precisa estar em (0, 1], veio {args.scale}"
            raise GenerateError(msg)

        alias_model = _alias_to_model()
        selected_cases = [c for c in cases if not args.case or c.get("id") in args.case]
        if not selected_cases:
            msg = f"nenhum caso selecionado com --case {args.case}"
            raise GenerateError(msg)
        selected_sets = args.sets or list(column_sets)
        unknown = [s for s in selected_sets if s not in column_sets]
        if unknown:
            msg = f"conjuntos desconhecidos: {', '.join(unknown)}; disponíveis: {', '.join(column_sets)}"
            raise GenerateError(msg)

        if not args.dry_run:
            _check_env()

        plan: list[dict[str, Any]] = []
        for case in selected_cases:
            case_id = str(case.get("id"))
            domain = str(case.get("domain"))
            for set_name in selected_sets:
                alias = _resolve_alias(models, set_name)
                records = _records_for(case, set_name, args.scale)
                plan.append(
                    {
                        "case": case_id,
                        "set": set_name,
                        "alias": alias,
                        "model": alias_model.get(alias, "?"),
                        "records": records,
                        "domain": domain,
                    }
                )

        total_calls = sum(item["records"] for item in plan)
        est = _estimate_cost(plan, build, alias_model)
        print(f"casos: {len(selected_cases)} | conjuntos: {len(selected_sets)} | execuções: {len(plan)}")
        print(f"chamadas de modelo: {total_calls} | scale: {args.scale}")
        print(f"custo estimado: ${est:.4f} USD")
        print()
        for item in plan:
            print(f"  {item['case']:<34} {item['set']:<15} n={item['records']:<5} {item['model']}")

        if args.dry_run:
            print("\n[dry-run] nada foi gerado.")
            return 0

        run_dir = OUTPUT_ROOT / str(build.get("dataset_name", "dataset"))
        run_timeout = float(build.get("run_timeout_seconds", 900))
        for item in plan:
            dataset_name = f"{item['case']}__{item['set']}"
            artifact_path = run_dir / item["case"] / item["set"]
            config_path = artifact_path / "dd_config.json"
            artifact_path.mkdir(parents=True, exist_ok=True)
            payload = _materialize(column_sets[item["set"]], item["domain"], item["alias"])
            config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\n>>> {dataset_name} (n={item['records']})")
            _run_dd(config_path, item["records"], dataset_name, artifact_path, run_timeout)
            print(f"    ok -> {artifact_path}")
    except GenerateError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    print(f"\nartefatos em: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
