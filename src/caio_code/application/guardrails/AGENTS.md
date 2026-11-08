# src/caio_code/application/guardrails/

Guardrails do loop do agente. Hoje existe um: a detecção de tool repetida.

## Módulos

`repeated_tool_call.py`: `RepeatedToolCallGuard` (`inspect(tool, arguments, run_id) ->
GuardrailVerdict`), `normalize_arguments` (JSON canônico: ordem de chave e whitespace não
escondem repetição) e o `ADVISORY_TEMPLATE`.

## Invariantes

- O guard é deliberadamente estreito: mesmo nome + mesmos argumentos normalizados, dentro de
  uma janela deslizante de `GuardrailConfig.window_messages` chamadas; dispara a partir da
  `max_repeats`-ésima. Guard largo pararia retry legítimo.
- Quando dispara **não aborta o run**: publica `GuardrailFired` no bus e devolve o advisory,
  que o runner retorna como `ToolMessage` no lugar do resultado — é a única forma de o modelo
  saber que o loop foi detectado.
- Sem relógio próprio: `Clock` injetado; sem clock, eventos usam o `EPOCH` fixo (nunca `now()`).
- O advisory manda reler o resumo ancorado (Next Move / Relevant Files) antes de tentar outra
  coisa — conecta o guardrail à gestão de contexto.

## Testes

`tests/application/guardrails/`; o efeito ponta a ponta (advisory chegando ao modelo na
terceira chamada idêntica) é coberto por `tests/application/agent/test_runner.py`.
