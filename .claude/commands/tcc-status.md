---
description: Mostra branch, PR, card do Linear e estado do CI.
---

Carregue a skill `tcc-pr-review` e reporte, sem alterar nada:

1. branch atual e base do PR (`gh pr view --json baseRefName,state,mergeable`);
2. tamanho do diff contra a base (`python scripts/ci/pr_size.py`);
3. testes que o CI de PR vai rodar (`python scripts/ci/changed_tests.py`);
4. card do Linear correspondente (`python scripts/linear.py issues --project "$LINEAR_PROJECT_ID"`);
5. três próximos passos, cada um com o comando exato.
