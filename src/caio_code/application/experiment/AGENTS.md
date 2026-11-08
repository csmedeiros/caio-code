# src/caio_code/application/experiment/

O experimento do Capítulo 4: braços, runner e relatórios.

## Módulos

| Módulo | Conteúdo |
|---|---|
| `arms.py` | `ArmSpec` e `default_arms(settings)`: os **nove braços**; helpers `_single`/`_combined` — truncagem primeiro nas combinações, `StructureRepairPolicy` sempre por último (ADR 0004b) |
| `runner.py` | `ExperimentDependencies`, `ExperimentRunner.run/run_trial` (shape → probes → alias scoring → accounting), `parse_answers`/`score_answers`, `build_dependencies`, `run_experiment`, `main` (usada pelo `caio-code evaluate`) |
| `report.py` | `write_report`: `<out>/<run_id>/results.json` (evidência) + `report.md` (tabela comparativa e retention por posição) |

## Invariantes

- Um trial: caso → pipeline do braço → contexto moldado → probes como última mensagem pinned
  → resposta JSON → `answer_matches` por alias. O modelo nunca vê o histórico sem moldar (em
  braço gerenciado) nem as probes antes de responder.
- A única diferença entre braços é a política: mesmos casos, mesmo modelo, mesmas probes.
- Tudo que o trial gasta é contado: a chamada de probe e, nos braços de compactação, a
  chamada do summarizer. Cache = `cached_tokens` do provedor; custo = `PriceSheet` em USD.
- Overflow com `enforce_window` (braço `baseline_capped`) é resultado registrado
  (`TrialResult.error`), não exceção engolida; erro de provedor idem.
- Determinismo: relógio e identificadores injetados; seed do dataset em
  `EvalConfig.seed`; concorrência explícita (`asyncio.Semaphore`).
- `select_arms` com nome desconhecido → `ValueError` listando os braços disponíveis.

## Testes

`tests/application/experiment/`, offline com `StubGateway`/`StubSummarizer`/`StubScorer` e
relatórios em `tmp_path`. O relatório commitado de referência vive em `.reports/evals/`.
