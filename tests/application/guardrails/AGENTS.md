# tests/application/guardrails/

Testes do `RepeatedToolCallGuard`: não dispara abaixo de `max_repeats`, dispara na
`max_repeats`-ésima chamada idêntica, normalização de argumentos (ordem de chave, whitespace),
janela deslizante esquece chamadas antigas, `GuardrailFired` publicado no bus, advisory
referencia o resumo ancorado, `reset()`.

Invariantes: sem relógio de parede (o guard aceita `Clock` injetado; sem ele usa o `EPOCH`
fixo); assert no `verdict.fired/message/repeats`.
