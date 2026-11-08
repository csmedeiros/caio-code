# tests/infrastructure/middleware/

Testes do `ContextPolicyMiddleware` (pasta criada; os testes são pendência — hoje o
comportamento é exercitado por `tests/application/agent/test_runner.py`).

Cobertura exigida quando chegar: pipeline aplicado por índice a cada model call (identidade
preservada), `ContextShaped` publicado com o `run_id` do runner, `enforce_window` + estouro →
`ContextOverflowError`, placeholder de compactação → `CompactionService` no caminho async (e
ausente no sync), contadores `compactions`/`truncated_tool_outputs`.

Invariantes: `FixedClock`, bus com `EventRecorder`, handler falso — nunca um modelo real.
