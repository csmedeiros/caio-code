#!/usr/bin/env python3
"""Monta o dataset congelado a partir dos blocos gerados pelo NeMo Data Designer.

Divisão de responsabilidade (ver `datagen/AGENTS.md`): o Data Designer gera
**conteúdo**; este script impõe **estrutura**. Tudo que o experimento precisa que
seja exato é decidido aqui, deterministicamente, a partir de `random.Random(seed)`:

- alternância de papéis e pareamento `tool_calls` <-> `tool_call_id`;
- ids de mensagem (`<case>-mNNN`) e de tool call (`<case>-tcNNN`);
- primeira mensagem pinned, papel `user`, texto = a task do caso;
- **seleção dos fatos por unicidade medida**: o Data Designer gera os blocos e os
  fatos de forma independente, então um fato como `--workers` pode aparecer em
  dezenas de outras mensagens. Se isso passar, uma política "acerta" a sonda
  mantendo a mensagem errada e a retenção deixa de medir qualquer coisa. Por isso
  o pool é maior que o necessário e só entram fatos com zero ocorrência incidental;
- posição dos fatos críticos (early/middle/late) e o `message_index` de cada um;
- mensagem de contrato no último quinto, sobre uma mensagem `user` existente, sem
  revelar nenhuma resposta;
- duas saídas de ferramenta expandidas acima dos tetos de truncagem, sem as quais
  os braços de truncagem seriam indistinguíveis do baseline;
- `metadata` do caso e o manifesto do dataset.

A serialização usa o codec do próprio agente, de modo que um dataset inválido
falha aqui em vez de falhar no meio do experimento.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

DATAGEN_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = DATAGEN_ROOT.parent
DEFAULT_CONFIG = DATAGEN_ROOT / "configs" / "long_histories_128k.json"
DEFAULT_OUTPUT_ROOT = DATAGEN_ROOT / "output"
DEFAULT_DATASET_DIR = REPO_ROOT / "evals" / "datasets"

# O venv do datagen é isolado; os módulos puros do agente entram por sys.path.
sys.path.insert(0, str(REPO_ROOT / "src"))
from caio_code.domain.conversation.messages import Message, Role, ToolCall  # noqa: E402
from caio_code.domain.evaluation.cases import (  # noqa: E402
    CriticalFact,
    EvalDataset,
    HistoryCase,
    Probe,
    normalize_answer,
)
from caio_code.infrastructure.datasets import codec  # noqa: E402

CONTRACT_TEMPLATE = (
    "Before you answer anything else, restate the constraints we agreed for this task and "
    "keep them in mind for the rest of the session: {task} Report the exact values you relied "
    "on, not a paraphrase."
)
POSITIONS = ("early", "middle", "late")


class ConvertError(RuntimeError):
    """Bloco ausente, pool insuficiente ou dataset que viola o próprio desenho."""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        msg = f"arquivo não encontrado: {path}"
        raise ConvertError(msg)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"JSON inválido em {path}: {exc}"
        raise ConvertError(msg) from exc


def _read_pool(output_root: Path, dataset_name: str, case_id: str, set_name: str) -> list[dict[str, Any]]:
    """Lê o jsonl de um (caso, conjunto). O diretório pode ter sufixo de timestamp."""
    base = output_root / dataset_name / case_id / set_name
    if not base.is_dir():
        msg = f"nenhuma saída gerada para {case_id}/{set_name} em {base}; rode generate.py"
        raise ConvertError(msg)
    files = sorted(base.glob("*/*.jsonl"))
    if not files:
        msg = f"nenhum .jsonl sob {base}; rode generate.py"
        raise ConvertError(msg)
    rows: list[dict[str, Any]] = []
    # Havendo mais de uma rodada (re-execução), a última vence: é a mais recente.
    for path in files[-1:]:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                msg = f"linha inválida em {path}: {exc}"
                raise ConvertError(msg) from exc
    if not rows:
        msg = f"pool vazio para {case_id}/{set_name}"
        raise ConvertError(msg)
    return rows


def _bodies(rows: list[dict[str, Any]]) -> list[str]:
    out = [str(row.get("body", "")).strip() for row in rows]
    out = [text for text in out if text]
    if not out:
        msg = "nenhum bloco com `body` não vazio"
        raise ConvertError(msg)
    return out


def _tool_blocks(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    out = [(str(row.get("tool_name") or "shell"), str(row.get("body", "")).strip()) for row in rows]
    out = [(name, body) for name, body in out if body]
    if not out:
        msg = "nenhum bloco de tool_output utilizável"
        raise ConvertError(msg)
    return out


def _expand_over_ceilings(body: str, *, line_ceiling: int, byte_ceiling: int) -> str:
    """Expande uma saída real até estourar os DOIS tetos de truncagem.

    Sem isso nenhum tool output ultrapassa `TOOL_LIMITS`, e os braços
    `tool_truncation_only` / `*_plus_truncation` medem exatamente o mesmo que o
    baseline — o experimento perde o braço que isola a truncagem.

    Os dois tetos são independentes: um corpo de linhas curtas atinge 2.000
    linhas muito antes de atingir 51.200 bytes, então o laço continua até os
    dois serem violados, e não só o de linhas.
    """
    lines = body.splitlines() or [body]
    expanded: list[str] = []
    counter = 0
    total_bytes = 0
    # Pior caso: cada linha renderizada tem pelo menos 7 bytes ("    1| "),
    # então byte_ceiling/7 + 1 linhas bastam; a folga cobre o teto de linhas.
    max_lines = line_ceiling + byte_ceiling // 7 + 64
    while True:
        for line in lines:
            counter += 1
            rendered = f"{counter:5d}| {line}"
            expanded.append(rendered)
            total_bytes += len(rendered.encode("utf-8")) + 1
            if len(expanded) > max_lines:
                msg = (
                    f"não foi possível estourar os dois tetos ({line_ceiling} linhas, "
                    f"{byte_ceiling} bytes) dentro de {max_lines} linhas"
                )
                raise ConvertError(msg)
        if len(expanded) > line_ceiling and total_bytes > byte_ceiling:
            return "\n".join(expanded)


def _fact_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normaliza o pool de fatos e descarta os que já nascem inutilizáveis."""
    candidates: list[dict[str, Any]] = []
    seen_answers: set[str] = set()
    for row in rows:
        raw = row.get("fact")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                continue
        if not isinstance(raw, dict):
            continue
        statement = str(raw.get("statement", "")).strip()
        answer = str(raw.get("answer", "")).strip()
        question = str(raw.get("question", "")).strip()
        raw_aliases = raw.get("aliases") or []
        # Um modelo que devolve `aliases` como string em vez de lista iteraria
        # CARACTERES: cada um viraria um alias de uma letra, que casa com
        # qualquer mensagem por subcadena e corrompe a pontuação em silêncio.
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        aliases = tuple(
            dict.fromkeys(
                alias
                for alias in (str(a).strip() for a in raw_aliases)
                # Alias de um caractere é degenerado sob `answer_matches`.
                if len(normalize_answer(alias)) >= 2
            )
        )
        if not (statement and answer and question) or len(aliases) < 2:
            continue
        if len(normalize_answer(answer)) < 2:
            continue
        key = normalize_answer(answer)
        if not key or key in seen_answers:
            continue
        seen_answers.add(key)
        # A resposta precisa aparecer LITERALMENTE no próprio enunciado, porque é
        # o enunciado que vai embutido na mensagem portadora. Um modelo que
        # responde "5432/tcp" para um enunciado que diz "port 5432" produz uma
        # sonda inrespondível: nenhuma política consegue acertá-la, e a retenção
        # medida vira um teto zero que não diz nada sobre gestão de contexto.
        normalized_statement = normalize_answer(statement)
        acceptable = [normalize_answer(a) for a in (answer, *aliases)]
        if not any(a and a in normalized_statement for a in acceptable):
            continue
        candidates.append(
            {
                "facet": str(row.get("facet", "")).strip(),
                "statement": statement,
                "answer": answer,
                "question": question,
                "aliases": aliases,
            }
        )
    return candidates


