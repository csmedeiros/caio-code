# Protocolo de evidência

Toda alegação da tese precisa rastrear até um registro verificado. A pipeline se recusa a
redigir um capítulo enquanto qualquer fonte dele não passar por este protocolo.

## Registros

| Arquivo | Papel | Quem escreve |
|---|---|---|
| `planejamento/papers.json` | registro de fontes (idempotente, chave = URL) | `scripts/register_paper.py` |
| `evidencias/papers/<slug>.json` | registro de verificação por fonte | verifier |
| `planejamento/bibmap.json` | citekey → paper → registro | `node scripts/tcc-map.mjs` |
| `evidencias/capitulos/cap-NN.md` | log de pesquisa do capítulo | researcher |
| `evidencias/revisao/cap-NN.md` | log de refino e aprovação | reviewer |

## Admissão de fonte (rígida)

- Apenas peer-reviewed: trilha principal de conferência, Findings, periódico ou workshop
  revisado. Preprints, relatórios técnicos e blogs não sustentam alegação. A única exceção é a
  documentação do protocolo MCP (citar com data de acesso).
- Fonte ausente de `planejamento/papers.json` não entra no bib.
- Registre pela URL canônica, não pelo link do PDF no arXiv:

```bash
python scripts/register_paper.py \
  --title "..." --authors "Sobrenome, Nome" --year AAAA \
  --url "https://arxiv.org/abs/XXXX.XXXXX" --id "arXiv:XXXX.XXXXX" \
  --chapter N --claim "alegação que a fonte sustenta" \
  --type arxiv
```

## Verificação (por fonte, por capítulo)

Abra o PDF em `papers/` e localize a passagem exata por trás de cada alegação. Depois escreva
`evidencias/papers/<slug>.json`:

```json
{
  "url": "URL canônica",
  "title": "título como publicado",
  "verified": true,
  "verified_at": "ISO-8601",
  "claim_support": "sim | parcial | nao",
  "claim_adjusted": "o que a fonte realmente sustenta, em uma frase",
  "claim_evidence": "citação literal + seção/página/tabela/figura",
  "flags": [
    "o que a fonte NÃO testa",
    "limites de escopo: modelo, idioma, benchmark, N",
    "resultado do autor vs. reproduzido",
    "ressalva de preprint/veículo"
  ],
  "role": "seminal | survey | system | benchmark"
}
```

Regras:

- `verified: true` exige citação literal, não paráfrase. Sem passagem, não está verificado.
- `claim_support: "nao"` bloqueia a citação. Remova a alegação ou troque a fonte.
- `parcial` é comum: diga exatamente que parte vale e ponha o resto em `flags`.
- `claim_adjusted` é a única frase que o redator pode usar. Sem ela, use `claim_evidence` e fique
  abaixo dele.
- `flags` são obrigações do texto. Se a fonte não testou agentes, o capítulo diz isso.

## Log de pesquisa do capítulo

`evidencias/capitulos/cap-NN.md` precisa conter (os guardas verificam):

```markdown
# Capítulo NN — Título

## Question

## Selected sources

| Fonte | Alegação usada | Evidência |
|---|---|---|

## Discarded

| Fonte | Motivo |
|---|---|

## Decision

O que é sustentado por fonte, o que é formalização deste trabalho, o que é inferência testada
pelo experimento.
```

## Auditoria de citação

```bash
node scripts/tcc-map.mjs --check
```

Toda chave do bib precisa mapear para um paper em `papers.json` e para um registro com
`verified: true` e `claim_support` em {sim, parcial}. O plugin `tcc-gate` recheca a cada escrita
de capítulo.

## Testes de exagero

Antes de aceitar uma frase, pergunte:

1. A fonte rodou agentes ou só prompts estáticos? Se estático, diga isso.
2. Usou o modelo/benchmark citado na tese? Se não, não há transferência.
3. O número vem do resumo ou da tabela? Cite a tabela quando o número é condicional.
4. É inferência deste trabalho? Rotule e aponte o experimento (E1–E6).
5. É técnica sem paper primário (janela deslizante, seleção de mensagens, contexto vs. memória
   vs. estado)? Atribua a formalização ao autor.

Se qualquer resposta mudar a frase, a frase não está pronta.