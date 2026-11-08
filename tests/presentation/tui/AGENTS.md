# tests/presentation/tui/

Testes da interface terminal e do driver headless. Todo teste leva
`@pytest.mark.tui` e roda através de `App.run_test()` (ou é unidade pura dos
módulos do driver). Espelham os módulos de `src/caio_code/presentation/tui/`:

| Teste | Cobre |
|---|---|
| `test_ports.py` | contrato `AgentFacade` |
| `test_theme.py` | constantes visuais |
| `test_composer.py` | enter envia, ctrl+j/shift+enter quebra linha, esc interrompe |
| `test_message_list.py` | bolhas, deltas, trim, painel de ferramenta, tecla `e` |
| `test_tool_panel.py` | resumo de argumentos, status, truncagem |
| `test_todo_sidebar.py` | header de progresso, classes por status |
| `test_usage_footer.py` | formatação e estado over budget |
| `test_scripted.py` | determinismo e interrupção da fachada offline |
| `test_app.py` | integração: boot, envio, eventos → widgets, keybindings |
| `driver/` | passos, parser, relatórios, cenários embutidos e CLI |

## Invariantes

- `FixedClock`/`SequentialIdentifiers` injetados; nada de relógio de parede nos testes.
- Esperas só com `await pilot.pause(...)`; tamanho de terminal `DEFAULT_TERMINAL_SIZE`.
- Testes do driver gravam relatórios em `tmp_path`.
