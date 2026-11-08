# src/caio_code/domain/todo/

O estado do todo tracking. O board é domínio, não widget: TUI, CLI e relatórios de avaliação
leem o mesmo objeto, então o que o usuário vê é o que foi medido.

## Módulos

`items.py`: `TodoStatus` (pending/in_progress/completed/cancelled), `TodoItem` (frozen, com
`glyph` por status) e `TodoBoard`.

## Invariantes

- No máximo **um** item `in_progress`; ids únicos. Violação → `TodoInvariantError`.
- `replace` é a única mutação: o tool `write_todos` envia a lista inteira a cada chamada
  (como nos harnesses que o protótipo espelha); a ordem de exibição é renumerada
  deterministicamente (`order`, depois `id` — nunca hash).
- `progress_ratio` exclui itens cancelados do denominador.
- `as_records()` é a vista serializável usada por relatórios e pelas asserções do driver da TUI.
- Nenhum relógio: `last_updated_at` vive no tracker de aplicação, não aqui.

## Testes

Os testes ficam em `tests/application/todos/` (tracker); o comportamento visível na UI é
verificado pelos cenários `todo_sidebar` do driver (`tests/presentation/tui/`).
