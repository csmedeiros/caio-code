# tests/infrastructure/persistence/

Testes de `src/caio_code/infrastructure/persistence/`: o codec JSON e os
stores de arquivo.

## Cobertura mínima

- `test_codec.py`: round trip preservando `pinned`, `tool_calls` (tupla) e
  `metadata`; chaves exatas do envelope; versão desconhecida e campo
  malformado levantam `StorageError` nomeando o campo.
- `test_jsonl.py`: append/read na ordem de escrita; linha corrupta com arquivo
  e número da linha no erro; run inexistente; transcript store round trip,
  `list_sessions` ordenado, escrita atômica sem sobra de `.tmp`.

## Invariantes

- Offline e determinístico; tudo em `tmp_path`.
- O envelope testado aqui é contrato público: outro agente o reutiliza.
