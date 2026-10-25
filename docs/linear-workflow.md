# Fluxo de trabalho no Linear

Workspace `Caio Medeiros`, time `CM`. Autenticação por `LINEAR_API_KEY`; projeto do agente em
`LINEAR_PROJECT_ID`.

## Estrutura

```
Projeto "caio-code"
├── CM-nn  Feature: <nome>            ← card pai (In Progress)
│   ├── CM-nn+1  implementação        ← subtarefa
│   ├── CM-nn+2  testes               ← subtarefa
│   ├── CM-nn+3  execução/medição     ← subtarefa
│   └── CM-nn+4  análise e escrita    ← subtarefa
```

Feature maior **sempre** é card pai com subtarefas (`parentId` apontando para o pai). O
comentário de progresso vai na subtarefa correspondente, nunca no pai.

## Ciclo de um card

1. **Criar antes do código.** Título no imperativo e descrição com escopo e critério de
   conclusão. Sem critério de conclusão, o card não sai de `Todo`.
2. **Mover para `In Progress`** ao começar. Um card, uma pessoa.
3. **Comentar a cada avanço** — um comentário por avanço:

   ```bash
   python scripts/linear.py comment --issue CM-31 --body "Janela implementada.
   Teste: tests/context/test_window.py (7 passando). Budget exato coberto.
   Falta: política de seleção."
   ```

   O comentário responde: o que mudou, como foi verificado (comando e resultado), o que falta.
   Não editar comentário antigo para acrescentar novidade; não juntar dois avanços.
4. **`Done` só com merge e documentação.** O resultado precisa estar na `main` **e** escrito em
   algum lugar durável (README do módulo, ADR ou capítulo do TCC). Trabalho pronto mas fora da
   `main` fica `In Progress`.

## Relação com os PRs

| Tamanho | Como quebrar |
|---|---|
| 1 PR (5–20 arquivos) | um card, um PR |
| 2–4 PRs | um card pai + subtarefa por PR, PRs empilhados |
| 5+ PRs | um projeto (ou card pai) + subtarefas; revisar o escopo antes de começar |

Cada PR cita o card no corpo (`Linear: CM-31`). O `make pr CARD=CM-31` inclui essa linha.

## Stack de PRs

Cada PR aponta para a branch de baixo:

```bash
make stack-new NAME=window  CARD=CM-31            # base main
make stack-new NAME=selection CARD=CM-32 BASE=feat/cm-31-window
```

Regras: cada PR passa sozinho; merge de baixo para cima; ao mergear, rebase dos de cima;
nenhum PR empilhado é mergeado antes do pai.

## Automação

O hook `SessionEnd` (`.claude/hooks/session-end-linear.sh`) lê o transcript da sessão e posta
**um** comentário no card ativo. Ele nunca marca `Done` sem merge, e nunca cria card duplicado.

Verificação rápida:

```bash
make linear-status
```

## O que não fazer

- Card sem critério de conclusão.
- Comentário "feito" sem evidência de teste.
- Marcar `Done` porque o código está escrito.
- Um card para cinco features, ou cinco cards para uma.
- Editar o card de outra pessoa sem combinar.