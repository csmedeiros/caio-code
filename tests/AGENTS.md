# tests/

Suíte espelhada de `src/`. O caminho do teste diz qual módulo ele cobre:
`src/caio_code/domain/policy/compaction.py` → `tests/domain/policy/test_compaction.py`.

## Invariantes

- Sem rede, sem chave de API, sem ordem de execução implícita. Provedor `stub`,
  `FixedClock`, `SequentialIdentifiers` e `tmp_path` em tudo.
- Teste que exige modelo real leva `@pytest.mark.integration` e não roda no CI; testes da TUI
  levam `@pytest.mark.tui` e rodam via `App.run_test()` headless.
- Toda correção de bug chega com o teste que falha sem ela.
- Nome descreve comportamento: `test_window_drops_oldest_when_over_budget`.
- `test_repo_layout.py` protege as convenções do repositório (AGENTS.md + symlink CLAUDE.md
  por diretório, frontmatter das skills, `FEATURE_TREE.md`, pacote importável). Se ele quebra,
  a estrutura está errada — não o teste.
- Os diretórios `context/`, `harness/`, `providers/`, `state/`, `tools/` e `scripts/` são
  resíduo do layout antigo (só `__init__.py`); a remoção é pendência no `AGENTS.md` raiz.
  Não adicione testes neles.

## Como rodar

```bash
make test           # tudo
make test-changed   # só o que o PR tocou (a mesma seleção do CI)
```

## O que não entra aqui

Teste de integração com modelo real rodando no CI, snapshot gigante, fixture binária pesada.
