# src/caio_code/application/todos/

O caso de uso do todo tracking.

## Módulos

`service.py`: `TodoTracker` (`replace_from_tool_arguments`, `replace`, `mark`, `board`,
`revisions`) e `parse_todo_arguments` (aceita `{"todos": [...]}` ou lista pura, chaves
tolerantes `content|text|title`, prioridade inválida cai no default).

## Invariantes

- O tool `write_todos` envia a lista inteira a cada chamada; o tracker só valida e substitui
  o board (`TodoBoard.replace` renumera a ordem).
- `TodoBoardUpdated` é publicado **pelo runner**, não pelo tracker (`publish=False` padrão):
  dois publicadores dobrariam cada update da sidebar. `publish=True` só quando nada mais é
  dono do evento.
- Payload inválido → `ToolError` nomeando a posição e o valor; conteúdo acima de
  `MAX_CONTENT_CHARS` é truncado com `…`; status desconhecido → erro.
- A marcação manual (`mark`) preserva o invariante de um único `in_progress`.
- Tempo e ids vêm do `Clock`/`IdentifierFactory` injetados.

## Testes

`tests/application/todos/`; o caminho via grafo (runner interceptando `write_todos`) é
coberto por `tests/application/agent/test_runner.py`.
