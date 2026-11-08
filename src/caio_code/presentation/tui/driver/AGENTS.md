# src/caio_code/presentation/tui/driver/

O driver headless: como um agente de IA (ou um teste) dirige a TUI sem terminal. É a
razão de ser deste pacote — cenários tipados executados pelo `Pilot` do Textual, com
relatórios legíveis por máquina e por gente.

## Mapa de módulos

| Módulo | Papel |
|---|---|
| `steps.py` | passos tipados (`Type`, `Key`, `Wait`, `Send`, `AssertText`, `AssertTodo`, `AssertFooter`, `Snapshot`, `AssertWidget`) e o parser de scripts texto |
| `pilot_driver.py` | `TuiDriver.run_scenario`: executa passos dentro de `App.run_test`, registra status/elapsed/screen text por passo |
| `report.py` | `DriverReport`, `StepRecord`, `write_json`, `as_markdown` |
| `scenarios.py` | `SCENARIOS`: smoke, todo_sidebar, compaction, interrupt, demo — todos com `ScriptedFacade`, offline |
| `cli.py` | `main(argv)`; flags `--scenario/--script/--stdin/--size/--reports-dir/--continue-on-error/--json/--markdown` |
| `errors.py` | `DriverError`, `ScenarioError`, `ScriptError`, `DriverAssertionError`, `WidgetLookupError` |
| `text.py` | extração de texto: `screen_text(app)` (o que está pintado) e `widget_text(widget)` (conteúdo completo) |

## Invariantes

- O driver é o único módulo da apresentação que pode importar
  `infrastructure/observability/clocks.py` (`FixedClock` nos testes, `SystemClock` no CLI).
- Queries usam `app.screen.query*` — `app.query` não enxerga telas modais empurradas.
- `Snapshot` grava `NNN-<nome>.svg` e `NNN-<nome>.txt` em `reports_dir/<cenário>/`.
- Assert falhou → `DriverAssertionError` com índice do passo, esperado e real; com
  `continue_on_error=True` o relatório acumula as falhas sem levantar.
- Scripts texto: um passo por linha, `#` comenta; verbo desconhecido → `ScriptError`.
- Exit code do CLI: 0 só se todas as asserções passaram; 1 falha de asserção; 2 uso inválido.
