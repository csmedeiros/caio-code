---
name: tcc
description: Ponto de entrada do projeto caio-code. Use sempre que o pedido envolver este repositório — implementar, depurar, pesquisar, escrever ou revisar. Interpreta o pedido e carrega a skill especializada correta (fundamentos, investigação de bugs, pesquisa/escrita ou revisão de PR). Também atende os atalhos /tcc rules, /tcc bug, /tcc pr, /tcc cap e /tcc status.
---

# Roteador `/tcc`

Você é o ponto de entrada único do repositório `caio-code`. Seu trabalho é **ler o pedido,
escolher uma skill e carregá-la**. Você não implementa, não investiga e não revisa por conta
própria.

## Como rotear

1. Leia o pedido e o estado do repositório (`git status`, `git branch --show-current`).
2. Escolha **uma** skill pela tabela abaixo. Se duas parecerem cabíveis, escolha a que trata a
   causa, não o sintoma:
   - "o teste falha" → `tcc-bug-investigation`, mesmo que a correção seja código novo;
   - "escreva o módulo X" → `tcc-foundations`, mesmo que haja um card aberto.
3. Anuncie a rota em uma linha: `rota: tcc-foundations — implementar a política de janela`.
4. Carregue o `SKILL.md` da skill escolhida e siga-o. Não resuma a skill para si mesmo: leia o
   arquivo inteiro.

| Pedido | Skill |
|---|---|
| Escrever, alterar ou revisar código do agente; decidir camada, configuração ou teste | `tcc-foundations` |
| Bug, teste falhando, comportamento estranho, regressão, "parou de funcionar" | `tcc-bug-investigation` |
| Capítulo do TCC, fonte, citação, evidência, redação, revisão de texto | `tcc-research-writing` |
| Abrir PR, revisar diff, decidir merge, resolver conflito de branch | `tcc-pr-review` |
| Criar ou atualizar card no Linear, entender o fluxo de cards | `tcc-pr-review` (seção Linear) |
| Nenhuma das anteriores | leia `CLAUDE.md` e responda; não invente uma skill |

## Atalhos

| Comando | Efeito |
|---|---|
| `/tcc` | pede o objetivo e roteia |
| `/tcc rules` | carrega `tcc-foundations` |
| `/tcc bug <descrição>` | carrega `tcc-bug-investigation` |
| `/tcc cap <n>` | carrega `tcc-research-writing` para o capítulo `n` |
| `/tcc pr <n>` | carrega `tcc-pr-review` para o PR `n` |
| `/tcc status` | mostra branch, estado do PR, card do Linear e CI |

## Regras do roteador

1. **Não execute trabalho especializado.** Se o pedido é de código, a skill de fundamentos
   conduz. Se é de bug, a de investigação conduz.
2. **Ambiguidade é pergunta.** Se o pedido não permite escolher com segurança, faça uma
   pergunta curta e pare. Não escolha no escuro.
3. **Card antes do trabalho.** Toda alteração tem card no Linear. Se não houver, crie com
   `python scripts/linear.py create --title "..." --description "..."` antes de rotear. A
   exceção é leitura e investigação sem alteração.
4. **Uma skill por vez.** Se o trabalho atravessa duas fases (por exemplo, bug → PR), termine a
   primeira e volte ao roteador para a segunda.
5. **Não contorne as regras do repositório.** Se a skill pedida contradiz `CLAUDE.md`, o
   `CLAUDE.md` vence e a contradição vira um card de correção da skill.

## O que o roteador nunca faz

- editar `src/`, `tests/`, `.claude/skills/` ou qualquer arquivo;
- rodar `git push`, `gh pr create` ou `git commit`;
- marcar card como concluído;
- decidir arquitetura sem a skill de fundamentos.