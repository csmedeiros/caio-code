# infrastructure/persistence/

Adaptadores de persistência: implementam as portas `TranscriptStore` e
`ResultStore` de `domain/ports/storage.py`.

## Módulos

| Módulo | Papel |
|---|---|
| `codec.py` | Serialização JSON de `Message`/`Transcript` no envelope versionado |
| `jsonl.py` | `JsonlResultStore` (JSONL por run, fsync a cada append) e `JsonTranscriptStore` (um envelope por sessão, escrita atômica via `os.replace`) |

## O envelope (contrato público — outro agente reutiliza)

```json
{"version": 1, "session_id": "<str>", "messages": [<message>, ...]}
```

Chaves de mensagem: `id, role, text, tool_calls [{id, name, arguments}],
tool_call_id, name, pinned, metadata`. `tokens` é cache e não é serializado.
Tuplas em `metadata` viram listas JSON; `tool_calls` volta como tupla, que é o
que o dataclass espera. Versão desconhecida ou mensagem malformada levanta
`StorageError` nomeando o campo.

## Invariantes

- Todo `StorageError` nomeia o valor ofensivo: arquivo, número da linha, campo.
- `append` faz flush + fsync: um crash preserva os registros já escritos.
- `save` de transcript é atômico (arquivo temporário + `os.replace`).
- Ids de run/sessão são nomes de arquivo seguros (sem separadores, sem `..`).
- Nenhum timestamp gerado aqui: determinismo; se um registro precisar de hora,
  quem injeta é o chamador (Clock), não o store.

## O que nunca importar aqui

`harness`, `cli`, `providers`, langchain. Só `config`, `domain` e stdlib.

## Testes

Espelhados em `tests/infrastructure/persistence/`, offline: round trip,
linha corrupta, versão desconhecida, ordenação de `list_sessions`.
