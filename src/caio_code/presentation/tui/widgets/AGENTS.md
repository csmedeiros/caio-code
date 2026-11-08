# src/caio_code/presentation/tui/widgets/

Widgets da interface. Nenhum widget conhece o agente, o bus ou o driver: cada um expõe
métodos de atualização que o `app.py` chama ao traduzir eventos de domínio.

## Mapa de módulos

| Módulo | Widget | Papel |
|---|---|---|
| `message_list.py` | `MessageList` (`#transcript`), `MessageBubble` | transcrição rolante; bolhas por role; `full_text()` exporta tudo, visível ou não |
| `composer.py` | `Composer` (`#composer`) | entrada multi-linha; enter envia, shift+enter/ctrl+j quebra linha, esc interrompe |
| `todo_sidebar.py` | `TodoSidebar` (`#sidebar`, `#todo-header`) | estilo opencode: header `3/7 · 43%`, um item por linha com GLYPHS, independe do scroll do transcript |
| `usage_footer.py` | `UsageFooter` (`#usage-footer`) | modelo, política, fill de contexto, tokens, cache, custo, status |
| `tool_panel.py` | `ToolPanel` (`#tool-panel-<call_id>`) | painel por chamada de ferramenta; resultado colapsado expansível |

## Invariantes

- Cores e tamanhos só via constantes de `theme.py`; nada de literal visual aqui.
- Widgets não importam `application/` nem `infrastructure/`; só `domain/` e `theme.py`.
- `full_text()` é o contrato do driver: texto completo do widget, incluindo conteúdo
  colapsado ou fora do scroll.
- O composer se comunica com o app por `Message` (`Submitted`, `InterruptRequested`),
  nunca chamando a fachada diretamente.
