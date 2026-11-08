#!/usr/bin/env python3
"""Portão de qualidade do dataset gerado: aplica o contrato e fixa a procedência.

Um dataset que falha aqui **não** pode virar número do Capítulo 4. As verificações
cobrem três classes:

1. **Estrutura** — ids sequenciais, papéis alternados, `tool_calls` pareado com
   `tool_call_id`, primeira mensagem `user` e pinned, mensagem de contrato dentro
   do último quinto.
2. **Medição** — limites de mensagens/chars, espalhamento de tamanho entre casos,
   pressão sobre a janela declarada, tetos de truncagem efetivamente exercitados.
3. **Pontuabilidade** — o que protege a retenção de virar número falso:
   - o enunciado de cada fato está mesmo na mensagem que o carrega;
   - nenhuma resposta/alias de um fato é subcadena da de outro (ambiguidade);
   - nenhuma resposta aparece incidentalmente em muitas outras mensagens, o que
     deixaria uma política "acertar" mantendo a mensagem errada;
   - a mensagem de contrato não revela nenhuma resposta.

Ao final escreve `BUILDINFO.json` com sha256 de cada arquivo, versão do Data
Designer, modelo usado e fingerprint da config. Como a geração é dirigida por LLM,
a reprodutibilidade do dataset é **por hash fixado**, não por regeneração
(ver `datagen/AGENTS.md`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

DATAGEN_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = DATAGEN_ROOT.parent
DEFAULT_CONFIG = DATAGEN_ROOT / "configs" / "long_histories_128k.json"
DEFAULT_DATASET_DIR = REPO_ROOT / "evals" / "datasets"

sys.path.insert(0, str(REPO_ROOT / "src"))
from caio_code.config import CHARS_PER_TOKEN  # noqa: E402
from caio_code.domain.evaluation.cases import normalize_answer  # noqa: E402
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter  # noqa: E402

# O mesmo contador que o experimento usa. Contar `ceil(total/4)` em vez de
# `Σ ceil(|m|/4)` daria ao portão um número diferente do que os artefatos do
# run reportam -- e a tabela do capítulo discordaria do próprio dataset.
COUNTER = CharProxyTokenCounter()


class ValidationError(RuntimeError):
    """Erro de infraestrutura: config ou dataset ilegível."""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        msg = f"arquivo não encontrado: {path}"
        raise ValidationError(msg)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"JSON inválido em {path}: {exc}"
        raise ValidationError(msg) from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _proxy_tokens(messages: list[dict[str, Any]]) -> int:
    """Proxy tokens do caso, exatamente como `CharProxyTokenCounter.count_message`.

    Inclui `tool_calls` (nome + argumentos), não só o texto: é isso que o
    contador do experimento soma, e omitir isso faria o portão reportar menos
    tokens do que os artefatos do run -- a tabela do capítulo discordaria do
    próprio dataset.
    """
    total = 0
    for message in messages:
        total += COUNTER.count_text(str(message.get("text") or ""))
        for call in message.get("tool_calls") or []:
            total += COUNTER.count_text(str(call.get("name") or "") + str(call.get("arguments") or ""))
    return total


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle) and needle in haystack


def _check_case(
    raw: dict[str, Any],
    *,
    bounds: dict[str, Any],
    assembly: dict[str, Any],
    window_tokens: int,
    problems: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    case_id = str(raw.get("id", "<sem id>"))
    messages = raw.get("messages") or []
    facts = raw.get("facts") or []
    probes = raw.get("probes") or []

    def fail(text: str) -> None:
        problems.append(f"{case_id}: {text}")

    def warn(text: str) -> None:
        warnings.append(f"{case_id}: {text}")

    # --- estrutura -------------------------------------------------------
    expected_ids = [f"{case_id}-m{i:03d}" for i in range(len(messages))]
    if [m.get("id") for m in messages] != expected_ids:
        fail("ids de mensagem não são sequenciais no formato <case>-mNNN")
    if not messages:
        fail("caso sem mensagens")
        return {"id": case_id, "messages": 0, "chars": 0, "proxy_tokens": 0}
    if messages[0].get("role") != "user":
        fail(f"a primeira mensagem é {messages[0].get('role')!r}, deveria ser 'user'")
    if assembly.get("first_message_pinned", True) and not messages[0].get("pinned"):
        fail("a primeira mensagem não está pinned (políticas podem derrubá-la)")

    open_calls: dict[str, int] = {}
    for index, message in enumerate(messages):
        for call in message.get("tool_calls") or []:
            if call.get("id") in open_calls:
                fail(f"tool_call id duplicado: {call.get('id')}")
            open_calls[call.get("id")] = index
        if message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            if call_id not in open_calls:
                fail(f"mensagem {index} é 'tool' sem tool_call anterior ({call_id!r})")
            elif open_calls[call_id] >= index:
                fail(f"mensagem {index}: tool result aparece antes do tool_call {call_id!r}")

    contract = [i for i, m in enumerate(messages) if (m.get("metadata") or {}).get("role_in_case") == "contract"]
    last_fifth_start = len(messages) - max(1, len(messages) // 5)
    if not contract:
        fail("nenhuma mensagem de contrato (role_in_case='contract')")
    elif any(index < last_fifth_start for index in contract):
        fail(f"mensagem de contrato em {contract} está antes do último quinto (>{last_fifth_start})")

    # --- medição ---------------------------------------------------------
    chars = sum(len(m.get("text") or "") for m in messages)
    count = len(messages)
    if not bounds.get("min_messages", 0) <= count <= bounds.get("max_messages", 10**9):
        fail(f"{count} mensagens fora da faixa [{bounds.get('min_messages')}, {bounds.get('max_messages')}]")
    if not bounds.get("min_chars", 0) <= chars <= bounds.get("max_chars", 10**9):
        fail(f"{chars} chars fora da faixa [{bounds.get('min_chars')}, {bounds.get('max_chars')}]")

    line_ceiling = int(assembly.get("tool_output_line_ceiling", 2000))
    byte_ceiling = int(assembly.get("tool_output_byte_ceiling", 51200))
    tools = [m for m in messages if m.get("role") == "tool"]
    over_lines = sum(1 for m in tools if (m.get("text") or "").count("\n") + 1 > line_ceiling)
    over_any = sum(
        1
        for m in tools
        if (m.get("text") or "").count("\n") + 1 > line_ceiling
        or len((m.get("text") or "").encode("utf-8")) > byte_ceiling
    )
    if over_lines < int(bounds.get("min_tool_outputs_over_line_ceiling", 1)):
        fail(f"nenhuma saída de tool ultrapassa {line_ceiling} linhas: o braço de truncagem não é exercitado")
    if over_any < int(bounds.get("min_tool_outputs_over_any_ceiling", 2)):
        fail(f"apenas {over_any} saídas de tool acima de algum teto; o desenho pede {bounds.get('min_tool_outputs_over_any_ceiling')}")

    proxy = _proxy_tokens(messages)
    pressure = proxy / window_tokens if window_tokens else 0.0
    if pressure < 2.0:
        warn(f"pressão de apenas {pressure:.2f}x sobre a janela de {window_tokens} tokens")

    # --- pontuabilidade --------------------------------------------------
    positions = {"early": 0, "middle": 0, "late": 0}
    per_position = int(bounds.get("facts_per_position", 0))
    acceptable: list[tuple[str, list[str]]] = []
    for fact in facts:
        position = fact.get("position")
        if position not in positions:
            fail(f"fato {fact.get('id')!r} com posição inválida {position!r}")
        else:
            positions[position] += 1
        index = fact.get("message_index")
        if not isinstance(index, int) or not 0 <= index < len(messages):
            fail(f"fato {fact.get('id')!r} com message_index fora do transcript: {index!r}")
        else:
            carrier = normalize_answer(messages[index].get("text") or "")
            if not _contains(carrier, normalize_answer(fact.get("statement") or "")):
                fail(f"fato {fact.get('id')!r} não está no texto da mensagem {index} que deveria carregá-lo")
            # Invariante do contrato antigo: a resposta precisa aparecer
            # LITERALMENTE na mensagem que declara o fato. Sem isso a sonda é
            # inrespondível para qualquer política -- a retenção medida seria um
            # teto zero, não uma propriedade da gestão de contexto.
            answers = [
                normalize_answer(a)
                for a in (fact.get("answer"), *(fact.get("aliases") or []))
            ]
            if not any(a and a in carrier for a in answers):
                fail(
                    f"fato {fact.get('id')!r}: nenhuma resposta aceitável "
                    f"(answer={fact.get('answer')!r}) aparece literalmente na mensagem {index}; "
                    "a sonda não tem como ser acertada"
                )
        acceptable.append((str(fact.get("id")), [str(a) for a in (fact.get("answer"), *(fact.get("aliases") or []))]))

    if per_position:
        for position, seen in positions.items():
            if seen != per_position:
                fail(f"{seen} fatos na posição {position!r}; o desenho pede {per_position}")

    fact_ids = {f.get("id") for f in facts}
    for probe in probes:
        if probe.get("fact_id") not in fact_ids:
            fail(f"sonda {probe.get('id')!r} referencia fato inexistente {probe.get('fact_id')!r}")
        if not (probe.get("question") or "").strip():
            fail(f"sonda {probe.get('id')!r} sem pergunta")
    if len(probes) != len(facts):
        warn(f"{len(probes)} sondas para {len(facts)} fatos")

    # Ambiguidade: resposta de um fato contida na de outro.
    for index, (fact_a, answers_a) in enumerate(acceptable):
        for fact_b, answers_b in acceptable[index + 1 :]:
            for candidate_a in answers_a:
                needle = normalize_answer(candidate_a)
                for candidate_b in answers_b:
                    other = normalize_answer(candidate_b)
                    if needle and other and (needle == other or _contains(other, needle) or _contains(needle, other)):
                        fail(
                            f"respostas ambíguas entre {fact_a} ({candidate_a!r}) e {fact_b} ({candidate_b!r}): "
                            "uma é subcadena da outra, então a pontuação não distingue os fatos"
                        )

    # Ocorrência incidental: a resposta aparece em mensagens que não a carregam.
    for fact in facts:
        answers = [normalize_answer(a) for a in (fact.get("answer"), *(fact.get("aliases") or []))]
        answers = [a for a in answers if a]
        carrier = fact.get("message_index")
        incidental = 0
        for index, message in enumerate(messages):
            if index == carrier:
                continue
            haystack = normalize_answer(message.get("text") or "")
            if any(_contains(haystack, answer) for answer in answers):
                incidental += 1
        if incidental > 2:
            fail(
                f"fato {fact.get('id')!r} (answer={fact.get('answer')!r}) aparece em {incidental} outras mensagens: "
                "uma política poderia acertar mantendo a mensagem errada"
            )
        elif incidental > 0:
            warn(f"fato {fact.get('id')!r} tem {incidental} ocorrência incidental")

    # A mensagem de contrato não pode revelar resposta.
    for index in contract:
        haystack = normalize_answer(messages[index].get("text") or "")
        for fact in facts:
            for candidate in (fact.get("answer"), *(fact.get("aliases") or [])):
                if _contains(haystack, normalize_answer(str(candidate))):
                    fail(f"a mensagem de contrato revela a resposta do fato {fact.get('id')!r}: {candidate!r}")

    return {
        "id": case_id,
        "messages": count,
        "chars": chars,
        "proxy_tokens": proxy,
        "window_pressure": round(pressure, 2),
        "facts": len(facts),
        "probes": len(probes),
        "tool_outputs": len(tools),
        "over_line_ceiling": over_lines,
        "over_any_ceiling": over_any,
        "fact_positions": positions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="build config JSON")
    parser.add_argument("--dataset-dir", type=Path, default=None, help="dataset a validar (default: evals/datasets/<name>)")
    parser.add_argument("--no-buildinfo", action="store_true", help="não escreve BUILDINFO.json")
    args = parser.parse_args(argv)

    try:
        build = _load_json(args.config)
        dataset_name = str(build.get("dataset_name", "dataset"))
        dataset_dir = args.dataset_dir or (DEFAULT_DATASET_DIR / dataset_name)
        manifest_path = dataset_dir / "dataset.json"
        manifest = _load_json(manifest_path)

        bounds = build.get("bounds") or {}
        assembly = build.get("assembly") or {}
        window_tokens = int(build.get("window_tokens", 0))

        problems: list[str] = []
        warnings: list[str] = []
        stats: list[dict[str, Any]] = []
        files: dict[str, str] = {"dataset.json": _sha256(manifest_path)}

        for case_id in manifest.get("cases") or []:
            path = dataset_dir / f"{case_id}.json"
            if not path.is_file():
                problems.append(f"{case_id}: arquivo ausente {path}")
                continue
            files[f"{case_id}.json"] = _sha256(path)
            stats.append(
                _check_case(
                    _load_json(path),
                    bounds=bounds,
                    assembly=assembly,
                    window_tokens=window_tokens,
                    problems=problems,
                    warnings=warnings,
                )
            )

        sizes = [item["chars"] for item in stats]
        spread = (max(sizes) - min(sizes)) if sizes else 0
        # O espalhamento é uma propriedade do conjunto COMPLETO: validado um
        # subconjunto (--case), a comparação não significa nada e vira falso
        # positivo. O total esperado vem do build config, não do manifesto.
        expected_cases = len(build.get("cases") or [])
        if len(stats) < expected_cases:
            print(
                f"\nnota: {len(stats)} de {expected_cases} casos presentes; "
                "o espalhamento de tamanho só é avaliado no conjunto completo"
            )
        elif spread < int(bounds.get("min_size_spread_chars", 0)):
            problems.append(
                f"espalhamento de tamanho entre casos é {spread} chars; "
                f"o desenho pede >= {bounds.get('min_size_spread_chars')}"
            )
    except ValidationError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    header = f"dataset: {dataset_name} | janela declarada: {window_tokens} tokens | casos: {len(stats)}"
    print(header)
    print("-" * len(header))
    print(f"{'case':<34}{'msgs':>6}{'chars':>10}{'proxy tok':>11}{'pressao':>9}{'facts':>7}{'tools':>7}")
    for item in stats:
        print(
            f"{item['id']:<34}{item['messages']:>6}{item['chars']:>10}"
            f"{item['proxy_tokens']:>11}{item['window_pressure']:>8.2f}x{item['facts']:>7}{item['tool_outputs']:>7}"
        )
    if stats:
        mean = sum(i["proxy_tokens"] for i in stats) / len(stats)
        print(f"\nproxy tokens: min={min(i['proxy_tokens'] for i in stats)} mean={mean:.0f} max={max(i['proxy_tokens'] for i in stats)}")
        print(f"espalhamento de chars entre casos: {spread}")

    for warning in warnings:
        print(f"\naviso: {warning}")
    for problem in problems:
        print(f"\nFALHA: {problem}")

    if problems:
        print(f"\n{len(problems)} problema(s): o dataset NÃO pode virar número de capítulo.")
        return 1

    if not args.no_buildinfo:
        buildinfo = {
            "dataset_name": dataset_name,
            "generator": str(build.get("generator", "")),
            "seed": build.get("seed"),
            "window_tokens": window_tokens,
            "chars_per_token": CHARS_PER_TOKEN,
            "models": build.get("models"),
            "calibration": build.get("calibration"),
            "config_sha256": _sha256(args.config),
            "files_sha256": files,
            "cases": stats,
            "reproducibility": "hash-pinned: a geração é dirigida por LLM e não é byte-reproduzível; o artefato versionado é a fonte de verdade.",
        }
        info_path = dataset_dir / "BUILDINFO.json"
        info_path.write_text(json.dumps(buildinfo, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nprocedência -> {info_path}")

    print("\nOK: dataset dentro do contrato.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
