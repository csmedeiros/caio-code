# tests/application/metrics/

Testes do `RunLedger`: `UsageRecorded` acumula usage e custo pela `PriceSheet`,
`CompactionEnded` incrementa `compactions`, `ToolCallCompleted(truncated=True)` incrementa
`truncated_tool_outputs`, `reset()` zera preservando o modelo, `record()` direto para
chamadas fora do bus.

Invariantes: eventos sintéticos publicados num `InMemoryEventBus`; valores de fixture com
custo calculável à mão pela price sheet do stub (zero) e de um modelo tabelado.
