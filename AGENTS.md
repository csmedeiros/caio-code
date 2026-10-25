# CLAUDE.md — caio-code

> **Regra zero — este arquivo é a memória do repositório.** Toda sessão nova começa lendo
> isto. Se ele ficar desatualizado, a próxima sessão refaz trabalho ou desfaz uma decisão
> deliberada. Ao terminar qualquer tarefa, atualize a seção afetada **antes** de considerar a
> tarefa concluída.
>
> `AGENTS.md` é o arquivo canônico; `CLAUDE.md` é um **symlink** para ele. Edite sempre
> `AGENTS.md`; nunca substitua o symlink por uma cópia. A mesma regra vale em cada subpasta.

`caio-code` é o agente de codificação desenvolvido na Parte III do TCC *Context Is All You
Need*. Ele vive dentro de `~/tcc/` por conveniência, mas é um **repositório git independente**,
ignorado pelo repositório da monografia. Nada aqui é versionado pelo TCC, e o texto do TCC não
é editado a partir daqui.

---

## 1. O que este repositório é

O produto é um agente de codificação autônomo em Python que integra técnicas de engenharia de
contexto para tarefas longas em repositórios grandes. A tese que o agente encarna:

> A gestão explícita do contexto — janela, seleção e compactação — é o que permite a um agente
> de longa duração continuar coerente quando o histórico não cabe mais na janela do modelo.

O agente é o objeto de estudo do Capítulo 16 e é avaliado no Capítulo 17. Ele **não** é uma
biblioteca genérica, um framework para terceiros, nem um produto comercial. Escopo vale mais
que generalidade.

### Camadas

```
cli  ──▶  harness  ──▶  context
                  ├──▶  providers
                  ├──▶  tools
                  └──▶  state
```

A seta indica "importa". As folhas (`context`, `providers`, `tools`, `state`) não importam
`harness` nem `cli`. Essa direção é testada em `tests/test_layering.py`; quebrá-la falha o CI.

---

## 2. Skills e o roteador `/tcc`

O entrypoint de trabalho é a skill `tcc`. Um `/tcc <pedido>` lê o pedido, escolhe a skill
adequada e a carrega. O roteador não executa trabalho por conta própria.

| Skill | Carrega quando |
|---|---|
| `.claude/skills/tcc/SKILL.md` | sempre — é o roteador |
| `.claude/skills/tcc-foundations/SKILL.md` | escrever/revisar código do agente, decidir camada, config ou teste |
| `.claude/skills/tcc-bug-investigation/SKILL.md` | bug, teste falhando, comportamento estranho, regressão |
| `.claude/skills/tcc-research-writing/SKILL.md` | pesquisa, evidência, capítulo do TCC, citação, redação |
| `.claude/skills/tcc-pr-review/SKILL.md` | abrir PR, revisar diff, decidir merge |

Atalhos: `/tcc rules`, `/tcc bug`, `/tcc pr <n>`, `/tcc cap <n>`, `/tcc status`.

---

## 3. Estrutura

```
caio-code/
├── AGENTS.md                    # este arquivo (CLAUDE.md é symlink)
├── Makefile                     # ÚNICO ponto de entrada para setup, teste, lint, PR
├── pyproject.toml               # empacotamento, ruff, pytest
├── .claude/
│   ├── settings.json            # hooks SessionEnd
│   ├── hooks/                   # workers dos hooks (headless claude)
│   ├── skills/                  # as cinco skills
│   ├── agents/                  # subagentes do fluxo de pesquisa/escrita
│   └── commands/                # /tcc e /tcc-status (atalhos finos sobre as skills)
├── .githooks/pre-push           # branch atualizada + proibição de push direto na main
├── .github/workflows/           # três CIs (ver §7)
├── src/
│   └── caio_code/
│       ├── __init__.py          # versão do pacote
│       ├── config.py            # dataclasses de configuração; nada de número mágico  [a escrever]
│       ├── cli.py               # argparse; única porta de entrada do processo          [a escrever]
│       ├── harness/             # loop agêntico                                        [estrutura]
│       ├── context/             # tokens, janela, seleção, compactação                 [estrutura]
│       ├── providers/           # protocolo + stub determinístico                      [estrutura]
│       ├── tools/               # ferramentas de SWE, sandbox por raiz                 [estrutura]
│       └── state/               # estado durável entre turnos                          [estrutura]
├── tests/                       # espelha src/ (mesmos nomes de módulo)
├── scripts/
│   ├── ci/changed_tests.py      # mapeia diff → testes das pastas alteradas
│   ├── ci/pr_size.py            # 5–20 arquivos por PR
│   ├── ci/open_pr.py            # branch empilhada / abertura de PR
│   ├── install_hooks.py         # core.hooksPath = .githooks
│   ├── linear.py                # cliente GraphQL do Linear (stdlib)
│   └── smoke.py                 # smoke test offline, multiplataforma
├── docs/
│   ├── adr/                     # decisões de arquitetura
│   └── linear-workflow.md       # cards, subtarefas, stack de PRs
└── .reports/                    # bugs, sessões e saídas de hook (versionado, sem segredos)
```

Os diretórios marcados `[estrutura]` existem vazios (`__init__.py` de 0 byte) de propósito: a
estrutura foi decidida, a implementação não. Não preencha nenhum deles sem card e sem a skill
`tcc-foundations`.

Cada pasta de módulo tem o seu próprio `AGENTS.md` e `CLAUDE.md` (symlink). Eles descrevem
invariantes locais e são atualizados no mesmo PR que muda a pasta.

---

## 4. Linear — obrigatório

