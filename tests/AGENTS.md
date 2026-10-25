# tests/

Suíte espelhada de `src/`. O caminho do teste diz qual módulo ele cobre:
`src/caio_code/context/window.py` → `tests/context/test_window.py`.

## Invariantes

- Sem rede, sem `ANTHROPIC_API_KEY`, sem ordem de execução implícita.
- Teste que exige modelo real leva `@pytest.mark.integration` e não roda no CI.
- Toda correção de bug chega com o teste que falha sem ela.
- Nome descreve comportamento: `test_window_drops_oldest_when_over_budget`.
- `test_repo_layout.py` protege as convenções do repositório (symlinks, frontmatter das
  skills, pacote importável). Se ele quebra, a estrutura está errada — não o teste.

## Como rodar

```bash
make test           # tudo
make test-changed   # só o que o PR tocou (a mesma seleção do CI)
```

## O que não entra aqui

Teste de integração com modelo real rodando no CI, snapshot gigante, fixture binária pesada.