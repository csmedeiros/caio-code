# infrastructure/observability/

Relógios, identificadores, registro de eventos e tracing.

## O que vive aqui

| Módulo | Conteúdo |
|---|---|
| `clocks.py` | `SystemClock` (tempo real; só a raiz de composição usa), `FixedClock` (determinístico, avança `step_ms` por leitura), `SequentialIdentifiers` (contador, sem `uuid4`) |
| `bus.py` | `EventRecorder` (coleta em memória, `.of_type`, `.counts`, `.clear`), `to_record` (serializa toda classe de `domain/events.py`), `JsonlEventHandler` (uma linha JSON por evento) |
| `langsmith.py` | `configure_tracing(settings)` (ativa só com `LANGSMITH_API_KEY`), `tracing_disabled()` (context manager) |

## Invariantes

- `datetime.now()`/`time.monotonic()` só aparecem dentro de `SystemClock`; todo o resto
  do pacote recebe um `Clock` injetado.
- `to_record` cobre **todas** as classes de `domain/events.py`; evento novo sem mapeamento
  levanta `TypeError` em vez de sumir silenciosamente.
- `JsonlEventHandler` nunca lança para dentro do publisher: erro de escrita/serialização
  vai para stderr com o nome do evento.
- A chave do LangSmith nunca é impressa nem interpolada em mensagem de erro.
- `FixedClock` exige `start` timezone-aware.

## O que nunca entra aqui

- Domínio de contexto, provedores de modelo ou LangChain. Este pacote só implementa as
  portas `Clock`/`IdentifierFactory` e consome `DomainEvent`.

## Como é testado

`tests/infrastructure/observability/`, offline: relógio fixo, identificadores sequenciais,
round-trip de `to_record` para cada evento, handler JSONL em `tmp_path` (inclusive com
caminho não gravável) e tracing desligado.