Workspace `Caio Medeiros`, time `CM`. Autenticação em `LINEAR_API_KEY` (nunca versionada).

1. **Toda feature e toda alteração tem card.** O card é criado antes do código, não depois.
2. **Todo avanço é um comentário isolado no card** — um comentário por avanço: decisão, teste
   que passou, métrica observada, falha encontrada. Não editar comentário antigo para
   acrescentar novidade, não acumular dois avanços num comentário.
3. **Feature maior = projeto (ou card pai) + subtarefas.** PRs pequenos (5–20 arquivos) são
   dependentes lineares uns dos outros e empilhados (§6). O comentário de progresso vai na
   subtarefa correspondente.
4. **`Done` significa "merged na main e documentado".** Trabalho pronto mas não integrado
   permanece `In Progress`.
5. O escopo do PR deve corresponder ao card. Mudança fora de escopo pede card novo ou divisão
   do PR.

Automação: `python scripts/linear.py …`. O hook de fim de sessão (§8) consolida o progresso.

---

## 5. Versionamento

- **Qualquer alteração nesta pasta exige pull request.** Push direto em `main` é bloqueado
  pelo `.githooks/pre-push` e, no servidor, por branch protection (habilitar em
  *Settings → Branches*).
- O PR é pequeno: **entre 5 e 20 arquivos** alterados. `scripts/ci/pr_size.py` falha acima de
  20 e avisa abaixo de 5.
- Branch: `<tipo>/<card>-<slug>`, por exemplo `feat/CM-31-window-policy`.
- **Antes do push**, a branch precisa estar atualizada com a base do PR (`origin/main` ou a
  branch empilhada anterior). O pre-push verifica e falha com instruções.
- Commits em inglês, imperativos, com o ID do card: `CM-31: add sliding-window policy`.
- Rebase, não merge, para atualizar a branch.

---

## 6. Stack de PRs

Features maiores são quebradas em PRs **linearmente dependentes** e empilhados no GitHub:

```
main
 └── feat/CM-31-window        (PR 1, base main)
      └── feat/CM-32-selection (PR 2, base feat/CM-31-window)
           └── feat/CM-33-compaction (PR 3, base feat/CM-32-selection)
```

Regras: cada PR compila e passa os próprios testes sozinho; o merge é sempre de baixo para
cima; ao mergear o de baixo, rebase os de cima. `make stack-new NAME=<slug> CARD=<CM-nn>`
cria a branch em cima da atual e abre o PR com `--base` correto.

---

## 7. CI

| Workflow | Gatilho | O que roda |
|---|---|---|
| `pr-tests.yml` | `pull_request` | testes **apenas das pastas modificadas** (`scripts/ci/changed_tests.py`) + `pr_size.py` |
| `main-tests.yml` | `push` em `main` | `make test` — suíte completa |
| `smoke.yml` | `pull_request` + `push` em `main` | `scripts/smoke.py` em **ubuntu, macos e windows** |

Nenhum CI usa rede nem chave de API: o provedor `stub` é o padrão dos testes. Teste que exige
LLM real é marcado `@pytest.mark.integration` e não roda no CI.

---

## 8. Hooks de fim de sessão

Dois hooks `SessionEnd` em `.claude/settings.json`, cada um disparando um `claude -p` headless
em segundo plano (o hook retorna na hora; o trabalho não bloqueia o encerramento):

1. **Aprendizado** (`session-end-learn.sh`): lê o transcript, extrai no máximo três lições
   acionáveis e, se houver mudança real, abre um PR tocando **somente** `.claude/skills/**`,
   `CLAUDE.md` ou `AGENTS.md`. Nunca toca `src/` nem `tests/`.
2. **Linear** (`session-end-linear.sh`): lê o transcript e registra o progresso no card ativo
   via `scripts/linear.py`.

Regras: os hooks são **best-effort** e nunca falham a sessão; logs em `.reports/session-end/`;
`TCC_SKIP_SESSION_HOOKS=1` desliga os dois; sessões filhas (o próprio `claude -p`) não disparam
hooks de novo. Eles rodam apenas em Linux/macOS.

---

## 9. Makefile — único ponto de entrada

`make help` lista tudo. Não invente comandos paralelos: se falta um alvo, adicione ao Makefile.

```bash
make setup        # venv + dependências + git hooks
make test         # suíte completa
make test-changed # apenas os módulos alterados (mesma lógica do CI de PR)
make smoke        # teste de fumaça ponta a ponta, sem rede
make lint         # ruff check
make format       # ruff format
make check        # lint + test
make clean        # remove .venv, caches e artefatos
```

---

## 10. Segredos e ambiente

- `.env` é ignorado; `.env.example` documenta os nomes.
- Variáveis: `LINEAR_API_KEY`, `LINEAR_PROJECT_ID`, `LINEAR_TEAM_ID`, `CAIO_CODE_MODEL`,
  `ANTHROPIC_API_KEY`, `TCC_SKIP_SESSION_HOOKS`, `TCC_HOME`.
- Nunca imprimir valor de segredo em log, PR, comentário do Linear ou transcript.
- O agente só lê `ANTHROPIC_API_KEY` no processo principal; testes não a leem.

---

## 11. Pendências conhecidas

- [ ] Preencher `LINEAR_PROJECT_ID` do projeto do agente em `.env`.
- [ ] Habilitar branch protection em `main` (PR obrigatório, CI verde, branch atualizada).
- [ ] Definir o modelo padrão em `CAIO_CODE_MODEL`.
- [ ] Primeiro ADR: por que três políticas de contexto e não uma.