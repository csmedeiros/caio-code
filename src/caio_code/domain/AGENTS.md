# src/caio_code/domain/

O núcleo puro: o modelo do problema, sem SDK, sem I/O, sem relógio, sem rede.

## Subpacotes e módulos

| Caminho | Conteúdo |
|---|---|
| `errors.py` | `CaioCodeError` e todas as subclasses tipadas; `except: pass` é proibido no repositório |
| `events.py` | `DomainEvent` e os 12 eventos do run, `EventBus` (Protocol), `InMemoryEventBus` |
| `conversation/` | transcript imutável, budget, rendering para o summarizer, resumo ancorado |
| `policy/` | o contrato `ContextPolicy` e as seis políticas (base, full_history, sliding_window, message_selection, compaction, tool_output, structure_repair) |
| `ports/` | as portas: `TokenCounter`, `ModelGateway`, `Summarizer`, `RelevanceScorer`, `Clock`/`IdentifierFactory`, `TranscriptStore`/`ResultStore` |
| `todo/` | `TodoItem`, `TodoStatus`, `TodoBoard` (o estado que a sidebar renderiza) |
| `usage/` | `TokenUsage`, `CacheStats`, `Cost` (Decimal), `PriceSheet`, `RunAccounting`, `UsageLedger` |
| `evaluation/` | `CriticalFact`, `Probe`, `HistoryCase`, `EvalDataset`, `TrialResult`, `pass_at_k`, `ArmAggregate`, `ExperimentReport` |

## Invariantes

- Nada aqui importa `application/`, `infrastructure/` ou `presentation/`.
- A única exceção de import dentro do pacote é `caio_code.config` (números: `PRICE_SHEET`,
  `FALLBACK_PRICE`, `CHARS_PER_TOKEN`) — deliberação do ADR 0003.
- Nenhum import de terceiros (LangChain, openai, textual, deepagents): o domínio fala
  `Message`/`Transcript`, e `infrastructure/mappers/` é a única ponte.
- Tempo e identidade nunca são lidos: chegam pelos ports `Clock`/`IdentifierFactory`, e todo
  evento carrega `at` preenchido pelo chamador.
- Políticas são planners puros: `plan(PolicyRequest) -> PolicyDecision`; quem aplica a decisão
  é o chamador, por índice (ADR 0003/0004).
- Dataclasses de valor são `frozen=True, slots=True`; validação no `__post_init__`.

## Testes

`tests/domain/` (policy, conversation). Sem fixture de I/O: se um teste do domínio precisa de
arquivo ou rede, o código testado está na camada errada.
