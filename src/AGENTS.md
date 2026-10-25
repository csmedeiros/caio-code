# src/

Código do agente. Tudo que é importável pelo pacote `caio_code` vive aqui; nada que seja
ferramenta de desenvolvimento (`scripts/`), teste (`tests/`) ou documentação (`docs/`).

## Invariantes

- Um pacote por camada: `harness`, `context`, `providers`, `tools`, `state`.
- A direção dos imports é verificada por `tests/test_layering.py`: `cli → harness → folhas`.
- As folhas não importam `harness` nem `cli`, e não importam umas às outras.
- Nenhum código executável no `__init__.py` de pacote: só reexportações explícitas.

## Regras

- Siga `.claude/skills/tcc-foundations/SKILL.md`.
- Código e identificadores em inglês; comentários explicativos em português.
- Nada de número mágico: configuração em `caio_code/config.py`.

## Testes

Espelhados em `tests/<mesmo caminho>/`. Um módulo novo sem teste não entra.