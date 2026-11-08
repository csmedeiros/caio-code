# src/caio_code/

O pacote do agente: quatro camadas (ADR 0003) mais a configuração na raiz.

## Mapa de módulos

| Módulo/pacote | Camada | Papel |
|---|---|---|
| `config.py` | raiz | dataclasses frozen de configuração, `PRICE_SHEET`, `load_settings()`/`load_endpoints()`; todo número do sistema vive aqui |
| `__main__.py` | raiz | `python -m caio_code` → `presentation.cli.main:main` |
| `domain/` | domínio | políticas de contexto, transcript, resumo ancorado, eventos, erros tipados, todos, contabilidade, avaliação e as portas (`ports/`) |
| `application/` | aplicação | casos de uso: `agent/` (runner deepagents + fachada), `compaction/`, `experiment/`, `todos/`, `guardrails/`, `selection/`, `metrics/` |
| `infrastructure/` | infraestrutura | adaptadores: `llm/`, `tokens/`, `tools/`, `middleware/`, `mappers/`, `persistence/`, `datasets/`, `observability/`, `pricing/` |
| `presentation/` | apresentação | `cli/` (argparse, composição, stdout) e `tui/` (Textual, widgets, driver headless) |

## Invariantes

- `config.py` não importa nenhum outro módulo do pacote.
- `domain/` não importa `application/`, `infrastructure/` nem `presentation/`, e não importa
  SDK de terceiros (a única exceção de import é `config`).
- A CLI (`presentation/cli/main.py`) é a única que lê `sys.argv`, imprime em stdout e produz
  o exit code do processo.
- O loop agêntico pertence ao deepagents (ADR 0002); o pacote contribui o middleware de
  políticas de contexto, o guard de tool repetida e os eventos.
- Decisões de política são aplicadas por índice sobre as mensagens originais do provedor
  (`infrastructure/mappers/langchain.py`), preservando identidade para o prompt cache.

## O que não entra aqui

Código de experimento ad-hoc, notebooks de análise e dados de avaliação (vivem em `evals/` e
`.reports/`).
