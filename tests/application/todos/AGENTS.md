# tests/application/todos/

Testes do `TodoTracker` e do `parse_todo_arguments`: payload `{"todos": [...]}` e lista pura,
chaves tolerantes, prioridade inválida → default, status desconhecido → `ToolError`, conteúdo
vazio → erro, truncamento em `MAX_CONTENT_CHARS`, `mark` preserva um único `in_progress`,
`replace` renumera a ordem, `publish=True` publica `TodoBoardUpdated` (e o padrão não publica).

Invariantes: `FixedClock`, `SequentialIdentifiers`; o board é comparado por `as_records()`.
