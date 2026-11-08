# tests/infrastructure/tools/

Testes de `src/caio_code/infrastructure/tools/`: sandbox, filesystem, shell,
search e a seleção de backend do deepagents.

## Cobertura mínima

- `test_sandbox.py`: fuga por `..`, caminho absoluto, symlink (arquivo e
  diretório-pai), diretório negado, `relative`/`is_within`.
- `test_filesystem.py`: round trip read/write/edit; edit sem match e com
  múltiplos matches; truncamento com marcador acima do teto; tools LangChain
  devolvem erro como texto.
- `test_shell.py`: recusa com execução desabilitada; timeout; exit não zero
  como string; `shell_backend` None quando desabilitado.
- `test_search.py`: grep pula binários e diretórios negados; limite de
  resultados; regex inválida; `find_files`.
- `test_deepagents_backend.py`: raiz real → `FilesystemBackend`; raiz
  inexistente → `StateBackend`.

## Invariantes

- Offline: shell só roda `sys.executable`; nada de rede ou modelo real.
- Cada teste constrói sua raiz em `tmp_path` — sem estado compartilhado.
