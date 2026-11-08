# src/caio_code/presentation/cli/

A única porta de entrada de processo do pacote: `python -m caio_code` e o
console script `caio-code` (`caio_code.presentation.cli.main:main`).

## Módulos

| Módulo | Papel |
|---|---|
| `main.py` | argparse (subcomandos `run`, `tui`, `compact`, `evaluate`, `classify`, `doctor`), despacho, códigos de saída; único lugar que lê `sys.argv`, imprime em stdout e falha com mensagem de uma linha |
| `composition.py` | raiz de composição: `Settings` -> `AgentDependencies` -> `AgentRunner` com grafo pronto; único lugar da apresentação que importa infrastructure |
| `formatting.py` | formatação pura (bloco de métricas, JSON); nada de I/O além do writer |
| `commands/` | um módulo por verbo, cada um uma função `(Namespace) -> int` |

## Invariantes

- Somente stdlib para parsing (argparse); nenhum typer/click.
- `evaluate` importa `caio_code.application.experiment.runner` **lazy** e
  falha com `ConfigurationError` tipado se o módulo ainda não existe. Com
  `--variants`, delega ao chat-replay (`application/evaluation/replay.py`).
- `doctor` reporta nomes de variáveis de ambiente, NUNCA valores; exits
  non-zero quando o provedor pedido não tem credenciais.
- Erros tipados (`CaioCodeError`) viram `error: ...` no stderr + exit 1, nunca
  traceback.
- Políticas nomeadas vêm de `composition.POLICY_NAMES`; números vêm de
  `config.py` (exceção documentada: `SEARCH_MAX_RESULTS`).

## Testes

Espelhados em `tests/presentation/cli/`, todos com `--provider stub`.
