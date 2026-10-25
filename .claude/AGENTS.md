# .claude/

Configuração do Claude Code neste repositório: skills, subagentes, comandos e hooks.

## Estrutura

| Caminho | Papel |
|---|---|
| `skills/tcc/` | roteador — entrypoint `/tcc` |
| `skills/tcc-foundations/` | regras fundamentais de código |
| `skills/tcc-bug-investigation/` | protocolo de investigação de bugs |
| `skills/tcc-research-writing/` | pipeline de pesquisa, evidência e escrita do TCC |
| `skills/tcc-pr-review/` | revisão de PR, Linear e stack |
| `agents/` | os cinco papéis da pipeline (researcher, verifier, writer, editor, reviewer) |
| `commands/` | `/tcc` e `/tcc-status` |
| `hooks/` | `session-end.sh` + `worker.py` (headless) |
| `settings.json` | configuração dos hooks e permissões |

## Invariantes

- Toda skill tem frontmatter com `name` (igual ao diretório) e `description` que permita
  rotear sem abrir o arquivo.
- O roteador `tcc` menciona **todas** as outras skills; `tests/test_repo_layout.py` verifica.
- Skill não duplica `AGENTS.md`: referencia. Regra que muda comportamento do agente vive na
  skill; regra de processo do repositório vive no `AGENTS.md`.
- Hooks de fim de sessão são best-effort: nunca falham a sessão, nunca bloqueiam o
  encerramento, e não disparam em sessões filhas (`CAIO_CODE_HOOK_DEPTH=1`).

## Alterar uma skill

1. Card no Linear (sim, até para skill).
2. Edite o `SKILL.md`; rode `make test` (o teste de layout valida frontmatter e roteamento).
3. Abra PR. Mudança de skill é mudança de comportamento do agente — passa por revisão.

## O que não entra aqui

Segredo, caminho absoluto da máquina, transcript de sessão.