# src/caio_code/domain/ports/

As portas: os únicos lugares do domínio onde uma capacidade externa é nomeada.
`infrastructure/` implementa; `application/` e a raiz de composição injetam.

## Módulos

| Módulo | Porta | Implementações |
|---|---|---|
| `tokenizer.py` | `TokenCounter` (count_text/message/messages/transcript) | `infrastructure/tokens/counter.py` (char proxy, tiktoken) |
| `gateway.py` | `ModelGateway` + `ModelReply` (chamadas que o domínio faz por conta própria: probes do eval, scoring) | `infrastructure/llm/{stub,openai_compatible,typesafe}.py` |
| `summarizer.py` | `Summarizer` + `SummaryResult` (a única via de pedir um resumo) | `infrastructure/llm/{stub,openai_compatible,typesafe}.py` |
| `scorer.py` | `RelevanceScorer` + `ScoredMessage` (scores da seleção) | `StubScorer` (lexical), `ModelRelevanceScorer` |
| `time.py` | `Clock`, `IdentifierFactory` | `infrastructure/observability/clocks.py` |
| `storage.py` | `TranscriptStore`, `ResultStore`, `ResultRecord` | `infrastructure/persistence/jsonl.py` |

## Invariantes

- Protocols `runtime_checkable`, com variante sync e async onde o caso de uso precisa das duas.
- Nenhum import de SDK, arquivo ou relógio aqui; a porta nomeia a capacidade, não a tecnologia.
- O loop do agente NÃO passa por `ModelGateway`: ele pertence ao deepagents (ADR 0002). A
  porta cobre compactação, scoring, guardrails e as probes do experimento.
- `datetime.now`/`uuid4` estão banidos do caminho do agente: quem precisa de tempo ou
  identidade recebe `Clock`/`IdentifierFactory` injetados.

## Testes

Cobertos indiretamente pelos testes dos adaptadores (`tests/infrastructure/llm/`,
`observability/`, `persistence/`, `tokens/`) e pelos contratos estruturais usados em
`application/agent/bridges.py`.
