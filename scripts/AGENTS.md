# scripts/

Automação do repositório: CI, hooks, Linear e smoke test. Nada aqui é importado pelo pacote
`caio_code` — se uma função é necessária ao agente, ela pertence a `src/`.

## Invariantes

- Só biblioteca padrão, salvo dependência já usada pelo projeto. Script de CI que precisa de
  pacote extra é um problema, não uma solução.
- Todo script tem `--help`, código de saída significativo (0 ok, 1 falha, 2 uso) e não imprime
  segredo.
- Script não assume o diretório atual: resolve a raiz a partir de `__file__`.
- Nada de efeito colateral em `make test`/`make lint`: script de leitura não escreve, script de
  escrita anuncia o que fez.

## Mapa

| Script | Papel |
|---|---|
| `ci/changed_tests.py` | diff → alvos de teste (usado pelo CI de PR e por `make test-changed`) |
| `ci/pr_size.py` | 5–20 arquivos; falha acima de 20 |
| `ci/open_pr.py` | cria branch empilhada ou abre o PR com a base certa |
| `install_hooks.py` | aponta `core.hooksPath` para `.githooks/` |
| `linear.py` | cliente GraphQL mínimo (whoami, issues, create, comment, state) |
| `smoke.py` | verificação offline multiplataforma |
| `summarize_experiment.py` | lê `.reports/evals/<run_id>/results.json` e imprime as tabelas do Capítulo 4 (retenção com desvio, pass^k, tokens de prompt vs auxiliares, custo por fato retido); nunca chama modelo nem escreve |

## O que não entra aqui

Lógica de agente, chamada de modelo, manipulação de contexto.