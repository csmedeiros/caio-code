# docs/

Documentação de processo e decisões. O código explica o *que*; aqui fica o *por quê*.

## Invariantes

- Toda decisão de arquitetura reversível-sem-contexto vira um ADR em `docs/adr/`, numerado e
  imutável: decisão superada é substituída por outro ADR, nunca editada.
- Documento descreve o estado atual. Se ficou falso, é bug — corrija ou apague.
- Nada de segredo, caminho pessoal absoluto ou saída de terminal efêmera.

## ADR

Formato: `NNNN-titulo-curto.md`, com `Status`, `Contexto`, `Decisão`, `Consequências` e
`Alternativas descartadas`. Uma página. O ADR registra a decisão, não a discussão.

| ADR | Decisão |
|---|---|
| `0001-estrutura-em-camadas.md` | `cli → harness → folhas` (superado por 0002/0003; mantido por histórico) |
| `0002-deepagents-como-loop.md` | deepagents/LangChain como loop; a tese mede as políticas do middleware |
| `0003-camadas-ddd.md` | camadas DDD, regra de dependência, decisões aplicadas por índice |
| `0004-medicoes-do-experimento.md` | cauda verbatim sobre o custo real, structure repair no fim de todo pipeline, cache/custo do provedor |
| `0005-modelo-de-decisao-typesafe.md` | Jev (TypeSafe) é modelo de decisão atrás de porta própria; seleção de mensagens por Noul; custo atribuído ao braço |

## Documentos

| Arquivo | Conteúdo |
|---|---|
| `linear-workflow.md` | cards, subtarefas, stack de PRs, regra de Done |
| `adr/` | decisões de arquitetura |