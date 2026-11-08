# src/caio_code/application/compaction/

O caso de uso da compactação: o único lugar que chama um modelo para resumir.

## Módulos

`service.py`: `CompactionService.compact()/compact_sync()` e `CompactionOutcome`. Fluxo:
lê o prompt do metadata da decisão do `CompactionPlanner` → `CompactionStarted` no bus →
`summarizer.asummarize(prompt, max_tokens)` → `parse_summary` → `summary_message_from`
(substitui o placeholder `[summary pending]`) → re-medida com o `TokenCounter` → 
`CompactionEnded` (usage, custo via `PriceSheet`, `well_formed`).

## Invariantes

- O planner é puro (domínio); só este serviço faz o I/O do summarizer. O prompt vem do
  metadata `compaction_prompt` da decisão — sem prompt, `SummarizerError`.
- Resumo vazio ou sem as cinco seções NÃO falha o run: `well_formed=False` no evento e no
  outcome, e o chamador mantém o head que já tinha. Compactação ruim degrada para
  "não compactou", nunca destrói o contexto em silêncio.
- `tokens_after` é re-medido com o resumo real no lugar do placeholder (o planner só estima).
- Tempo vem do `Clock` injetado; `compact_sync` recusa rodar dentro de event loop ativo
  (`SummarizerError`).
- O custo da chamada do summarizer entra na conta do trial/run (ADR 0004c).

## Testes

`tests/application/compaction/`, com `StubSummarizer` (sempre bem formado) e `FixedClock`.
