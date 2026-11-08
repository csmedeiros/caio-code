# ADR 0003 — Camadas DDD e a regra de dependência

- **Status:** aceito (substitui o mapa `cli → harness → folhas` do ADR 0001)
- **Data:** 2026-10-31

## Contexto

O mapa do ADR 0001 (`cli → harness → {context, providers, tools, state}`) descrevia um agente
com loop próprio. Com o ADR 0002 o loop passou a ser do deepagents, e o pacote cresceu para
além das quatro folhas: casos de uso (compactação, experimento, todos, guardrails), portas de
domínio, adaptadores de infraestrutura e duas bordas de apresentação (CLI e TUI). Era preciso
um mapa que dissesse, para qualquer módulo novo, onde ele mora e o que ele pode importar.

## Decisão

Quatro camadas, na direção:

```
presentation ──▶ application ──▶ domain ◀── infrastructure
```

- **`domain/`** — o modelo do problema: mensagens e transcript imutáveis
  (`conversation/`), as políticas de contexto como planners puros (`policy/`), eventos
  (`events.py`), erros tipados (`errors.py`), todo board (`todo/`), contabilidade de
  tokens/cache/custo (`usage/`), modelo de avaliação (`evaluation/`) e as **portas**
  (`ports/`: `TokenCounter`, `ModelGateway`, `Summarizer`, `RelevanceScorer`, `Clock`,
  `IdentifierFactory`, `TranscriptStore`, `ResultStore`). Não importa nada do pacote —
  exceção única e deliberada: `caio_code.config`, onde vivem os números (`PRICE_SHEET`,
  `CHARS_PER_TOKEN`).
- **`application/`** — casos de uso: `agent/` (runner, fachada, prompt), `compaction/`,
  `experiment/`, `todos/`, `guardrails/`, `selection/`, `metrics/`. Importa `domain`; o
  runner importa também peças de `infrastructure` (mappers, backend de tools, middleware)
  porque é ele quem orquestra o grafo.
- **`infrastructure/`** — adaptadores das portas: `llm/`, `tokens/`, `tools/`,
  `persistence/`, `datasets/`, `observability/`, `pricing/`, `mappers/`, `middleware/`.
  Importa `domain` e, onde um caso de uso é orquestrado, `application`.
- **`presentation/`** — `cli/` (único leitor de `sys.argv`/stdout/exit code; a raiz de
  composição `cli/composition.py` é o único ponto da apresentação que monta
  `infrastructure` livremente) e `tui/` (só `domain` + `config`, com exceção documentada
  para os relógios no driver).

### Políticas como planners puros, decisões aplicadas por índice

Uma política recebe `PolicyRequest` (transcript, budget, counter) e devolve
`PolicyDecision` — `kept_indices`, `removals`, `substitutions`, `injected`, `insert_at` —
sem produzir lista de mensagens de provedor e sem I/O. Quem aplica é o chamador:
`PolicyDecision.result()` no domínio, `apply_decision()` nos mappers LangChain.

A aplicação é **por índice sobre a lista original**: mensagens mantidas continuam sendo os
*MESMOS objetos* `BaseMessage`. Isso preserva identidade, e identidade é o que o prompt
caching do provedor usa para cobrar `cached_tokens` menor — reconstruir as mensagens a cada
turno destruiria o cache e invalidaria a métrica de custo do Capítulo 4.

### Verificação

A direção dos imports é verificada por `tests/test_layering.py` (AST por módulo: `domain` não
importa `application`/`infrastructure`/`presentation` nem pacote de terceiros; `application` não
importa `presentation`; a exceção `application -> infrastructure` aparece na lista de permitidos,
não como falha). O mesmo teste cobre duas regras que sustentam a medição: determinismo (nenhum
relógio de parede ou aleatoriedade fora de `infrastructure/observability/clocks.py`) e a
proibição de repetir inline um limite que o Capítulo 4 reporta.

## Consequências

- Módulo novo tem uma única pergunta a responder: qual camada? Se a resposta for "duas",
  são dois módulos.
- Portas em `domain/ports/` tornam o `stub` substituível em todo lugar: testes e CI nunca
  tocam rede.
- O runner (`application/agent/runner.py`) importa `infrastructure` — violação aparente,
  aceita e delimitada: sem ela o caso de uso central viraria uma camada extra de interfaces
  sem ganho para um protótipo de tese.
- Decisões por índice mantêm o experimento honesto: o que o provedor vê e o que o relatório
  mede são a mesma lista de objetos.

## Pendências

- [x] `tests/test_layering.py` verifica a regra acima por AST, incluindo a exceção
      `application -> infrastructure`, a ausência de terceiros no `domain`, o determinismo
      (relógio/aleatoriedade só em `infrastructure/observability/clocks.py`) e a proibição de
      limites medidos inline fora de `config.py`.
- [ ] `make layering` já existe e pula com aviso enquanto o teste não chega.

## Alternativas descartadas

- **Manter o mapa do ADR 0001.** Não descreve mais o pacote: não há `harness`, e as folhas
  viraram sete subpacotes de infraestrutura mais sete de aplicação.
- **Hexagonal estrito (application sem importar infrastructure).** Exigiria portas extras só
  para isolar mappers e backend do runner; custo de indireção sem benefício de medição.
- **Políticas devolvendo mensagens prontas.** Perderia a preservação de identidade (cache),
  obrigaria round-trip com perda e acoplaria o domínio ao formato do provedor.
