# src/caio_code/domain/evaluation/

O modelo do experimento do Capítulo 4: casos, sondas, pontuação de um trial e agregação de um
braço. O dataset em si vive em `evals/datasets/` (congelado) e é carregado por
`infrastructure/datasets/`.

## Módulos

| Módulo | Conteúdo |
|---|---|
| `cases.py` | `CriticalFact` (position early/middle/late, aliases), `Probe`, `HistoryCase` (valida probes ↔ facts; `variant` full/spill + `SpillFile`), `EvalDataset` (ids únicos, `limited()`), `normalize_answer`, `answer_matches` (alias match) |
| `spill.py` | `derive_spill_case`/`variant_case`: a variante `spill` derivada em runtime do caso commitado (saídas de tool acima do teto de bytes viram ponteiro + `SpillFile` em memória); pura e determinística |
| `scoring.py` | `ProbeScore`, `TrialResult` (retention, usage, cache, custo, tokens before/after, overflow, compactions, `variant`, evidência de `replay`, `as_record()`), `pass_at_k` (pass^k sobre as repetições), `ArmAggregate` (médias + `retention_by_position` + stats de tool do replay, por `variant`), `ExperimentReport` |

## Invariantes

- Dataset pequeno de propósito: cinco históricos longos com fatos críticos no começo, no meio
  e no fim — o Capítulo 4 mede a diferença entre políticas no mesmo input, não o tamanho do
  benchmark.
- Invariante quebrada de dataset levanta `DatasetError` na construção: um dataset fora do
  desenho não pode virar número de capítulo.
- `pass_at_k` exige todas as k repetições de um caso corretas para contá-lo: consistência faz
  parte da claim (um agente que acerta 1 em 3 não é usável).
- Accuracy nunca sozinha: todo `TrialResult` carrega retenção, tokens, cache e custo.
- Nada aqui roda modelo: a execução é `application/experiment/runner.py`.

## Testes

Os testes ficam em `tests/application/experiment/` (runner e arms); as invariantes dos
arquivos versionados são verificadas por `tests/infrastructure/datasets/test_committed_dataset.py`.
