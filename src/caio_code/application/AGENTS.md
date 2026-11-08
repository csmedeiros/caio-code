# src/caio_code/application/

A camada de casos de uso. Cada subpacote é um caso de uso com estado próprio mínimo; tudo que
é regra pura vive em `domain/`.

## Subpacotes

| Pacote | Caso de uso |
|---|---|
| `agent/` | o runner do grafo deepagents, a fachada da TUI, o system prompt, o modelo stub |
| `compaction/` | `CompactionService`: a única chamada de modelo para resumir (plan → summarize → replace → account) |
| `evaluation/` | chat-replay do Capítulo 4 (v5): `ChatReplayRunner` (seed → molda 1x → sondas in-band → juiz), `ReplayToolServer`, `LlmJudge` + calibração, relatórios com coluna variant |
| `experiment/` | os nove braços (`arms.py`), o runner do experimento (`runner.py`) e os relatórios (`report.py`) |
| `guardrails/` | `RepeatedToolCallGuard`: tool idêntica repetida → advisory ao modelo |
| `metrics/` | `RunLedger`: usage/cache/custo acumulados a partir dos eventos do bus |
| `selection/` | `SelectionService`: task → scores por mensagem para a política de seleção |
| `todos/` | `TodoTracker`: argumentos do `write_todos` → `TodoBoard` validado |

## Invariantes

- Importa `domain` sempre; `presentation` nunca. `infrastructure` aparece onde o caso de uso
  orquestra adaptadores (o runner e o experiment runner) — exceção delimitada no ADR 0003.
- Tempo e identidade só pelos ports injetados (`Clock`, `IdentifierFactory`).
- Progresso é reportado por **eventos** no bus (`domain/events.py`), nunca por callback ad hoc:
  TUI, ledger e harness de avaliação assinam o mesmo stream.
- Colaboradores chegam prontos por injeção (`AgentDependencies`, `ExperimentDependencies`);
  nada é construído implicitamente dentro de um caso de uso.
- Erros são capturados, registrados no resultado e publicados (`RunFinished.error`) — nunca
  engolidos.

## Testes

`tests/application/<pacote>/`, offline: stub provider, `FixedClock`, bus em memória,
`EventRecorder` para a ordem dos eventos.
