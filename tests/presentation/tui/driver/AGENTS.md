# tests/presentation/tui/driver/

Testes do driver headless (`src/caio_code/presentation/tui/driver/`).

| Arquivo | Cobre |
|---|---|
| `test_steps.py` | passos tipados, `describe()`, parser de script texto (comentários `#`, verbo desconhecido → `ScriptError`) |
| `test_pilot_driver.py` | execução via `App.run_test(headless=True)`, `StepRecord` por passo, `DriverAssertionError` com índice/esperado/real, `continue_on_error`, snapshots SVG+txt |
| `test_scenarios.py` | as cinco fábricas (`smoke`, `todo_sidebar`, `compaction`, `interrupt`, `demo`), `resolve_scenario_names` (`all`, duplicatas, desconhecido) |
| `test_report.py` | `DriverReport.passed`, `report_to_dict`, `as_markdown`, `write_json` |
| `test_cli.py` | flags, exit codes (0/1/2), `--stdin` |

Invariantes: `ScriptedFacade` + `FixedClock`; sem terminal real, sem rede, sem sleep de parede
(`await pilot.pause()`).
