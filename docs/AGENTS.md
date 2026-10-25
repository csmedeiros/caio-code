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

## Documentos

| Arquivo | Conteúdo |
|---|---|
| `linear-workflow.md` | cards, subtarefas, stack de PRs, regra de Done |
| `adr/` | decisões de arquitetura |