def _answers_of(candidate: dict[str, Any]) -> list[str]:
    return [normalize_answer(a) for a in (candidate["answer"], *candidate["aliases"]) if normalize_answer(a)]


def _occurrences(messages: list[Message], answers: list[str], *, skip: int | None = None) -> int:
    """Em quantas mensagens (fora a portadora) alguma resposta aparece como subcadena."""
    hits = 0
    for index, message in enumerate(messages):
        if skip is not None and index == skip:
            continue
        haystack = normalize_answer(message.text)
        if any(answer in haystack for answer in answers):
            hits += 1
    return hits


def _ambiguous(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Duas respostas se confundem se uma é subcadena da outra."""
    for left in _answers_of(a):
        for right in _answers_of(b):
            if left == right or left in right or right in left:
                return True
    return False


def _select_facts(
    candidates: list[dict[str, Any]],
    messages: list[Message],
    *,
    needed: int,
    contract_text: str,
) -> list[dict[str, Any]]:
    """Escolhe `needed` fatos que a pontuação consegue distinguir de verdade.

    Critérios, nesta ordem: zero ocorrência incidental no transcript, nenhuma
    colisão com o texto do contrato, nenhuma ambiguidade com os já escolhidos e,
    como desempate, variedade de facet.
    """
    haystack = normalize_answer(contract_text)
    clean: list[dict[str, Any]] = []
    for candidate in candidates:
        answers = _answers_of(candidate)
        if not answers:
            continue
        if any(answer in haystack for answer in answers):
            continue
        if _occurrences(messages, answers) != 0:
            continue
        clean.append(candidate)

    selected: list[dict[str, Any]] = []
    used_facets: set[str] = set()
    # Duas passadas: primeiro só facets novos (diversidade), depois o que sobrou.
    for require_new_facet in (True, False):
        for candidate in clean:
            if len(selected) >= needed:
                return selected
            if candidate in selected:
                continue
            facet = candidate["facet"]
            if require_new_facet and facet in used_facets:
                continue
            if any(_ambiguous(candidate, chosen) for chosen in selected):
                continue
            selected.append(candidate)
            used_facets.add(facet)

    if len(selected) < needed:
        msg = (
            f"só {len(selected)} de {needed} fatos são pontuáveis (zero ocorrência incidental e "
            f"sem ambiguidade) num pool de {len(candidates)}. Aumente `facts` no build config "
            "ou diversifique os facets: sem isso a retenção mediria acerto por coincidência."
        )
        raise ConvertError(msg)
    return selected


def _build_messages(
    case_id: str,
    *,
    task: str,
    user_pool: list[str],
    assistant_pool: list[str],
    tool_pool: list[tuple[str, str]],
    char_target: int,
    tool_call_probability: float,
    rng: random.Random,
    assembly: dict[str, Any],
) -> tuple[list[Message], list[int]]:
    """Transcript válido: user/assistant alternando, tool result sempre pareado.

    Retorna as mensagens e os índices das duas saídas expandidas acima dos tetos.
    """
    line_ceiling = int(assembly.get("tool_output_line_ceiling", 2000))
    byte_ceiling = int(assembly.get("tool_output_byte_ceiling", 51200))

    messages: list[Message] = [
        Message(
            id=f"{case_id}-m000",
            role=Role.USER,
            text=task,
            pinned=bool(assembly.get("first_message_pinned", True)),
            metadata={"role_in_case": "task", "note": "the task statement; policies may never drop it"},
        )
    ]
    ui = ai = ti = tc = 0
    expanded_indices: list[int] = []
    # Duas saídas expandidas, colocadas cedo o bastante para caberem no histórico.
    expand_at = {3, 9}
    tool_events = 0

    def next_id(index: int) -> str:
        return f"{case_id}-m{index:03d}"

    def char_total() -> int:
        return sum(len(m.text) for m in messages)

    while char_total() < char_target:
        if ui >= len(user_pool) or ai >= len(assistant_pool):
            break
        messages.append(
            Message(id=next_id(len(messages)), role=Role.USER, text=user_pool[ui], metadata={"filler": "user_turn"})
        )
        ui += 1

        use_tool = rng.random() < tool_call_probability and ti < len(tool_pool)
        if use_tool:
            tool_name, tool_body = tool_pool[ti]
            ti += 1
            tc += 1
            call_id = f"{case_id}-tc{tc:03d}"
            messages.append(
                Message(
                    id=next_id(len(messages)),
                    role=Role.ASSISTANT,
                    text=assistant_pool[ai],
                    tool_calls=(
                        ToolCall(id=call_id, name=tool_name, arguments=json.dumps({"path": f"src/{tool_name}.py"})),
                    ),
                    metadata={"filler": "assistant_turn"},
                )
            )
            ai += 1
            if tool_events in expand_at:
                tool_body = _expand_over_ceilings(tool_body, line_ceiling=line_ceiling, byte_ceiling=byte_ceiling)
                expanded_indices.append(len(messages))
            tool_events += 1
            messages.append(
                Message(
                    id=next_id(len(messages)),
                    role=Role.TOOL,
                    text=tool_body,
                    tool_call_id=call_id,
                    name=tool_name,
                    metadata={"filler": "tool_output"},
                )
            )
        else:
            messages.append(
                Message(
                    id=next_id(len(messages)),
                    role=Role.ASSISTANT,
                    text=assistant_pool[ai],
                    metadata={"filler": "assistant_turn"},
                )
            )
            ai += 1

    if len(messages) < 40:
        msg = f"transcript curto demais ({len(messages)} mensagens); faltam blocos gerados"
        raise ConvertError(msg)
    return messages, expanded_indices


def _place_contract(messages: list[Message], task: str, *, reserved: set[int]) -> int:
    """Reescreve uma mensagem `user` do último quinto como mensagem de contrato.

    Não insere mensagem nova (preservando ids e alternância) e nunca escolhe uma
    mensagem reservada para carregar fato.
    """
    text = CONTRACT_TEMPLATE.format(task=task)
    start = len(messages) - max(2, len(messages) // 5)
    for index in range(start, len(messages)):
        if index in reserved or messages[index].role is not Role.USER:
            continue
        target = messages[index]
        messages[index] = Message(
            id=target.id,
            role=Role.USER,
            text=f"{text}\n\n{target.text}",
            tool_calls=(),
            tool_call_id=None,
            name=None,
            pinned=False,
            metadata={**target.metadata, "role_in_case": "contract"},
        )
        return index
    msg = "nenhuma mensagem `user` livre no último quinto para virar contrato"
    raise ConvertError(msg)


def _embed_facts(
    case_id: str,
    messages: list[Message],
    selected: list[dict[str, Any]],
    fractions: dict[str, list[float]],
    *,
    reserved: set[int],
) -> tuple[list[CriticalFact], list[Probe]]:
    """Embutir cada fato no transcript e derivar a sonda correspondente."""
    last = len(messages) - 1
    built_facts: list[CriticalFact] = []
    built_probes: list[Probe] = []
    used_indices: set[int] = set(reserved)
    slot = 0
    for position in POSITIONS:
        for fraction in fractions.get(position, []):
            if slot >= len(selected):
                break
            raw = selected[slot]
            index = max(1, min(last - 1, round(fraction * last)))
            # Nunca duas coisas no mesmo índice: nem outro fato, nem o contrato.
            while index in used_indices and index < last - 1:
                index += 1
            while index in used_indices and index > 1:
                index -= 1
            if index in used_indices:
                msg = f"sem índice livre para o fato da posição {position!r}"
                raise ConvertError(msg)
            used_indices.add(index)

            target = messages[index]
            fact_id = f"{case_id}-f{slot:02d}"
            messages[index] = Message(
                id=target.id,
                role=target.role,
                text=f"{target.text}\n\n{raw['statement']}",
                tool_calls=target.tool_calls,
                tool_call_id=target.tool_call_id,
                name=target.name,
                pinned=target.pinned,
                metadata={**target.metadata, "carries_fact": fact_id},
            )
            built_facts.append(
                CriticalFact(
                    id=fact_id,
                    statement=raw["statement"],
                    answer=raw["answer"],
                    aliases=raw["aliases"],
                    position=position,  # type: ignore[arg-type]
                    message_index=index,
                )
            )
            built_probes.append(
                Probe(
                    id=f"{case_id}-p{slot:02d}",
                    fact_id=fact_id,
                    question=raw["question"],
                    expected=raw["answer"],
                    aliases=raw["aliases"],
                )
            )
            slot += 1
    if not built_facts:
        msg = "nenhum fato crítico embutido"
        raise ConvertError(msg)
    return built_facts, built_probes


def _convert_case(
    spec: dict[str, Any],
    *,
    dataset_name: str,
    output_root: Path,
    assembly: dict[str, Any],
    bounds: dict[str, Any],
    seed: int,
    case_index: int,
) -> HistoryCase:
    case_id = str(spec["id"])
    task = str(spec["task"])
    char_target = int(spec["char_target"])
    rng = random.Random(seed + case_index)

    user_pool = _bodies(_read_pool(output_root, dataset_name, case_id, "user_turn"))
    assistant_pool = _bodies(_read_pool(output_root, dataset_name, case_id, "assistant_turn"))
    tool_pool = _tool_blocks(_read_pool(output_root, dataset_name, case_id, "tool_output"))
    candidates = _fact_candidates(_read_pool(output_root, dataset_name, case_id, "facts"))

    rng.shuffle(user_pool)
    rng.shuffle(assistant_pool)
    rng.shuffle(tool_pool)

    messages, expanded = _build_messages(
        case_id,
        task=task,
        user_pool=user_pool,
        assistant_pool=assistant_pool,
        tool_pool=tool_pool,
        char_target=char_target,
        tool_call_probability=float(assembly.get("tool_call_probability", 0.55)),
        rng=rng,
        assembly=assembly,
    )

    per_position = int(bounds.get("facts_per_position", 4))
    needed = per_position * len(POSITIONS)
    fractions = assembly.get("fact_position_fractions") or {}
    # A seleção acontece ANTES de embutir: mede o transcript como o modelo o verá.
    selected = _select_facts(candidates, messages, needed=needed, contract_text=CONTRACT_TEMPLATE.format(task=task))

    # Índices-alvo dos fatos, para que o contrato nunca caia sobre uma portadora.
    last = len(messages) - 1
    reserved: set[int] = set()
    for position in POSITIONS:
        for fraction in fractions.get(position, []):
            reserved.add(max(1, min(last - 1, round(fraction * last))))
    contract_index = _place_contract(messages, task, reserved=reserved)
    facts, probes = _embed_facts(case_id, messages, selected, fractions, reserved={contract_index})

    tool_messages = [m for m in messages if m.role is Role.TOOL]
    largest = max(tool_messages, key=lambda m: len(m.text), default=None)
    positions: dict[str, int] = {position: 0 for position in POSITIONS}
    for fact in facts:
        positions[fact.position] += 1

    metadata = {
        "case_seed": seed + case_index,
        "char_count": sum(len(m.text) for m in messages),
        "char_target": char_target,
        "contract_message": messages[contract_index].id,
        "domain": str(spec.get("domain", "")),
        "expanded_over_ceiling_messages": [messages[i].id for i in expanded if i < len(messages)],
        "fact_facets": sorted({candidate["facet"] for candidate in selected if candidate["facet"]}),
        "fact_pool_size": len(candidates),
        "fact_positions": positions,
        "generator": "datagen (nemo-data-designer + convert.py)",
        "largest_tool_output_chars": len(largest.text) if largest else 0,
        "largest_tool_output_lines": (largest.text.count("\n") + 1) if largest else 0,
        "largest_tool_output_message": largest.id if largest else "",
        "message_count": len(messages),
        "notes": str(spec.get("description", "")),
        "probe_count": len(probes),
        "tool_output_count": len(tool_messages),
    }
    return HistoryCase(
        id=case_id,
        description=str(spec.get("description", "")),
        messages=tuple(messages),
        facts=tuple(facts),
        probes=tuple(probes),
        task=task,
        source=str(spec.get("source", "synthetic-datadesigner")),
        metadata=metadata,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="build config JSON")
    parser.add_argument(
        "--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="raiz dos artefatos do Data Designer"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="diretório de destino do dataset (default: evals/datasets/<name>)"
    )
    parser.add_argument("--case", action="append", default=None, help="converte só este case id (repetível)")
    args = parser.parse_args(argv)

    try:
        build = _load_json(args.config)
        dataset_name = str(build.get("dataset_name", "dataset"))
        seed = int(build.get("seed", 0))
        assembly = build.get("assembly") or {}
        bounds = build.get("bounds") or {}
        cases_spec = build.get("cases") or []
        if args.case:
            cases_spec = [c for c in cases_spec if c.get("id") in args.case]
        if not cases_spec:
            msg = "nenhum caso para converter"
            raise ConvertError(msg)

        target_dir = args.out or (DEFAULT_DATASET_DIR / dataset_name)
        target_dir.mkdir(parents=True, exist_ok=True)

        converted: list[HistoryCase] = []
        for index, spec in enumerate(cases_spec):
            case = _convert_case(
                spec,
                dataset_name=dataset_name,
                output_root=args.output_root,
                assembly=assembly,
                bounds=bounds,
                seed=seed,
                case_index=index,
            )
            converted.append(case)
            path = target_dir / f"{case.id}.json"
            path.write_text(
                json.dumps(codec.case_to_dict(case), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(
                f"{case.id:<34} msgs={case.metadata['message_count']:<5} "
                f"chars={case.metadata['char_count']:<8} facts={len(case.facts)} "
                f"(pool {case.metadata['fact_pool_size']}) probes={len(case.probes)} -> {path.name}"
            )

        dataset = EvalDataset(
            name=dataset_name,
            cases=tuple(converted),
            seed=seed,
            generator=f"datagen/{build.get('generator', 'nemo-data-designer')}",
        )
        manifest = target_dir / "dataset.json"
        manifest.write_text(
            json.dumps(codec.dataset_to_dict(dataset), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nmanifesto -> {manifest}")
    except ConvertError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
