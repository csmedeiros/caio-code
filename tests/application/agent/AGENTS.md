# tests/application/agent/

Testes do caso de uso do agente: prompt, sessão, runner, facade e stub model.

## Cobertura exigida

- `test_prompt.py`: o prompt inclui política, janela, root e as seções
  autoritativas do resumo.
- `test_session.py`: `ContextSnapshot.from_decision` (pipeline e política única)
  e `AgentRunResult.as_record` serializável.
- `test_stub_model.py`: script consumido em ordem, usage metadata no formato
  OpenAI, determinismo.
- `test_runner.py`: stream completo (ordem dos eventos, accounting não nulo),
  `interrupt()` -> status `interrupted`, guard dispara na terceira chamada
  idêntica e o advisory chega ao modelo, `write_todos` atualiza o board e
  publica `TodoBoardUpdated`.
- `test_facade.py`: o protocolo `AgentFacade` sobre o runner.

## Como rodar

```bash
.venv/bin/python -m pytest tests/application/agent -q
```
