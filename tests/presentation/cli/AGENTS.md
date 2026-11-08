# tests/presentation/cli/

Testes do CLI. Todos rodam com `--provider stub`, offline, e chamam
`main(argv)` diretamente — nunca `sys.exit`.

## Cobertura exigida

- Cada subcomando (`run`, `tui`, `compact`, `evaluate`, `classify`, `doctor`) sai 0 no
  caminho stub; subcomando desconhecido sai não-zero.
- `doctor --json` não pode conter valor de segredo (assert explícito com uma
  chave falsa injetada no ambiente); a seção `decision` reporta nomes e settings
  resolvidos, e decision provider `typesafe` sem `TYPESAFE_API_KEY` sai 1.
- `classify --provider stub` sai 0, é determinístico e nunca imprime segredo.
- `run --json` grava um registro parseável com status/usage/context.
- `evaluate` falha com erro tipado enquanto o experiment runner não existe.
- `tui` é testado com `CaioCodeApp.run` patcheado (nenhum terminal real).

## Como rodar

```bash
.venv/bin/python -m pytest tests/presentation/cli -q
```
