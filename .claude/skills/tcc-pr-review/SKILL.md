---
name: tcc-pr-review
description: Revisão de pull request do repositório caio-code. Use ao abrir, revisar ou decidir o merge de um PR, ao resolver branch desatualizada e ao criar ou atualizar o card do Linear. Verifica escopo contra o card, tamanho do diff, testes das pastas alteradas, regras de fundamentos, symlinks de AGENTS.md e segredos.
---

# Revisão de PR

Um PR aqui não é só código: é a unidade de registro do experimento. O que não estiver no card e
no diff não aconteceu.

## Gate 0 — antes de olhar o diff

1. **Existe card?** O PR precisa citar um `CM-nn`. Sem card, o PR volta.
2. **O escopo do card é o escopo do diff?** Liste o que o card promete e o que o diff faz. O que
   estiver a mais vira card novo (e outro PR); o que estiver a menos mantém o card `In Progress`.
3. **A base está certa?** Primeiro PR da pilha → `main`. PR empilhado → a branch de baixo. A
   base errada quebra o stack.
4. **A branch está atualizada?** O `pre-push` já exige isso; se o PR mostra *behind*, peça
   rebase, não merge.

## Gate 1 — tamanho e forma

```bash
python scripts/ci/pr_size.py --base <base>
```

- mais de 20 arquivos: divida em PRs empilhados;
- menos de 5: aceitável para correção; para feature, provavelmente falta teste ou doc.

## Gate 2 — testes

```bash
make test-changed
```

- a pasta alterada tem teste?
- comportamento novo tem teste novo?
- a correção de bug tem teste que falha sem ela?
- nenhum teste foi enfraquecido, marcado `skip` ou teve asserção removida?

Um PR que só adiciona código sem teste não passa, mesmo que o CI fique verde (o CI só roda o
que existe).

## Gate 3 — fundamentos

Percorra `tcc-foundations` contra o diff. O que reprova na hora:

- import na direção errada entre camadas;
- número mágico (budget, limite, timeout, nome de modelo);
- `time.now()`/`random` no caminho determinístico;
- tool que aceita caminho fora da raiz;
- segunda fórmula de contagem de tokens;
- `except Exception` silencioso;
- dependência de SDK fora de `providers/`.

## Gate 4 — documentação viva

- mudou estrutura de pasta? `AGENTS.md` da pasta foi atualizado?
- `CLAUDE.md` continua sendo **symlink** para `AGENTS.md` em cada pasta?
- decisão reversível sem contexto? falta ADR em `docs/adr/`?

## Gate 5 — segurança e higiene

- nenhum `.env`, chave, token ou transcript com segredo no diff;
- nenhum artefato de build (`__pycache__`, `.venv`, `.reports/session-end/*.json`);
- nenhum `--force`, `--no-verify` ou teste desabilitado justificado por conveniência;
- commit messages no formato `CM-nn: imperative summary`.

## Gate 6 — CI

Os três workflows precisam estar verdes:

| Workflow | O que prova |
|---|---|
| `pr-tests` | testes das pastas alteradas + tamanho do PR |
| `smoke` | execução ponta a ponta em Linux, macOS e Windows |
| `main-tests` | (só após merge) suíte completa |

Vermelho não se resolve com *re-run*. Se é instável, é bug (§2 de fundamentos).

## Gate 7 — Linear

- o card está `In Progress` enquanto o PR não mergeia;
- há **um comentário por avanço**, não um comentário acumulado;
- `Done` só depois do merge e de o resultado estar documentado (ADR, README do módulo ou texto
  do TCC).

## Veredito

Responda sempre neste formato:

```markdown
## Veredito: APPROVE | REQUEST CHANGES

### Bloqueios
1. `arquivo.py:42` — o que está errado e por quê.

### Sugestões (não bloqueiam)
1. ...

### O que o PR não cobre
- ...

### Próximo passo
- rebase em `origin/main` / dividir em dois PRs / atualizar o card CM-31
```

Regras do veredito: todo bloqueio aponta `arquivo:linha`; "está bom" sem lista de verificação é
veredito inválido; dúvida sobre intenção é pergunta, não bloqueio.

## Revisão genérica

Para qualidade de código em geral (nomes, complexidade, duplicação), use a skill
`mattpocock:engineering/code-review` quando disponível. Esta skill cobre o que é específico
deste repositório — escopo, stack, Linear, determinismo e contrato de evidência — e não a
substitui.