# tests/infrastructure/observability/

Testes de relógios, eventos e tracing.

| Arquivo | Cobre |
|---|---|
| `test_clocks.py` | `FixedClock` (start tz-aware obrigatório, avança `step_ms` por leitura), `SequentialIdentifiers` (`prefix-0001`, sem uuid), `SystemClock` só monotônico |
| `test_bus.py` | `EventRecorder` (`.of_type`, `.counts`, `.clear`), `to_record` para **todas** as classes de `domain/events.py`, evento novo sem mapeamento → erro, `JsonlEventHandler` não lança para o publisher |
| `test_langsmith.py` | tracing off sem chave, on com chave (via env monkeypatchado), `tracing_disabled()` força off, chave nunca impressa |

Invariantes: sem rede; env monkeypatchado e restaurado pelo pytest; `tmp_path` para o JSONL.
