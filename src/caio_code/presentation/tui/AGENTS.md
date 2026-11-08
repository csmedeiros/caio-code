# src/caio_code/presentation/tui/

Interface terminal do agente (Textual): transcrição rolante, composer, sidebar de todos,
footer de contexto/uso e o driver headless. É a camada de apresentação: **só importa
`domain/` e `config.py`** — nunca `application/` nem `infrastructure/` (exceção única e
deliberada: o driver importa `infrastructure/observability/clocks.py` para `FixedClock`/
`SystemClock`).

## Mapa de módulos

| Módulo | Papel |
|---|---|
| `ports.py` | `AgentFacade` (Protocol): o único canal entre a UI e o agente; constantes de status de run |
| `theme.py` | todas as cores, tamanhos e o CSS; nenhum widget contém literal visual |
| `app.py` | `CaioCodeApp(App)`: assina o `EventBus`, traduz eventos em updates de widget, keybindings |
| `scripted.py` | `ScriptedFacade`: fachada offline e determinística que reproduz um script de passos |
| `widgets/` | transcript, composer, sidebar, footer, painel de ferramenta |
| `driver/` | driver headless (Pilot), cenários, relatórios e CLI `python -m caio_code.presentation.tui.driver` |

## Invariantes

- O app nunca chama modelo: chama a fachada e renderiza eventos do bus injetado.
- O bus é síncrono; o handler do app só faz `post_message(DomainEventArrived)` — nenhuma
  mutação de widget acontece fora do event loop do Textual.
- `MessageAppended` com `message_id` já visto é delta de streaming: substitui o texto no
  lugar (respeitando `TuiConfig.stream_deltas`). `role='tool'` com `message_id` igual a um
  `call_id` pendente leva o preview do resultado; `role='summary'` recebe o estilo ancorado.
- Determinismo: sem `datetime.now`/`time.time`/`random`/`uuid4`; relógio e identificadores
  são injetados (`Clock`/`IdentifierFactory` de `domain/ports/time.py`).
- Sem números mágicos: tamanhos e cores vêm de `theme.py`, limites de `config.TuiConfig`.

## Como é testado

`tests/presentation/tui/`, tudo com `@pytest.mark.tui` e `App.run_test()` headless.
Os quatro cenários embutidos do driver rodam como testes de ponta a ponta.
