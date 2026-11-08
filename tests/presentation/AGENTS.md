# tests/presentation/

Testes da camada de apresentação (TUI). Espelham `src/caio_code/presentation/`.

## Invariantes

- Tudo offline: `ScriptedFacade` + `InMemoryEventBus` + `FixedClock`; nenhum modelo, rede
  ou relógio de parede.
- Sem `time.sleep`/`asyncio.sleep` com atraso real: `await pilot.pause()` é a espera.
- Terminal pequeno (100x30) para a suíte ser rápida.

## Como rodar

```bash
.venv/bin/python -m pytest tests/presentation -q
```
