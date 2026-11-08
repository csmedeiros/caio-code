# src/caio_code/infrastructure/middleware/

A costura entre o grafo deepagents e as políticas de contexto do domínio — o ponto exato onde
a tese intervém no loop.

## Módulos

`context_policy.py`: `ContextPolicyMiddleware(AgentMiddleware)`. Em cada model call
(`wrap_model_call`/`awrap_model_call`):

1. `to_domain(request.messages)` → `Transcript`;
2. `fixed_tokens` = system message + schemas das tools;
3. `pipeline.plan(PolicyRequest)` → `PipelineDecision`; publica `ContextShaped` no bus;
4. `enforce_window` + estouro → `ContextOverflowError` (braço `baseline_capped`);
5. `apply_pipeline` aplica as decisões **por índice** sobre as mensagens originais do
   provedor (identidade preservada → prompt cache continua valendo, ADR 0003/0004c);
6. no caminho async, placeholder de compactação → `CompactionService.compact` → mensagem
   ancorada real no lugar, e `compactions` incrementa.

## Invariantes

- O middleware não contém política: o pipeline vem injetado no construtor. Aqui só há
  tradução, medição e aplicação.
- Sem serviço de compactação injetado, o placeholder fica — no relatório isso lê como
  "compactação planejada e não executada", nunca como resumo vazio.
- Contadores (`compactions`, `truncated_tool_outputs`) e `last_decision` ficam no middleware;
  o `ContextSnapshot` do runner vem do evento `ContextShaped`, para TUI e ledger verem os
  mesmos números.
- `run_id` é atributo mutável definido pelo runner a cada run (`_set_run_id`).
- Caminho sync não chama modelo: compactação só no async.

## Testes

`tests/infrastructure/middleware/` (pasta criada; os testes do middleware são pendência —
hoje o comportamento é exercitado via `tests/application/agent/test_runner.py`), com pipeline
real do domínio, `StubChatModel`/handler falso, `FixedClock` e `EventRecorder`.
