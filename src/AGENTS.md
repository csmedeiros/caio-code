# src/

Código do agente. Tudo que é importável pelo pacote `caio_code` vive aqui; nada que seja
ferramenta de desenvolvimento (`scripts/`), teste (`tests/`), dados de avaliação (`evals/`)
ou documentação (`docs/`).

## Invariantes

- Um pacote por camada: `domain`, `application`, `infrastructure`, `presentation` (ADR 0003).
- Regra de dependência: `presentation → application → domain ← infrastructure`.
  `domain` não importa nada do pacote (exceção única: `caio_code.config`).
- A verificação automática (`tests/test_layering.py`) ainda não existe; enquanto isso a regra
  vale por revisão — pendência registrada no ADR 0003.
- Nenhum código executável no `__init__.py` de pacote: só reexportações explícitas.
- Nenhuma dependência de framework (LangChain, deepagents, openai, textual) fora de
  `infrastructure/`, `application/agent/` e `presentation/`; o `domain` é puro.

## Regras

- Siga `.claude/skills/tcc-foundations/SKILL.md`.
- Código e identificadores em inglês; comentários explicativos em português.
- Nada de número mágico: configuração em `caio_code/config.py`.

## Testes

Espelhados em `tests/<mesmo caminho>/`. Um módulo novo sem teste não entra.
