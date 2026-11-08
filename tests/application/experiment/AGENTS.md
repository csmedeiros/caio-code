# tests/application/experiment/

Testes do experimento: `arms.py` (os nove braços existem, pipelines terminam em
`structure_repair`, combinações truncam primeiro, `select_arms` recusa nome desconhecido),
`runner.py` (um trial ponta a ponta com stubs: shape → probes → alias scoring → accounting;
overflow com `enforce_window` vira `TrialResult.error`; erro de provedor idem) e `report.py`
(`results.json` parseável + `report.md` com a tabela, ambos em `tmp_path`).

Invariantes: `StubGateway`/`StubSummarizer`/`StubScorer`, `FixedClock`,
`SequentialIdentifiers`; o custo do stub é zero pela `PRICE_SHEET`.
