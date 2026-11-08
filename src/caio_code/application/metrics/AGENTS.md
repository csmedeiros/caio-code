# src/caio_code/application/metrics/

Contabilidade do run a partir do stream de eventos.

## Módulos

`ledger.py`: `RunLedger(bus, pricing, model)` — assina o bus e acumula `UsageRecorded`
(usage + custo via `PriceSheet`), `CompactionEnded` (`compactions`) e `ToolCallCompleted`
(`tool_calls`, `truncated_tool_outputs`); `accounting() -> RunAccounting`; `reset()` por run.

## Invariantes

- O ledger **assina o bus** em vez de ser chamado pelo runner: um braço do experimento e uma
  sessão interativa são medidos pelo mesmo código.
- Custo é sempre `PriceSheet.cost_of` do domínio — nenhum call site refaz a conta.
- `record()` existe para chamadas que não passaram pelo bus (harness de avaliação); o modelo
  efetivo atualiza o ledger.
- Sem relógio, sem rede, sem estado além dos acumuladores.

## Testes

`tests/application/metrics/`, publicando eventos sintéticos num `InMemoryEventBus` com
`FixedClock`.
