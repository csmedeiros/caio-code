#!/usr/bin/env python3
"""Instala `configs/providers.yaml` no diretório de configuração do Data Designer.

Idempotente: entradas com o mesmo `name` (provider) ou `alias` (model config) são
substituídas; as demais são preservadas. Rodar duas vezes não duplica nada.

Segredos: o campo `api_key` do provider guarda o NOME da variável de ambiente.
Este script verifica se a variável existe, mas nunca imprime o valor.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

DATAGEN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = DATAGEN_ROOT / "configs" / "providers.yaml"
CONFIG_DIR = Path(os.environ.get("DATA_DESIGNER_HOME", Path.home() / ".data-designer"))
PROVIDERS_FILE = CONFIG_DIR / "model_providers.yaml"
MODELS_FILE = CONFIG_DIR / "model_configs.yaml"

ENV_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")


class SetupError(RuntimeError):
    """Falha de configuração: spec inválido, env ausente ou arquivo ilegível."""


def _resolve_env(value: Any) -> Any:
    """Substitui `${VAR}` pelo valor do ambiente; falha se a variável não existe."""
    if not isinstance(value, str):
        return value
    match = ENV_PLACEHOLDER.fullmatch(value.strip())
    if match is None:
        return value
    name = match.group(1)
    resolved = os.environ.get(name, "").strip().strip('"').strip("'")
    if not resolved:
        msg = f"a variável de ambiente {name} está vazia ou ausente (necessária para o endpoint)"
        raise SetupError(msg)
    return resolved


def _load_spec(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.is_file():
        msg = f"spec não encontrado: {path}"
        raise SetupError(msg)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        msg = f"spec precisa ser um mapping YAML: {path}"
        raise SetupError(msg)
    providers = raw.get("providers") or []
    models = raw.get("model_configs") or []
    if not isinstance(providers, list) or not isinstance(models, list):
        msg = "`providers` e `model_configs` precisam ser listas"
        raise SetupError(msg)
    for provider in providers:
        if "endpoint" in provider:
            provider["endpoint"] = _resolve_env(provider["endpoint"])
    return {"providers": providers, "model_configs": models}


def _load_existing(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get(key) if isinstance(raw, dict) else None
    return list(entries) if isinstance(entries, list) else []


def _merge(existing: list[dict[str, Any]], incoming: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Substitui por `key`, preserva o resto, mantém a ordem original."""
    by_key = {entry.get(key): entry for entry in incoming if isinstance(entry, dict)}
    merged: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for entry in existing:
        if not isinstance(entry, dict):
            continue
        identity = entry.get(key)
        if identity in by_key:
            merged.append(by_key[identity])
            seen.add(identity)
        else:
            merged.append(entry)
    for identity, entry in by_key.items():
        if identity not in seen:
            merged.append(entry)
    return merged


def _write(path: Path, key: str, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump({key: entries}, sort_keys=False, allow_unicode=True)
    path.write_text(payload, encoding="utf-8")


def _check_api_keys(providers: list[dict[str, Any]]) -> list[str]:
    """Confere se as variáveis de chave existem. Retorna os nomes presentes."""
    present: list[str] = []
    for provider in providers:
        name = provider.get("api_key")
        if not isinstance(name, str) or not name:
            continue
        if os.environ.get(name, "").strip():
            present.append(name)
        else:
            msg = (
                f"o provider {provider.get('name')!r} usa a variável {name}, "
                f"que está vazia ou ausente. Exporte-a antes de gerar "
                f"(por exemplo: set -a && . ../.env && set +a)."
            )
            raise SetupError(msg)
    return present


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC, help="arquivo YAML declarativo")
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR, help="diretório de configuração do Data Designer")
    parser.add_argument("--dry-run", action="store_true", help="mostra o que mudaria sem escrever")
    args = parser.parse_args(argv)

    try:
        spec = _load_spec(args.spec)
        providers = spec["providers"]
        models = spec["model_configs"]
        if not providers or not models:
            msg = "o spec precisa declarar ao menos um provider e um model_config"
            raise SetupError(msg)
        keys_present = _check_api_keys(providers)

        providers_file = args.config_dir / PROVIDERS_FILE.name
        models_file = args.config_dir / MODELS_FILE.name
        merged_providers = _merge(_load_existing(providers_file, "providers"), providers, "name")
        merged_models = _merge(_load_existing(models_file, "model_configs"), models, "alias")

        if args.dry_run:
            print(f"[dry-run] providers -> {providers_file}")
            for entry in providers:
                print(f"  + {entry.get('name')} endpoint={entry.get('endpoint')} api_key={entry.get('api_key')}")
            print(f"[dry-run] model_configs -> {models_file}")
            for entry in models:
                print(f"  + {entry.get('alias')} model={entry.get('model')} provider={entry.get('provider')}")
            print(f"[dry-run] variáveis de chave presentes: {sorted(keys_present)}")
            return 0

        _write(providers_file, "providers", merged_providers)
        _write(models_file, "model_configs", merged_models)
    except SetupError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    print(f"providers registrados: {', '.join(str(p.get('name')) for p in providers)}")
    print(f"model aliases registrados: {', '.join(str(m.get('alias')) for m in models)}")
    print(f"variáveis de chave presentes: {', '.join(sorted(keys_present))}")
    print(f"config dir: {args.config_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
